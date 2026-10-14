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
    decimal_text,
    format_fixed,
    implied_price_micro,
    notional_micro,
    parse_micro,
    parse_micro_nonneg,
    parse_price,
    decimal_zero,
    to_satoshi,
)
from dataclasses import dataclass

from spotbot.reconcile import order_is_ours
from spotbot.rules import SymbolRule, parse_symbol_rule

# The RSI cycle asks for this many candles. The last one is still open.
KLINE_LIMIT = 80

BASE = "https://api.mexc.com"


class MexcError(RuntimeError):
    """Exchange call failed closed."""


class MexcRateLimit(MexcError):
    """HTTP or body 403, 418, or 429. The caller must stop, not retry in a loop.

    retry_after_sec is the Retry-After header in seconds, when it is a plain integer.
    """

    def __init__(self, message: str, retry_after_sec: int | None = None) -> None:
        super().__init__(message)
        if retry_after_sec is not None and (isinstance(retry_after_sec, bool) or not isinstance(retry_after_sec, int) or retry_after_sec < 1):
            retry_after_sec = None
        self.retry_after_sec = retry_after_sec


class MexcOrderAccepted(MexcError):
    """The exchange accepted the order. The ack is not a finished fill yet.

    exchange_order_id is empty when the ack did not carry a digit id.
    """

    def __init__(self, message: str, exchange_order_id: str) -> None:
        super().__init__(message)
        self.exchange_order_id = exchange_order_id if isinstance(exchange_order_id, str) else ""


_MAX_BACKOFF_SEC = 259_200
_MIN_UNKNOWN_BACKOFF_SEC = 120


def backoff_sec(retry_after_sec: int | None, interval_sec: int) -> int:
    """Seconds to stay silent after a limit. The cycle interval is the floor.

    A missing or unreadable Retry-After waits at least two minutes. Three days
    is the longest ban MEXC documents, so a larger header is cut there.
    """
    if isinstance(interval_sec, bool) or not isinstance(interval_sec, int) or interval_sec < 1:
        raise MexcError("backoff interval must be an integer >= 1")
    if interval_sec > 86_400:
        interval_sec = 86_400
    stated = retry_after_sec
    if stated is None or isinstance(stated, bool) or not isinstance(stated, int) or stated < 1:
        stated = _MIN_UNKNOWN_BACKOFF_SEC
    if stated > _MAX_BACKOFF_SEC:
        stated = _MAX_BACKOFF_SEC
    return max(interval_sec, stated)


def _net_text(exc: BaseException) -> str:
    """A transport error is logged short. The URL and the body are not copied whole."""
    text = str(exc)
    return text if len(text) <= 180 else text[:180]


