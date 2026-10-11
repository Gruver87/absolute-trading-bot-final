"""MEXC spot public market data and, only in live mode, signed market orders."""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from typing import Any
from urllib.parse import urlencode

import requests

from spotbot.money import (
    BASE_ATOMS,
    MICRO,
    SATOSHI_MULTIPLIER,
    MoneyError,
    format_fixed,
    parse_micro,
    parse_micro_nonneg,
    to_satoshi,
)

BASE = "https://api.mexc.com"


class MexcError(RuntimeError):
    """Exchange call failed closed."""


class MexcClient:
    def __init__(self, api_key: str = "", api_secret: str = "", timeout_sec: int = 8) -> None:
        if timeout_sec < 1:
            raise MexcError("timeout_sec must be >= 1")
        self._key = api_key
        self._secret = api_secret
        self._timeout = timeout_sec
        self._local = threading.local()

    def klines(self, symbol: str, interval: str = "5m", limit: int = 80) -> list[int]:
        return [row[4] for row in self.ohlcv(symbol, interval, limit)]

    def ohlcv(self, symbol: str, interval: str = "5m", limit: int = 30) -> list[tuple[int, int, int, int, int]]:
        """Rows of open, high, low, close, quote-volume, all in micro-USDT."""
        payload = self._public(
            "/api/v3/klines",
            {"symbol": symbol, "interval": interval, "limit": str(limit)},
        )
        if not isinstance(payload, list) or len(payload) < 2:
            raise MexcError(f"no klines for {symbol}")
        rows: list[tuple[int, int, int, int, int]] = []
        for row in payload:
            if not isinstance(row, list) or len(row) < 8:
                raise MexcError(f"bad kline row for {symbol}")
            rows.append(
                (
                    parse_micro(str(row[1])),
                    parse_micro(str(row[2])),
                    parse_micro(str(row[3])),
                    parse_micro(str(row[4])),
                    parse_micro_nonneg(str(row[7])),
                )
            )
        return rows

    def depth_notional(self, symbol: str, limit: int = 20) -> tuple[int, int]:
        """Bid and ask notional in micro-USDT for the top of the book."""
        payload = self._public("/api/v3/depth", {"symbol": symbol, "limit": str(limit)})
        if not isinstance(payload, dict):
            raise MexcError(f"no depth for {symbol}")
        return _side_notional(payload.get("bids")), _side_notional(payload.get("asks"))

    def liquid_usdt(self, min_quote_micro: int, change_min_bps: int, change_max_bps: int, cap: int) -> list[str]:
        """USDT pairs whose 24h quote volume is real and whose move has started, not finished."""
        payload = self._public("/api/v3/ticker/24hr", {})
        if not isinstance(payload, list):
            raise MexcError("24h ticker is not a list")
        ranked: list[tuple[int, str]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "")
            if not symbol.endswith("USDT"):
                continue
            try:
                quote = parse_micro(str(item.get("quoteVolume") or "0"))
                change_bps = int(DecimalChange(str(item.get("priceChangePercent") or "0")))
            except (MoneyError, ValueError):
                continue
            if quote < min_quote_micro:
                continue
            if change_bps < change_min_bps or change_bps > change_max_bps:
                continue
            ranked.append((quote, symbol))
        ranked.sort(reverse=True)
        return [symbol for _, symbol in ranked[:cap]]

    def price(self, symbol: str) -> int:
        payload = self._public("/api/v3/ticker/price", {"symbol": symbol})
        if not isinstance(payload, dict) or "price" not in payload:
            raise MexcError(f"no price for {symbol}")
        return parse_micro(str(payload["price"]))

    def market_buy_quote(self, symbol: str, quote_micro: int) -> int:
        """Spend quote_micro USDT. Return filled base quantity in 1e8 atoms."""
        body = self._signed(
            "POST",
            "/api/v3/order",
            {
                "symbol": symbol,
                "side": "BUY",
                "type": "MARKET",
                "quoteOrderQty": format_fixed(quote_micro, SATOSHI_MULTIPLIER),
            },
        )
        executed = str(body.get("executedQty") or "")
        if not executed:
            raise MexcError(f"buy {symbol} returned no executedQty")
        return _base_atoms(executed)

    def market_sell_base(self, symbol: str, base_atoms: int) -> None:
        qty = format_fixed(base_atoms, BASE_ATOMS)
        self._signed(
            "POST",
            "/api/v3/order",
            {"symbol": symbol, "side": "SELL", "type": "MARKET", "quantity": qty},
        )

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            self._local.session = session
        return session

    def _public(self, path: str, params: dict[str, str]) -> Any:
        try:
            response = self._session().get(BASE + path, params=params, timeout=self._timeout)
        except requests.RequestException as exc:
            raise MexcError(str(exc)) from exc
        if response.status_code != 200:
            raise MexcError(f"{path} HTTP {response.status_code}")
        return response.json()

    def _signed(self, method: str, path: str, params: dict[str, str]) -> dict[str, Any]:
        if not self._key or not self._secret:
            raise MexcError("signed call without API key")
        query = dict(params)
        query["timestamp"] = str(int(time.time() * 1000))
        encoded = urlencode(query)
        signature = hmac.new(self._secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        url = f"{BASE}{path}?{encoded}&signature={signature}"
        headers = {"X-MEXC-APIKEY": self._key}
        try:
            response = self._session().request(method, url, headers=headers, timeout=self._timeout)
        except requests.RequestException as exc:
            raise MexcError(str(exc)) from exc
        if response.status_code != 200:
            raise MexcError(f"order HTTP {response.status_code}: {response.text[:180]}")
        body = response.json()
        if not isinstance(body, dict):
            raise MexcError("order response is not an object")
        return body


def DecimalChange(text: str) -> int:
    """24h percent string to basis points, truncating toward zero."""
    from decimal import Decimal, ROUND_DOWN

    raw = text.strip()
    if not raw:
        raise ValueError("empty change")
    bps = (Decimal(raw) * 100).to_integral_value(rounding=ROUND_DOWN)
    return int(bps)


def _side_notional(levels: object) -> int:
    if not isinstance(levels, list):
        raise MexcError("depth side is not a list")
    total = 0
    for level in levels:
        if not isinstance(level, list) or len(level) < 2:
            continue
        price = parse_micro(str(level[0]))
        qty_micro = parse_micro_nonneg(str(level[1]))
        total += price * qty_micro // MICRO
    return total


def _base_atoms(qty: str) -> int:
    atoms = to_satoshi(qty) * (BASE_ATOMS // MICRO)
    if atoms <= 0:
        raise MexcError(f"filled quantity rounds to zero: {qty}")
    return int(atoms)
