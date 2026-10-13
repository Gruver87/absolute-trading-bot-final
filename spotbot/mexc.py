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
    implied_price_micro,
    notional_micro,
    parse_micro,
    parse_micro_nonneg,
    parse_price,
    to_satoshi,
)
from dataclasses import dataclass

from spotbot.reconcile import order_is_ours
from spotbot.rules import SymbolRule, parse_symbol_rule

BASE = "https://api.mexc.com"


class MexcError(RuntimeError):
    """Exchange call failed closed."""


class MexcRateLimit(MexcError):
    """HTTP 429 or 418. The caller must stop, not retry in a loop."""


@dataclass(frozen=True)
class OrderFill:
    base_atoms: int
    quote_micro: int
    fee_micro: int
    client_order_id: str
    exchange_order_id: str
    base_fee_atoms: int = 0


def clock_allows(local_ms: int, server_ms: int, limit_ms: int = 2000) -> bool:
    """True when the local clock is close enough for recvWindow=5000."""
    if local_ms < 0 or server_ms <= 0 or limit_ms < 0:
        return False
    return abs(local_ms - server_ms) <= limit_ms


class MexcClient:
    def __init__(self, api_key: str = "", api_secret: str = "", timeout_sec: int = 8) -> None:
        if timeout_sec < 1:
            raise MexcError("timeout_sec must be >= 1")
        self._key = api_key
        self._secret = api_secret
        self._timeout = timeout_sec
        self._local = threading.local()
        self._rules: dict[str, SymbolRule] = {}

    def forget_rules(self) -> None:
        """Drop cached exchangeInfo so a later cycle sees a new fee or a halted pair."""
        self._rules.clear()

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
            try:
                rows.append(
                    (
                        parse_price(str(row[1])),
                        parse_price(str(row[2])),
                        parse_price(str(row[3])),
                        parse_price(str(row[4])),
                        parse_micro_nonneg(str(row[7])),
                    )
                )
            except MoneyError as exc:
                raise MexcError(f"bad kline number for {symbol}") from exc
        return rows

    def depth_notional(self, symbol: str, limit: int = 20) -> tuple[int, int]:
        """Bid and ask notional in micro-USDT for the top of the book."""
        payload = self._public("/api/v3/depth", {"symbol": symbol, "limit": str(limit)})
        if not isinstance(payload, dict):
            raise MexcError(f"no depth for {symbol}")
        return _side_notional(payload.get("bids")), _side_notional(payload.get("asks"))

    def book_top(self, symbol: str) -> tuple[int, int]:
        """Best bid and ask. One public request, not a socket. A crossed book is refused."""
        payload = self._public("/api/v3/ticker/bookTicker", {"symbol": symbol})
        if not isinstance(payload, dict):
            raise MexcError(f"no book ticker for {symbol}")
        try:
            bid = parse_price(str(payload.get("bidPrice")))
            ask = parse_price(str(payload.get("askPrice")))
        except MoneyError as exc:
            raise MexcError(f"bad book ticker for {symbol}") from exc
        if ask < bid:
            raise MexcError(f"crossed book for {symbol}")
        return bid, ask

    def book_spread_bps(self, symbol: str) -> int:
        """Top-of-book width in basis points. One public request, not a socket."""
        from spotbot.guards import top_spread_bps

        try:
            bid, ask = self.book_top(symbol)
            return top_spread_bps(bid, ask)
        except ValueError as exc:
            raise MexcError(f"bad book ticker for {symbol}") from exc

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
        try:
            return parse_price(str(payload["price"]))
        except MoneyError as exc:
            raise MexcError(f"bad price for {symbol}") from exc

    def server_time_ms(self) -> int:
        """Exchange clock in milliseconds. Public, no order."""
        payload = self._public("/api/v3/time", {})
        if not isinstance(payload, dict):
            raise MexcError("server time is not an object")
        raw = payload.get("serverTime")
        if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
            raise MexcError("server time missing")
        return raw

    def symbol_rule(self, symbol: str) -> SymbolRule:
        cached = self._rules.get(symbol)
        if cached is not None:
            return cached
        payload = self._public("/api/v3/exchangeInfo", {"symbol": symbol})
        if not isinstance(payload, dict):
            raise MexcError(f"no exchangeInfo for {symbol}")
        rows = payload.get("symbols")
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            raise MexcError(f"no exchangeInfo row for {symbol}")
        rule = parse_symbol_rule(rows[0])
        self._rules[symbol] = rule
        return rule

    def market_buy_quote(self, symbol: str, quote_micro: int, client_order_id: str) -> OrderFill:
        """Spend quote_micro USDT. The client id is stored so a restart can find the order."""
        body = self._signed(
            "POST",
            "/api/v3/order",
            {
                "symbol": symbol,
                "side": "BUY",
                "type": "MARKET",
                "quoteOrderQty": format_fixed(quote_micro, SATOSHI_MULTIPLIER),
                "newClientOrderId": client_order_id,
            },
        )
        if not order_is_ours(body, symbol, "BUY", client_order_id):
            raise MexcError(f"buy ack is not {symbol} {client_order_id}")
        _require_filled(body, "buy")
        executed = str(body.get("executedQty") or "")
        if not executed:
            raise MexcError(f"buy {symbol} returned no executedQty")
        quote = _filled_quote(body, "buy")
        if quote > quote_micro:
            raise MexcError(f"buy {symbol} filled more quote than requested")
        usdt_fee, base_fee = ack_commission(body, _base_asset(symbol))
        if usdt_fee > quote:
            raise MexcError(f"buy {symbol} commission is above the fill")
        return OrderFill(
            _base_atoms(executed),
            quote,
            usdt_fee,
            client_order_id,
            str(body.get("orderId") or ""),
            base_fee,
        )

    def market_sell_base(self, symbol: str, base_atoms: int, client_order_id: str) -> OrderFill:
        """Return the quote credit. USDT commission is included when the ack carries it."""
        body = self._signed(
            "POST",
            "/api/v3/order",
            {
                "symbol": symbol,
                "side": "SELL",
                "type": "MARKET",
                "quantity": format_fixed(base_atoms, BASE_ATOMS),
                "newClientOrderId": client_order_id,
            },
        )
        if not order_is_ours(body, symbol, "SELL", client_order_id):
            raise MexcError(f"sell ack is not {symbol} {client_order_id}")
        credit, fee, base_fee = _sell_credit(body, _base_asset(symbol))
        executed = str(body.get("executedQty") or "")
        if not executed:
            raise MexcError(f"sell {symbol} returned no executedQty")
        sold = _base_atoms(executed)
        if sold > base_atoms:
            raise MexcError(f"sell {symbol} filled more base than requested")
        return OrderFill(
            sold,
            credit,
            fee,
            client_order_id,
            str(body.get("orderId") or ""),
            base_fee,
        )

    def order_by_client(self, symbol: str, client_order_id: str) -> dict[str, Any]:
        body = self._signed(
            "GET",
            "/api/v3/order",
            {"symbol": symbol, "origClientOrderId": client_order_id},
        )
        return body

    def my_trades(self, symbol: str, limit: int = 100, order_id: str = "") -> list[object]:
        """Trades for one symbol. Pass order_id so the fee is not taken from a later fill."""
        params = {"symbol": symbol, "limit": str(limit)}
        if order_id:
            params["orderId"] = order_id
        body = self._signed("GET", "/api/v3/myTrades", params)
        if not isinstance(body, list):
            raise MexcError(f"trades for {symbol} are not a list")
        if len(body) >= limit:
            raise MexcError(f"trades for {symbol} filled the page, fee is incomplete")
        return body

    def spot_balances(self) -> tuple[int, int, dict[str, int], dict[str, int]]:
        """Total USDT, free USDT, total base atoms, and free base atoms. Signed read, no order."""
        body = self._signed("GET", "/api/v3/account", {})
        return parse_account(body)

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
        if response.status_code in (418, 429):
            wait = response.headers.get("Retry-After", "")
            raise MexcRateLimit(f"{path} HTTP {response.status_code} retry-after={wait or 'unknown'}")
        if response.status_code != 200:
            raise MexcError(f"{path} HTTP {response.status_code}")
        body = _json_body(response, path)
        if isinstance(body, dict):
            _reject_exchange_code(body)
        return body

    def _signed(self, method: str, path: str, params: dict[str, str]) -> dict[str, Any]:
        if not self._key or not self._secret:
            raise MexcError("signed call without API key")
        query = dict(params)
        query["timestamp"] = str(int(time.time() * 1000))
        query["recvWindow"] = "5000"
        encoded = urlencode(query)
        signature = hmac.new(self._secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        url = f"{BASE}{path}?{encoded}&signature={signature}"
        headers = {"X-MEXC-APIKEY": self._key}
        try:
            response = self._session().request(method, url, headers=headers, timeout=self._timeout)
        except requests.RequestException as exc:
            raise MexcError(str(exc)) from exc
        if response.status_code in (418, 429):
            wait = response.headers.get("Retry-After", "")
            raise MexcRateLimit(f"order HTTP {response.status_code} retry-after={wait or 'unknown'}")
        if response.status_code != 200:
            raise MexcError(f"order HTTP {response.status_code}: {response.text[:180]}")
        body = _json_body(response, "order")
        if not isinstance(body, dict):
            raise MexcError("order response is not an object")
        _reject_exchange_code(body)
        return body


def _reject_exchange_code(body: dict[str, Any]) -> None:
    """MEXC sometimes returns HTTP 200 with an error code instead of an order."""
    if "code" not in body:
        return
    code = body.get("code")
    if code in (0, 200, "0", "200"):
        return
    msg = str(body.get("msg") or body.get("message") or code)
    raise MexcError(f"exchange code {code}: {msg[:180]}")


def _json_body(response: requests.Response, label: str) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise MexcError(f"{label} is not json") from exc


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
            raise MexcError("depth level is incomplete")
        try:
            price = parse_price(str(level[0]))
            qty_micro = parse_micro_nonneg(str(level[1]))
        except MoneyError as exc:
            raise MexcError("depth level is not decimal") from exc
        atoms = qty_micro * (BASE_ATOMS // MICRO)
        total += notional_micro(atoms, price)
    return total


def _base_atoms(qty: str) -> int:
    try:
        atoms = to_satoshi(qty) * (BASE_ATOMS // MICRO)
    except MoneyError as exc:
        raise MexcError(f"filled quantity is not decimal: {qty}") from exc
    if atoms <= 0:
        raise MexcError(f"filled quantity rounds to zero: {qty}")
    return int(atoms)


def new_client_order_id(symbol: str, side: str) -> str:
    digest = hashlib.sha256(f"{side}:{symbol}:{time.time_ns()}".encode()).hexdigest()
    return digest[:32]


def executed_fill(body: dict[str, Any]) -> tuple[int, int, int] | None:
    """Base, quote, and price of what actually traded.

    None only when the executed quantity is empty or zero. A positive quantity
    that is not a decimal, or a zero quote beside it, is an error: that is not
    an empty fill.
    """
    executed = str(body.get("executedQty") or "")
    raw = body.get("cummulativeQuoteQty") or body.get("cumulativeQuoteQty")
    if executed.strip() in ("", "0", "0.0", "0.00", "0.00000000"):
        return None
    base = _base_atoms(executed)
    if raw in (None, ""):
        raise MexcError("executed order is missing quote qty")
    try:
        quote = parse_micro(str(raw))
    except MoneyError as exc:
        raise MexcError("executed order quote is not decimal") from exc
    if quote <= 0:
        raise MexcError("executed order quote is zero")
    try:
        return base, quote, implied_price_micro(quote, base)
    except MoneyError as exc:
        raise MexcError("executed order has no price") from exc


def quantities_from_order(body: dict[str, Any]) -> tuple[int, int, int]:
    """Base atoms, quote micro, and the implied price. The order must be filled."""
    _require_filled(body, "recover")
    got = executed_fill(body)
    if got is None:
        raise MexcError("filled order is missing qty")
    return got


def _require_filled(body: dict[str, Any], label: str) -> None:
    status = str(body.get("status") or "")
    if status not in ("FILLED", "2"):
        raise MexcError(f"{label} status {status or 'missing'}")


def _filled_quote(body: dict[str, Any], label: str) -> int:
    """Quote that actually traded. The requested amount is not a fill."""
    raw = body.get("cummulativeQuoteQty") or body.get("cumulativeQuoteQty")
    if raw in (None, ""):
        raise MexcError(f"{label} has no quote qty")
    try:
        quote = parse_micro(str(raw))
    except MoneyError as exc:
        raise MexcError(f"{label} quote is not decimal") from exc
    if quote <= 0:
        raise MexcError(f"{label} quote is zero")
    return quote


def _base_asset(symbol: str) -> str:
    if not symbol.endswith("USDT") or len(symbol) <= 4:
        raise MexcError(f"{symbol or 'missing'} is not a USDT pair")
    return symbol[:-4]


def ack_commission(body: dict[str, Any], base_asset: str) -> tuple[int, int]:
    """USDT fee and base fee named on the ack. Both zero means the ack omitted the fee.

    A named fee in any other asset, or a positive fee that rounds to zero, is refused.
    """
    commission = body.get("commission")
    if commission in (None, ""):
        return 0, 0
    raw = str(commission).strip()
    if raw in ("", "0", "0.0", "0.00"):
        return 0, 0
    asset = str(body.get("commissionAsset") or "").upper()
    if not base_asset:
        raise MexcError("ack commission needs a base asset")
    try:
        if asset == "USDT":
            fee = parse_micro_nonneg(raw)
            if fee <= 0:
                raise MexcError("USDT commission rounds to zero")
            return fee, 0
        if asset == base_asset:
            atoms = to_satoshi(raw) * (BASE_ATOMS // MICRO)
            if atoms <= 0:
                raise MexcError("base commission rounds to zero")
            return 0, atoms
    except MoneyError as exc:
        raise MexcError("ack commission is not decimal") from exc
    raise MexcError(f"ack commission is in {asset or 'missing'}")


def _sell_credit(body: dict[str, Any], base_asset: str) -> tuple[int, int, int]:
    _require_filled(body, "sell")
    raw = body.get("cummulativeQuoteQty") or body.get("cumulativeQuoteQty")
    if raw in (None, ""):
        raise MexcError("sell ack has no quote qty")
    credit = _filled_quote(body, "sell")
    fee, base_fee = ack_commission(body, base_asset)
    if fee > credit:
        raise MexcError("commission above the sell fill")
    return credit - fee, fee, base_fee


def parse_account(payload: dict[str, Any]) -> tuple[int, int, dict[str, int], dict[str, int]]:
    """Total USDT, free USDT, total base atoms, and free base atoms."""
    rows = payload.get("balances")
    if not isinstance(rows, list):
        raise MexcError("account balances missing")
    total_usdt = 0
    free_usdt = 0
    bases: dict[str, int] = {}
    free_bases: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise MexcError("balance row is not an object")
        asset = str(row.get("asset") or "")
        free = _qty_micro(row.get("free"))
        locked = _qty_micro(row.get("locked"))
        if not asset:
            if free or locked:
                raise MexcError("balance row has no asset")
            continue
        if asset == "USDT":
            free_usdt += free
            total_usdt += free + locked
            continue
        free_atoms = free * (BASE_ATOMS // MICRO)
        total_atoms = (free + locked) * (BASE_ATOMS // MICRO)
        if total_atoms > 0:
            bases[asset] = bases.get(asset, 0) + total_atoms
        if free_atoms > 0:
            free_bases[asset] = free_bases.get(asset, 0) + free_atoms
    return total_usdt, free_usdt, bases, free_bases


def _qty_micro(raw: object) -> int:
    if raw in (None, ""):
        return 0
    try:
        return to_satoshi(str(raw))
    except MoneyError as exc:
        raise MexcError(f"balance is not decimal: {raw}") from exc