def _retry_after_sec(value: object) -> int | None:
    """Parse a delta-seconds Retry-After. An HTTP date is not guessed.

    A value that is not short digit text is an unknown wait, not a huge integer.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) > 8 or not text.isdigit():
        return None
    return int(text)


def _api_path(path: object) -> str:
    """A relative MEXC path. A host, a query, or an at-sign is not requested."""
    if not isinstance(path, str) or not path.startswith("/api/v3/") or len(path) > 96:
        raise MexcError("request path is refused")
    rest = path[len("/api/v3/") :]
    if not rest or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/_-" for ch in rest):
        raise MexcError("request path is refused")
    return path


def _query(params: object) -> dict[str, str]:
    """Query text. A number or a line break is not signed or sent."""
    if not isinstance(params, dict) or len(params) > 16:
        raise MexcError("query is not an object" if not isinstance(params, dict) else "query is too wide")
    out: dict[str, str] = {}
    for key, value in params.items():
        if (
            not isinstance(key, str)
            or not isinstance(value, str)
            or not key
            or len(key) > 64
            or len(value) > 80
            or any(ch in key or ch in value for ch in "\r\n\x00")
        ):
            raise MexcError("query value is not text")
        out[key] = value
    return out


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
    if isinstance(local_ms, bool) or isinstance(server_ms, bool) or isinstance(limit_ms, bool) or not isinstance(local_ms, int) or not isinstance(server_ms, int) or not isinstance(limit_ms, int):
        return False
    if local_ms < 0 or server_ms <= 0 or limit_ms < 0 or local_ms >= 10**15 or server_ms >= 10**15 or limit_ms > 10_000:
        return False
    return abs(local_ms - server_ms) <= limit_ms


class MexcClient:
    def __init__(self, api_key: str = "", api_secret: str = "", timeout_sec: int = 8) -> None:
        if isinstance(timeout_sec, bool) or not isinstance(timeout_sec, int) or timeout_sec < 1 or timeout_sec > 30:
            raise MexcError("timeout_sec must be >= 1")
        if not isinstance(api_key, str) or not isinstance(api_secret, str):
            raise MexcError("API key is not text")
        if len(api_key) > 256 or len(api_secret) > 256 or any(ch in api_key or ch in api_secret for ch in "\r\n\x00"):
            raise MexcError("API key is not a single line")
        self._key = api_key
        self._secret = api_secret
        self._timeout = timeout_sec
        self._local = threading.local()
        self._rules: dict[str, SymbolRule] = {}

    def forget_rules(self) -> None:
        """Drop cached exchangeInfo so a later cycle sees a new fee or a halted pair."""
        self._rules.clear()

    def klines(self, symbol: str, interval: str = "5m", limit: int = KLINE_LIMIT) -> list[int]:
        """Close of each candle. Quote volume is not a price."""
        _public_limit(limit, "kline")
        return [row[3] for row in self.ohlcv(symbol, interval, limit)]

    def ohlcv(self, symbol: str, interval: str = "5m", limit: int = 30) -> list[tuple[int, int, int, int, int]]:
        """Rows of open, high, low, close, quote-volume, all in micro-USDT."""
        symbol = _text_symbol(symbol)
        if not isinstance(interval, str) or not interval:
            raise MexcError("kline interval is not text")
        _public_limit(limit, "kline")
        if limit > 1_000:
            raise MexcError("kline limit is too large")
        _interval_ms(interval)
        span = _interval_ms(interval)
        return parse_klines(symbol, self._kline_raw(symbol, interval, limit, span), span)

    def ohlcv_stamped(
        self, symbol: str, interval: str = "5m", limit: int = 30
    ) -> list[tuple[int, int, int, int, int, int]]:
        """Open time, then open, high, low, close, and quote volume."""
        symbol = _text_symbol(symbol)
        if not isinstance(interval, str) or not interval:
            raise MexcError("kline interval is not text")
        _public_limit(limit, "kline")
        if limit > 1_000:
            raise MexcError("kline limit is too large")
        span = _interval_ms(interval)
        return _parsed_klines(symbol, self._kline_raw(symbol, interval, limit, span), span, 2)

    def klines_between(self, symbol: str, interval: str, start_ms: int, end_ms: int) -> list[tuple[int, int]]:
        """Close of each candle in [start, end), with its open time. Pages of 500."""
        symbol = _text_symbol(symbol)
        if not isinstance(interval, str) or not interval:
            raise MexcError("kline interval is not text")
        span = _interval_ms(interval)
        if (
            isinstance(start_ms, bool)
            or isinstance(end_ms, bool)
            or not isinstance(start_ms, int)
            or not isinstance(end_ms, int)
            or start_ms <= 0
            or end_ms <= start_ms
            or end_ms - start_ms > span * 6_000
        ):
            raise MexcError(f"kline history for {symbol} is short")
        cursor = start_ms
        found: list[tuple[int, int]] = []
        for page in range(16):
            if cursor >= end_ms:
                break
            if page:
                time.sleep(0.2)
            payload = self._public(
                "/api/v3/klines",
                {
                    "symbol": symbol,
                    "interval": interval,
                    "limit": "500",
                    "startTime": str(cursor),
                    "endTime": str(end_ms),
                },
            )
            batch = _timed_closes(symbol, payload, span)
            nxt = 0
            for opened, close in batch:
                if opened < cursor or opened >= end_ms:
                    continue
                if found and opened <= found[-1][0]:
                    continue
                found.append((opened, close))
                nxt = opened + span
            if nxt <= cursor:
                raise MexcError(f"kline history for {symbol} is short")
            cursor = nxt
        else:
            if cursor < end_ms:
                raise MexcError(f"kline history for {symbol} is short")
        if len(found) < 2:
            raise MexcError(f"kline history for {symbol} is short")
        return found

    def _kline_raw(self, symbol: str, interval: str, limit: int, span: int) -> list:
        if limit <= 500:
            payload = self._public(
                "/api/v3/klines",
                {"symbol": symbol, "interval": interval, "limit": str(limit)},
            )
            if not isinstance(payload, list):
                raise MexcError(f"no klines for {symbol}")
            return payload
        recent = self._public(
            "/api/v3/klines",
            {"symbol": symbol, "interval": interval, "limit": "500"},
        )
        if not isinstance(recent, list) or not recent or not isinstance(recent[0], list):
            raise MexcError(f"no klines for {symbol}")
        boundary = recent[0][0]
        if isinstance(boundary, bool) or not isinstance(boundary, int) or boundary <= 0:
            raise MexcError(f"kline time for {symbol} is not a timestamp")
        left = limit - len(recent)
        if left < 1:
            return recent
        start = boundary - left * span
        if start <= 0:
            raise MexcError(f"kline history for {symbol} is short")
        time.sleep(0.2)
        earlier = self._public(
            "/api/v3/klines",
            {
                "symbol": symbol,
                "interval": interval,
                "limit": str(left),
                "startTime": str(start),
                "endTime": str(boundary),
            },
        )
        return _join_klines(earlier, recent, symbol)

    def depth_notional(self, symbol: str, limit: int = 20) -> tuple[int, int]:
        """Bid and ask notional in micro-USDT for the top of the book."""
        symbol = _text_symbol(symbol)
        _public_limit(limit, "depth")
        payload = self._public("/api/v3/depth", {"symbol": symbol, "limit": str(limit)})
        return depth_notionals(payload, symbol)

    def book_top(self, symbol: str) -> tuple[int, int]:
        """Best bid and ask. One public request, not a socket. A crossed book is refused."""
        symbol = _text_symbol(symbol)
        payload = self._public("/api/v3/ticker/bookTicker", {"symbol": symbol})
        return book_prices(payload, symbol)

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
        bounds = (min_quote_micro, change_min_bps, change_max_bps, cap)
        if any(isinstance(item, bool) or not isinstance(item, int) for item in bounds) or cap < 1 or cap > 32:
            return []
        if min_quote_micro >= 10**24 or change_min_bps <= -10**9 or change_max_bps >= 10**9:
            return []
        payload = self._public("/api/v3/ticker/24hr", {})
        if not isinstance(payload, list):
            raise MexcError("24h ticker is not a list")
        return rank_liquid(payload, min_quote_micro, change_min_bps, change_max_bps, cap)

    def price(self, symbol: str) -> int:
        symbol = _text_symbol(symbol)
        payload = self._public("/api/v3/ticker/price", {"symbol": symbol})
        return ticker_price(payload, symbol)

    def server_time_ms(self) -> int:
        """Exchange clock in milliseconds. Public, no order."""
        payload = self._public("/api/v3/time", {})
        if not isinstance(payload, dict) or len(payload) > 8:
            raise MexcError("server time is not an object")
        stamp = positive_int(payload.get("serverTime"), "server time")
        if stamp >= 10**15:
            raise MexcError("server time is not a timestamp")
        return stamp

    def symbol_rule(self, symbol: str) -> SymbolRule:
        if not isinstance(symbol, str) or not symbol:
            raise MexcError("exchangeInfo symbol is not text")
        from spotbot.state import usdt_symbol_ok

        if not usdt_symbol_ok(symbol):
            raise MexcError("exchangeInfo symbol is not a USDT pair")
        cached = self._rules.get(symbol)
        if cached is not None:
            return cached
        payload = self._public("/api/v3/exchangeInfo", {"symbol": symbol})
        if not isinstance(payload, dict) or len(payload) > 16:
            raise MexcError(f"no exchangeInfo for {symbol}" if not isinstance(payload, dict) else "exchangeInfo is too wide")
        rows = payload.get("symbols")
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            raise MexcError(f"no exchangeInfo row for {symbol}")
        if len(rows) != 1:
            raise MexcError(f"exchangeInfo for {symbol} has more than one row")
        named = rows[0].get("symbol")
        if not isinstance(named, str) or named != symbol:
            raise MexcError(f"exchangeInfo is not {symbol}")
        rule = parse_symbol_rule(rows[0])
        if len(self._rules) >= 32:
            self._rules.clear()
        self._rules[symbol] = rule
        return rule

    def market_buy_quote(self, symbol: str, quote_micro: int, client_order_id: str) -> OrderFill:
        """Spend quote_micro USDT. The client id is stored so a restart can find the order."""
        _order_request(symbol, client_order_id, quote_micro)
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
        order_id = _accepted_order_id(body, symbol, "BUY", client_order_id)
        try:
            _require_filled(body, "buy")
            executed = _filled_base_text(body, "buy")
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
                order_id,
                base_fee,
            )
        except MexcRateLimit:
            raise
        except MexcError as exc:
            raise MexcOrderAccepted(_net_text(exc), order_id) from exc

    def market_sell_base(self, symbol: str, base_atoms: int, client_order_id: str) -> OrderFill:
        """Return the quote credit. USDT commission is included when the ack carries it."""
        _order_request(symbol, client_order_id, base_atoms)
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
        order_id = _accepted_order_id(body, symbol, "SELL", client_order_id)
        try:
            credit, fee, base_fee = _sell_credit(body, _base_asset(symbol))
            executed = _filled_base_text(body, "sell")
            sold = _base_atoms(executed)
            if sold > base_atoms:
                raise MexcError(f"sell {symbol} filled more base than requested")
            return OrderFill(
                sold,
                credit,
                fee,
                client_order_id,
                order_id,
                base_fee,
            )
        except MexcRateLimit:
            raise
        except MexcError as exc:
            raise MexcOrderAccepted(_net_text(exc), order_id) from exc

    def order_by_client(self, symbol: str, client_order_id: str) -> dict[str, Any]:
        from spotbot.state import client_id_ok, usdt_symbol_ok

        if not usdt_symbol_ok(symbol) or not client_id_ok(client_order_id):
            raise MexcError("order lookup is missing a pair or a client id")
        body = self._signed(
            "GET",
            "/api/v3/order",
            {"symbol": symbol, "origClientOrderId": client_order_id},
        )
        return body

    def my_trades(self, symbol: str, limit: int = 100, order_id: str = "") -> list[object]:
        """Trades for one symbol. Pass order_id so the fee is not taken from a later fill."""
        symbol = _text_symbol(symbol)
        _public_limit(limit, "trade")
        if not isinstance(order_id, str):
            raise MexcError("trade order id is not text")
        if order_id and (len(order_id) > 32 or not order_id.isdigit()):
            raise MexcError("trade order id is not digits")
        params = {"symbol": symbol, "limit": str(limit)}
        if order_id:
            params["orderId"] = order_id
        body = self._signed("GET", "/api/v3/myTrades", params, as_list=True)
        if not isinstance(body, list):
            raise MexcError(f"trades for {symbol} are not a list")
        if len(body) >= limit:
            raise MexcError(f"trades for {symbol} filled the page, fee is incomplete")
        for row in body:
            if not isinstance(row, dict):
                raise MexcError("trade row is not an object")
            if len(row) > 32:
                raise MexcError("trade row is too wide")
        return body

    def spot_balances(self) -> tuple[int, int, dict[str, int], dict[str, int]]:
        """Total USDT, free USDT, total base atoms, and free base atoms. Signed read, no order."""
        body = self._signed("GET", "/api/v3/account", {})
        return parse_account(body)

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.trust_env = False
            session.cookies = _DropCookies()
            self._local.session = session
        return session

    def _public(self, path: str, params: dict[str, str]) -> Any:
        path = _api_path(path)
        params = _query(params)
        try:
            response = self._session().get(
                BASE + path, params=params, timeout=self._timeout, allow_redirects=False
            )
        except requests.RequestException as exc:
            raise MexcError(_net_text(exc)) from exc
        if response.status_code in (301, 302, 303, 307, 308):
            raise MexcError(f"{path} redirect is refused")
        if response.status_code in (403, 418, 429):
            _raise_limited(path, response.status_code, response.headers.get("Retry-After", ""))
        if response.status_code != 200:
            raise MexcError(f"{path} HTTP {response.status_code}")
        body = _json_body(response, path)
        if isinstance(body, dict):
            _reject_exchange_code(body)
        return body

    def _signed(self, method: str, path: str, params: dict[str, str], as_list: bool = False) -> Any:
        if method not in ("GET", "POST"):
            raise MexcError("request method is refused")
        if not self._key or not self._secret:
            raise MexcError("signed call without API key")
        path = _api_path(path)
        query = _query(params)
        query["timestamp"] = str(time.time_ns() // 1_000_000)
        query["recvWindow"] = "5000"
        encoded = urlencode(query)
        signature = hmac.new(self._secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        url = f"{BASE}{path}?{encoded}&signature={signature}"
        headers = {"X-MEXC-APIKEY": self._key}
        try:
            response = self._session().request(
                method, url, headers=headers, timeout=self._timeout, allow_redirects=False
            )
        except requests.RequestException as exc:
            raise MexcError(_net_text(exc)) from exc
        if response.status_code in (301, 302, 303, 307, 308):
            raise MexcError("order redirect is refused")
        if response.status_code in (403, 418, 429):
            _raise_limited("order", response.status_code, response.headers.get("Retry-After", ""))
        if response.status_code != 200:
            raw = getattr(response, "content", b"")
            if not isinstance(raw, (bytes, bytearray)):
                raw = b""
            shown = raw[:180].decode("utf-8", errors="replace")
            raise MexcError(f"order HTTP {response.status_code}: {shown}")
        return signed_payload(_json_body(response, "order"), as_list)


def _order_request(symbol: str, client_order_id: str, size: int) -> None:
    """Refuse a send that has no pair, no client id, or no positive size."""
    from spotbot.state import client_id_ok, usdt_symbol_ok

    if not usdt_symbol_ok(symbol) or not client_id_ok(client_order_id) or isinstance(size, bool) or not isinstance(size, int) or size <= 0 or size >= 10**24:
        raise MexcError("order is missing a pair, a client id, or a positive size")


def signed_payload(body: object, as_list: bool) -> Any:
    """An order ack is an object. The trade list is a list. An error object is neither."""
    if isinstance(body, dict):
        if len(body) > 128:
            raise MexcError("order response is too wide")
        fills = body.get("fills")
        if isinstance(fills, list) and len(fills) > 128:
            raise MexcError("order fills are too many")
        _reject_exchange_code(body)
        if as_list:
            raise MexcError("order response is not a list")
        return body
    if as_list and isinstance(body, list):
        if len(body) > 5_000:
            raise MexcError("order response is too large")
        for row in body:
            if not isinstance(row, dict):
                raise MexcError("trade row is not an object")
            if len(row) > 32:
                raise MexcError("trade row is too wide")
        return body
    raise MexcError("order response is not an object")


def _interval_ms(interval: str) -> int:
    spans = {
        "1m": 60_000,
        "5m": 300_000,
        "15m": 900_000,
        "30m": 1_800_000,
        "1h": 3_600_000,
        "4h": 14_400_000,
        "1d": 86_400_000,
    }
    if not isinstance(interval, str) or len(interval) > 8:
        raise MexcError("kline interval is not used")
    span = spans.get(interval)
    if span is None:
        raise MexcError("kline interval is not used")
    return span


def rank_liquid(
    payload: object,
    min_quote_micro: int,
    change_min_bps: int,
    change_max_bps: int,
    cap: int,
) -> list[str]:
    """USDT names with a real volume and a real percent. A missing percent is not zero."""
    from spotbot.state import usdt_symbol_ok

    if not isinstance(payload, list):
        raise MexcError("24h ticker is not a list")
    if len(payload) > 20_000:
        raise MexcError("24h ticker is too large")
    bounds = (min_quote_micro, change_min_bps, change_max_bps, cap)
    if any(isinstance(item, bool) or not isinstance(item, int) for item in bounds) or cap < 1 or cap > 32:
        return []
    if min_quote_micro >= 10**24 or change_min_bps <= -10**9 or change_max_bps >= 10**9:
        return []
    best: dict[str, int] = {}
    for item in payload:
        if not isinstance(item, dict) or len(item) > 64:
            continue
        symbol = item.get("symbol")
        if not isinstance(symbol, str) or not usdt_symbol_ok(symbol):
            continue
        raw_quote = item.get("quoteVolume")
        raw_change = item.get("priceChangePercent")
        if raw_quote in (None, "") or raw_change in (None, ""):
            continue
        try:
            quote = parse_micro(decimal_text(raw_quote))
            change_bps = DecimalChange(decimal_text(raw_change))
        except (MoneyError, ValueError):
            continue
        if quote < min_quote_micro:
            continue
        if change_bps < change_min_bps or change_bps > change_max_bps:
            continue
        if symbol not in best or quote > best[symbol]:
            best[symbol] = quote
    ranked = sorted(best.items(), key=lambda row: (-row[1], row[0]))
    return [symbol for symbol, _quote in ranked[:cap]]


def ticker_price(payload: object, symbol: str) -> int:
    """Last price only when the row names the requested pair."""
    symbol = _pair_name(symbol)
    if isinstance(payload, dict) and len(payload) > 16:
        raise MexcError(f"no price for {symbol}")
    if not isinstance(payload, dict) or "price" not in payload:
        raise MexcError(f"no price for {symbol}")
    named = payload.get("symbol")
    if not isinstance(named, str) or named != symbol:
        raise MexcError(f"price is not {symbol}")
    try:
        return parse_price(decimal_text(payload["price"]))
    except MoneyError as exc:
        raise MexcError(f"bad price for {symbol}") from exc


def _near_book(levels: list[tuple[int, int]], best: int) -> int:
    """Notional within 30 bps of the touch. A further order is not the next trade."""
    from spotbot.oracle import MAX_WIDTH_BPS

    total = 0
    for price, notional in levels:
        if price <= 0 or best <= 0:
            continue
        if abs(price - best) * 10_000 // best > MAX_WIDTH_BPS:
            continue
        total += notional
        if total >= 10**24:
            break
    return total


def depth_notionals(payload: object, symbol: str) -> tuple[int, int]:
    """Bid and ask notional near the touch. An empty side or a crossed top is not a book."""
    symbol = _pair_name(symbol)
    if not isinstance(payload, dict) or len(payload) > 16:
        raise MexcError(f"no depth for {symbol}" if not isinstance(payload, dict) else f"depth for {symbol} is too wide")
    named = payload.get("symbol")
    if named not in (None, "") and (not isinstance(named, str) or named != symbol):
        raise MexcError(f"depth is not {symbol}")
    bids = _depth_side(payload.get("bids"))
    asks = _depth_side(payload.get("asks"))
    if not bids or not asks:
        raise MexcError(f"empty depth for {symbol}")
    if min(price for price, _notional in asks) < max(price for price, _notional in bids):
        raise MexcError(f"crossed depth for {symbol}")
    positive_int(payload.get("lastUpdateId"), f"depth update for {symbol}")
    bid_sum = _near_book(bids, max(price for price, _notional in bids))
    ask_sum = _near_book(asks, min(price for price, _notional in asks))
    if bid_sum >= 10**24 or ask_sum >= 10**24:
        raise MexcError(f"depth notional for {symbol} is too large")
    return bid_sum, ask_sum


def _reject_exchange_code(body: dict[str, Any]) -> None:
    """MEXC sometimes returns HTTP 200 with an error code instead of an order."""
    if "code" not in body:
        return
    code = body.get("code")
    if code in (0, 200) and isinstance(code, int) and not isinstance(code, bool):
        return
    if code in ("0", "200"):
        return
    raw_msg = body.get("msg")
    if not isinstance(raw_msg, str):
        raw_msg = body.get("message")
    if not isinstance(raw_msg, str):
        raw_msg = ""
    if isinstance(code, bool) or not isinstance(code, (int, str)):
        shown = "refused"
    elif isinstance(code, str):
        shown = code[:32]
    elif code <= -1_000_000_000 or code >= 1_000_000_000:
        shown = "refused"
    else:
        shown = str(code)
    text = f"exchange code {shown}: {raw_msg[:180]}"
    if code in (429, 418, 403, "429", "418", "403"):
        raise MexcRateLimit(text)
    raise MexcError(text)


def _raise_limited(label: str, status: int, retry_after: str) -> None:
    seconds = _retry_after_sec(retry_after)
    shown = str(seconds) if seconds is not None else "unknown"
    raise MexcRateLimit(f"{label} HTTP {status} retry-after={shown}", seconds)


_MAX_BODY = 8_000_000


class _DropCookies(requests.cookies.RequestsCookieJar):
    """Do not store or send cookies. A Set-Cookie must not ride with the API key."""

    def extract_cookies(self, response, request):  # noqa: ANN001
        return None

    def set_cookie(self, cookie, *args, **kwargs):  # noqa: ANN001
        return None


def _json_body(response: requests.Response, label: str) -> Any:
    payload = getattr(response, "content", b"")
    if isinstance(payload, (bytes, bytearray)) and len(payload) > _MAX_BODY:
        raise MexcError(f"{label} response is too large")
    try:
        return response.json()
    except ValueError as exc:
        raise MexcError(f"{label} is not json") from exc


def DecimalChange(text: str) -> int:
    """24h percent string to basis points, truncating toward zero."""
    from decimal import Decimal, ROUND_DOWN

    if not isinstance(text, str) or len(text) > 80:
        raise ValueError("change is not decimal")
    raw = text.strip()
    if not raw:
        raise ValueError("empty change")
    bps = (Decimal(raw) * 100).to_integral_value(rounding=ROUND_DOWN)
    value = int(bps)
    if value <= -10**9 or value >= 10**9:
        raise ValueError("change is too large")
    return value


def _depth_side(levels: object) -> list[tuple[int, int]]:
    """Positive levels as price and notional. A zero size is not a level."""
    if not isinstance(levels, list):
        raise MexcError("depth side is not a list")
    if len(levels) > 5_000:
        raise MexcError("depth side is too large")
    rows: list[tuple[int, int]] = []
    for level in levels:
        if not isinstance(level, list) or len(level) < 2:
            raise MexcError("depth level is incomplete")
        if len(level) > 8:
            raise MexcError("depth level is too wide")
        try:
            price = parse_price(decimal_text(level[0]))
            qty_micro = parse_micro_nonneg(decimal_text(level[1]))
        except MoneyError as exc:
            raise MexcError("depth level is not decimal") from exc
        if qty_micro <= 0:
            continue
        if any(price == seen for seen, _notional in rows):
            raise MexcError("depth price is repeated")
        atoms = qty_micro * (BASE_ATOMS // MICRO)
        if atoms >= 10**24:
            raise MexcError("depth level is too large")
        try:
            rows.append((price, notional_micro(atoms, price)))
        except MoneyError as exc:
            raise MexcError("depth level is too large") from exc
    return rows


def _base_atoms(qty: str) -> int:
    try:
        atoms = to_satoshi(qty) * (BASE_ATOMS // MICRO)
    except MoneyError as exc:
        raise MexcError("filled quantity is not decimal") from exc
    if atoms <= 0:
        raise MexcError("filled quantity rounds to zero")
    if atoms >= 10**24:
        raise MexcError("filled quantity is too large")
    return int(atoms)


def positive_int(raw: object, label: str) -> int:
    """A positive integer. A digit string is accepted. A bool or a fraction is not."""
    if not isinstance(label, str) or len(label) > 80:
        label = "value"
    if isinstance(raw, bool):
        raise MexcError(f"{label} is not an integer")
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, str) and raw.strip().isdigit() and len(raw.strip()) <= 24:
        value = int(raw.strip())
    else:
        raise MexcError(f"{label} is not an integer")
    if value <= 0:
        raise MexcError(f"{label} is not positive")
    if value >= 10**24:
        raise MexcError(f"{label} is too large")
    return value


def book_prices(payload: object, symbol: str) -> tuple[int, int]:
    """Best bid and ask. A zero or crossed book is refused."""
    symbol = _pair_name(symbol)
    if not isinstance(payload, dict) or len(payload) > 16:
        raise MexcError(f"no book ticker for {symbol}" if not isinstance(payload, dict) else f"book ticker for {symbol} is too wide")
    try:
        bid = _book_side(payload.get("bidPrice"))
        ask = _book_side(payload.get("askPrice"))
    except MoneyError as exc:
        raise MexcError(f"bad book ticker for {symbol}") from exc
    if bid <= 0 or ask <= 0:
        raise MexcError(f"empty book for {symbol}")
    if not _size_ok(payload.get("bidQty")) or not _size_ok(payload.get("askQty")):
        raise MexcError(f"empty book for {symbol}")
    if ask < bid:
        raise MexcError(f"crossed book for {symbol}")
    named = payload.get("symbol")
    if not isinstance(named, str) or named != symbol:
        raise MexcError(f"book ticker is not {symbol}")
    return bid, ask


def _size_ok(raw: object) -> bool:
    """True when the book shows a positive size. Zero is an empty level."""
    from decimal import Decimal, InvalidOperation

    if raw in (None, ""):
        return False
    try:
        text = decimal_text(raw)
    except MoneyError as exc:
        raise MexcError("book size is not decimal") from exc
    if decimal_zero(text):
        return False
    try:
        return Decimal(text) > 0
    except InvalidOperation as exc:
        raise MexcError("book size is not decimal") from exc


def _public_limit(limit: int, label: str) -> None:
    """A public request limit is a positive integer. A fraction is not sent."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise MexcError(f"{label} limit is not an integer")
    if limit > 5_000:
        raise MexcError(f"{label} limit is too large")


def _join_klines(earlier: object, recent: object, symbol: str) -> list:
    """Earlier page, then the latest page. A row that starts at the join is not repeated."""
    if not isinstance(recent, list) or not recent or not isinstance(recent[0], list):
        raise MexcError(f"no klines for {symbol}")
    boundary = recent[0][0]
    if isinstance(boundary, bool) or not isinstance(boundary, int) or boundary <= 0:
        raise MexcError(f"kline time for {symbol} is not a timestamp")
    if not isinstance(earlier, list) or not earlier:
        raise MexcError(f"kline history for {symbol} is short")
    kept: list = []
    for row in earlier:
        if not isinstance(row, list) or not row:
            raise MexcError(f"bad kline row for {symbol}")
        opened = row[0]
        if isinstance(opened, bool) or not isinstance(opened, int) or opened <= 0:
            raise MexcError(f"kline time for {symbol} is not a timestamp")
        if opened >= boundary:
            continue
        kept.append(row)
    if not kept:
        raise MexcError(f"kline history for {symbol} is short")
    return kept + list(recent)


def parse_klines(symbol: str, payload: object, span_ms: int | None = None) -> list[tuple[int, int, int, int, int]]:
    """Open, high, low, close, and quote volume. A broken candle is refused."""
    full = _parsed_klines(symbol, payload, span_ms, 2)
    return [(row[1], row[2], row[3], row[4], row[5]) for row in full]


def _timed_closes(symbol: str, payload: object, span_ms: int) -> list[tuple[int, int]]:
    """Open time and close. One candle is enough; the caller pages."""
    if not isinstance(payload, list) or not payload:
        return []
    full = _parsed_klines(symbol, payload, span_ms, 1)
    return [(row[0], row[4]) for row in full]


def _parsed_klines(
    symbol: str, payload: object, span_ms: int | None, min_rows: int
) -> list[tuple[int, int, int, int, int, int]]:
    """Open time, open, high, low, close, quote volume."""
    symbol = _pair_name(symbol)
    if span_ms is not None and (isinstance(span_ms, bool) or not isinstance(span_ms, int) or span_ms < 1):
        raise MexcError(f"kline interval for {symbol} is not the one requested")
    if not isinstance(payload, list) or len(payload) < min_rows:
        raise MexcError(f"no klines for {symbol}")
    if len(payload) > 1_000:
        raise MexcError(f"too many klines for {symbol}")
    rows: list[tuple[int, int, int, int, int, int]] = []
    skipped_volume = False
    previous_open = 0
    previous_close = 0
    previous_span = 0
    for row in payload:
        if not isinstance(row, list) or len(row) < 8:
            raise MexcError(f"bad kline row for {symbol}")
        if len(row) > 16:
            raise MexcError(f"bad kline row for {symbol}")
        opened = positive_int(row[0], f"bad kline time for {symbol}")
        closed_at = positive_int(row[6], f"bad kline time for {symbol}")
        if opened >= 10**15 or closed_at >= 10**15:
            raise MexcError(f"kline time for {symbol} is not a timestamp")
        if opened <= previous_open or closed_at <= opened or (previous_close > 0 and opened < previous_close):
            raise MexcError(f"kline time for {symbol} is out of order")
        span = closed_at - opened
        if span_ms is not None and span != span_ms and span + 1 != span_ms:
            raise MexcError(f"kline interval for {symbol} is not the one requested")
        if previous_span and span != previous_span:
            raise MexcError(f"kline interval for {symbol} is not the one requested")
        previous_open = opened
        previous_close = closed_at
        previous_span = span
        try:
            open_px = parse_price(decimal_text(row[1]))
            high = parse_price(decimal_text(row[2]))
            low = parse_price(decimal_text(row[3]))
            close = parse_price(decimal_text(row[4]))
            base_vol = parse_micro_nonneg(decimal_text(row[5]))
            quote = parse_micro_nonneg(decimal_text(row[7]))
        except MoneyError as exc:
            raise MexcError(f"bad kline number for {symbol}") from exc
        if quote <= 0 or base_vol <= 0:
            skipped_volume = True
            continue
        if min(open_px, high, low, close) <= 0 or low > high or open_px < low or open_px > high or close < low or close > high:
            raise MexcError(f"kline range for {symbol} is impossible")
        rows.append((opened, open_px, high, low, close, quote))
    if len(rows) < min_rows:
        if skipped_volume:
            raise MexcError(f"kline volume for {symbol} is zero")
        raise MexcError(f"no klines for {symbol}")
    return rows


def _decimal_zero(text: str) -> bool:
    """True when the text is a decimal zero. A non-decimal is left for the parser."""
    from decimal import Decimal, InvalidOperation

    try:
        return Decimal(text) == 0
    except InvalidOperation:
        return False


def _book_side(raw: object) -> int:
    if raw in (None, ""):
        return 0
    text = decimal_text(raw)
    if _decimal_zero(text):
        return 0
    return parse_price(text)


_ID_LOCK = threading.Lock()
_ID_SEQ = 0


def new_client_order_id(symbol: str, side: str) -> str:
    """A 32-character id. A counter keeps two calls in the same nanosecond apart."""
    from spotbot.state import usdt_symbol_ok

    if not usdt_symbol_ok(symbol) or side not in ("B", "S"):
        raise MexcError("client id needs a USDT pair and a side")
    global _ID_SEQ
    with _ID_LOCK:
        _ID_SEQ += 1
        seq = _ID_SEQ
    digest = hashlib.sha256(f"{side}:{symbol}:{time.time_ns()}:{seq}".encode()).hexdigest()
    return digest[:32]


def _filled_quote_raw(body: dict[str, Any]) -> object:
    """Quote that traded. A present zero does not fall through to the other spelling."""
    if "cummulativeQuoteQty" in body and body.get("cummulativeQuoteQty") not in (None, ""):
        return body.get("cummulativeQuoteQty")
    return body.get("cumulativeQuoteQty")


def _pair_name(symbol: object) -> str:
    """A short USDT pair. A long name is refused before it can be copied into an error."""
    from spotbot.state import usdt_symbol_ok

    if not isinstance(symbol, str) or not usdt_symbol_ok(symbol):
        raise MexcError("symbol is not a USDT pair")
    return symbol


def _text_symbol(symbol: object) -> str:
    """A pair name is an uppercase USDT symbol. Anything else is not requested."""
    from spotbot.state import usdt_symbol_ok

    if not isinstance(symbol, str) or not symbol:
        raise MexcError("symbol is not text")
    if not usdt_symbol_ok(symbol):
        raise MexcError("symbol is not a USDT pair")
    return symbol


def executed_fill(body: dict[str, Any]) -> tuple[int, int, int] | None:
    """Base, quote, and price of what actually traded.

    None only when the executed quantity is empty or zero. A positive quantity
    that is not a decimal, or a zero quote beside it, is an error: that is not
    an empty fill.
    """
    if not isinstance(body, dict):
        raise MexcError("executed order is not an object")
    executed = body.get("executedQty")
    if executed in (None, ""):
        return None
    try:
        text = decimal_text(executed)
    except MoneyError as exc:
        raise MexcError("filled quantity is not decimal") from exc
    if text == "" or _decimal_zero(text):
        return None
    raw = _filled_quote_raw(body)
    base = _base_atoms(text)
    if raw in (None, ""):
        raise MexcError("executed order is missing quote qty")
    try:
        quote = parse_micro(decimal_text(raw))
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


def _filled_base_text(body: dict[str, Any], label: str) -> str:
    """Executed base as decimal text. A JSON float is not a fill."""
    raw = body.get("executedQty")
    if raw in (None, ""):
        raise MexcError(f"{label} returned no executedQty")
    try:
        text = decimal_text(raw)
    except MoneyError as exc:
        raise MexcError(f"{label} executedQty is not decimal") from exc
    if _decimal_zero(text):
        raise MexcError(f"{label} returned no executedQty")
    return text


def _accepted_order_id(body: dict[str, Any], symbol: str, side: str, client_order_id: str) -> str:
    """The id on an ack that is our order. A foreign ack is not stored."""
    if not order_is_ours(body, symbol, side, client_order_id):
        raise MexcError(f"{side.lower()} ack is not {symbol} {client_order_id}")
    try:
        return _order_id_text(body.get("orderId"))
    except MexcError as exc:
        raise MexcOrderAccepted(_net_text(exc), "") from exc


def _order_id_text(raw: object) -> str:
    """Digit order id. A JSON float is not an id. An empty ack id stays empty."""
    if raw in (None, ""):
        return ""
    if isinstance(raw, bool) or isinstance(raw, float):
        raise MexcError("order id is not digits")
    if isinstance(raw, int):
        if raw <= 0 or raw >= 10**32:
            raise MexcError("order id is not digits")
        text = str(raw)
    elif isinstance(raw, str):
        text = raw.strip()
        if len(text) > 32:
            raise MexcError("order id is not digits")
    else:
        text = ""
    if not text.isdigit() or not 1 <= len(text) <= 32:
        raise MexcError("order id is not digits")
    return text


def _require_filled(body: dict[str, Any], label: str) -> None:
    from spotbot.reconcile import order_filled

    if not isinstance(body, dict):
        raise MexcError(f"{label} status is not filled")
    if order_filled(body):
        return
    status = body.get("status") if isinstance(body, dict) else None
    if status in (None, ""):
        raise MexcError(f"{label} status missing")
    raise MexcError(f"{label} status is not filled")


def _filled_quote(body: dict[str, Any], label: str) -> int:
    """Quote that actually traded. The requested amount is not a fill."""
    raw = _filled_quote_raw(body)
    if raw in (None, ""):
        raise MexcError(f"{label} has no quote qty")
    try:
        quote = parse_micro(decimal_text(raw))
    except MoneyError as exc:
        raise MexcError(f"{label} quote is not decimal") from exc
    if quote <= 0:
        raise MexcError(f"{label} quote is zero")
    return quote


def _base_asset(symbol: str) -> str:
    from spotbot.state import usdt_symbol_ok

    if not usdt_symbol_ok(symbol):
        raise MexcError("symbol is not a USDT pair")
    return symbol[:-4]


def ack_commission(body: dict[str, Any], base_asset: str) -> tuple[int, int]:
    """USDT fee and base fee named on the ack. Both zero means the ack omitted the fee.

    A named fee in any other asset, or a positive fee that rounds to zero, is refused.
    """
    if not isinstance(body, dict):
        raise MexcError("ack is not an object")
    commission = body.get("commission")
    if commission in (None, ""):
        return 0, 0
    try:
        raw = decimal_text(commission)
    except MoneyError as exc:
        raise MexcError("ack commission is not decimal") from exc
    if raw in ("", "0", "0.0", "0.00") or decimal_zero(raw):
        return 0, 0
    asset_raw = body.get("commissionAsset")
    if not isinstance(asset_raw, str) or not asset_raw.strip():
        raise MexcError("ack commission asset is not text")
    asset = asset_raw.strip().upper()
    if len(asset) > 32 or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" for ch in asset):
        raise MexcError("ack commission asset is not text")
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
            if atoms >= 10**24:
                raise MexcError("base commission is too large")
            return 0, atoms
    except MoneyError as exc:
        raise MexcError("ack commission is not decimal") from exc
    raise MexcError(f"ack commission is in {asset or 'missing'}")


def _sell_credit(body: dict[str, Any], base_asset: str) -> tuple[int, int, int]:
    _require_filled(body, "sell")
    raw = _filled_quote_raw(body)
    if raw in (None, ""):
        raise MexcError("sell ack has no quote qty")
    credit = _filled_quote(body, "sell")
    fee, base_fee = ack_commission(body, base_asset)
    if fee > credit:
        raise MexcError("commission above the sell fill")
    return credit - fee, fee, base_fee


def parse_account(payload: dict[str, Any]) -> tuple[int, int, dict[str, int], dict[str, int]]:
    """Total USDT, free USDT, total base atoms, and free base atoms."""
    if not isinstance(payload, dict) or len(payload) > 32:
        raise MexcError("account balances missing" if not isinstance(payload, dict) else "account response is too wide")
    rows = payload.get("balances")
    if not isinstance(rows, list) or len(rows) > 5_000:
        raise MexcError("account balances missing" if not isinstance(rows, list) else "account has too many balances")
    total_usdt = 0
    free_usdt = 0
    bases: dict[str, int] = {}
    free_bases: dict[str, int] = {}
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or len(row) > 16:
            raise MexcError("balance row is not an object" if not isinstance(row, dict) else "balance row is too wide")
        raw_asset = row.get("asset")
        if raw_asset in (None, ""):
            asset = ""
        elif not isinstance(raw_asset, str):
            raise MexcError("balance asset is not text")
        else:
            asset = raw_asset.strip().upper()
            if len(asset) > 32 or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" for ch in asset):
                raise MexcError("balance asset is not text")
        free = _qty_micro(row.get("free"))
        locked = _qty_micro(row.get("locked"))
        if free < 0 or locked < 0:
            raise MexcError("balance is negative")
        if free >= 10**24 or locked >= 10**24 or free + locked >= 10**24:
            raise MexcError("account balance is too large")
        if not asset:
            if free or locked:
                raise MexcError("balance row has no asset")
            continue
        if asset in seen:
            raise MexcError("balance asset is repeated")
        seen.add(asset)
        if asset == "USDT":
            free_usdt += free
            total_usdt += free + locked
            if free_usdt >= 10**24 or total_usdt >= 10**24:
                raise MexcError("account balance is too large")
            continue
        free_atoms = free * (BASE_ATOMS // MICRO)
        total_atoms = (free + locked) * (BASE_ATOMS // MICRO)
        if free_atoms >= 10**24 or total_atoms >= 10**24:
            raise MexcError("account balance is too large")
        if total_atoms > 0:
            bases[asset] = bases.get(asset, 0) + total_atoms
        if free_atoms > 0:
            free_bases[asset] = free_bases.get(asset, 0) + free_atoms
    return total_usdt, free_usdt, bases, free_bases


def _qty_micro(raw: object) -> int:
    if raw in (None, ""):
        return 0
    try:
        return to_satoshi(decimal_text(raw))
    except MoneyError as exc:
        raise MexcError("balance is not decimal") from exc
