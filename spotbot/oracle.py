"""Live public prices from other spot venues, stored as satoshi.

Orders stay on MEXC. Binance, Bybit, and OKX are read at the decision and are
not traded. A missing venue is omitted. A buy needs at least one other price.
"""

from __future__ import annotations

import logging
import threading

import requests

from spotbot.money import MoneyError, decimal_text, parse_price

LOG = logging.getLogger("spotbot.oracle")
_LOCAL = threading.local()
_MAX_BODY = 8_000_000


class _DropCookies(requests.cookies.RequestsCookieJar):
    """Do not keep cookies from a public price host."""

    def extract_cookies(self, response, request):  # noqa: ANN001
        return None

    def set_cookie(self, cookie, *args, **kwargs):  # noqa: ANN001
        return None

# Do not buy when MEXC is this far richer than the other books.
BUY_MAX_AHEAD_BPS = 15
# Sell a winner early when MEXC has run this far ahead of the other books.
SELL_AHEAD_BPS = 15
SELL_AHEAD_MIN_PROFIT_BPS = 30
MAX_WIDTH_BPS = 30


class OracleError(RuntimeError):
    """A venue returned nothing usable."""


def _price_ok(price: int) -> bool:
    """A bool is not a price of one. It is left out of the width and the lag."""
    return not isinstance(price, bool) and isinstance(price, int) and price > 0


def _lower_middle(ordered: list[int]) -> int:
    """Odd count: the middle. Even count: the lower of the two middle values."""
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return ordered[mid - 1]


def deviation_bps(prices: list[int]) -> int | None:
    """Width of the price set in basis points of the median. None if fewer than two.

    An even count uses the lower middle price, so the width is not understated.
    """
    vals = [price for price in prices if _price_ok(price)]
    if len(vals) < 2:
        return None
    ordered = sorted(vals)
    mid = _lower_middle(ordered)
    if mid <= 0:
        return None
    return (ordered[-1] - ordered[0]) * 10_000 // mid


def lag_bps(mexc_micro: int, peers: list[int]) -> int | None:
    """Signed bps of the live MEXC price against the median of the other venues.

    Positive means MEXC is richer. None when there is no other price.
    """
    vals = [price for price in peers if _price_ok(price)]
    if not _price_ok(mexc_micro) or not vals:
        return None
    ordered = sorted(vals)
    mid = _lower_middle(ordered)
    if mid <= 0:
        return None
    return (mexc_micro - mid) * 10_000 // mid


def cheapest_first(rows: list[tuple[str, int]]) -> list[str]:
    """Order symbols by lag. A lower lag means MEXC is cheaper. Ties follow the name."""
    clean = [
        (symbol, lag)
        for symbol, lag in rows
        if isinstance(symbol, str) and not isinstance(lag, bool) and isinstance(lag, int)
    ]
    return [symbol for symbol, _lag in sorted(clean, key=lambda row: (row[1], row[0]))]


def entry_allowed(mexc_micro: int, peers: list[int]) -> bool:
    """Buy on MEXC only when another book exists and MEXC is not ahead of it."""
    lag = lag_bps(mexc_micro, peers)
    width = deviation_bps([mexc_micro, *peers])
    if lag is None or width is None:
        return False
    return width <= MAX_WIDTH_BPS and lag <= BUY_MAX_AHEAD_BPS


def ahead_exit(mexc_micro: int, peers: list[int], profit_bps: int) -> bool:
    """True when a profitable MEXC position is richer than the other books."""
    if isinstance(profit_bps, bool) or not isinstance(profit_bps, int):
        return False
    lag = lag_bps(mexc_micro, peers)
    if lag is None:
        return False
    return profit_bps >= SELL_AHEAD_MIN_PROFIT_BPS and lag >= SELL_AHEAD_BPS


def peer_prices(symbol: str, timeout_sec: int = 5) -> list[int]:
    """Other venues' last prices. Failures are omitted, not filled with zero."""
    return list(venue_quotes(symbol, timeout_sec).values())


def venue_quotes(symbol: str, timeout_sec: int = 5) -> dict[str, int]:
    """Binance, Bybit, and OKX spot last prices, keyed by venue."""
    session = getattr(_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        session.trust_env = False
        session.cookies = _DropCookies()
        _LOCAL.session = session
    okx = _okx_inst(symbol)
    found: dict[str, int] = {}
    calls: tuple[tuple[str, str, dict[str, str], object], ...] = (
        (
            "binance",
            "https://api.binance.com/api/v3/ticker/price",
            {"symbol": symbol},
            lambda body: _binance_price(body, symbol),
        ),
        (
            "bybit",
            "https://api.bybit.com/v5/market/tickers",
            {"category": "spot", "symbol": symbol},
            lambda body: _bybit_price(body, symbol),
        ),
    )
    if okx is not None:
        calls = (
            *calls,
            (
                "okx",
                "https://www.okx.com/api/v5/market/ticker",
                {"instId": okx},
                lambda body: _okx_price(body, okx),
            ),
        )
    for label, url, params, pick in calls:
        try:
            response = session.get(url, params=params, timeout=timeout_sec, allow_redirects=False)
        except requests.RequestException as exc:
            LOG.warning("oracle %s %s: %s", label, symbol, exc)
            continue
        if response.status_code != 200:
            LOG.warning("oracle %s %s HTTP %s", label, symbol, response.status_code)
            continue
        payload = getattr(response, "content", b"")
        if isinstance(payload, (bytes, bytearray)) and len(payload) > _MAX_BODY:
            LOG.warning("oracle %s %s response is too large", label, symbol)
            continue
        try:
            raw = pick(response.json())
            if raw is None:
                continue
            found[label] = parse_price(raw if isinstance(raw, str) else decimal_text(raw))
        except (MoneyError, ValueError, TypeError) as exc:
            LOG.warning("oracle %s %s parse: %s", label, symbol, exc)
    return found


def _okx_inst(symbol: str) -> str | None:
    if not symbol.endswith("USDT") or len(symbol) <= 4:
        return None
    return f"{symbol[:-4]}-USDT"


def _binance_price(body: object, symbol: str) -> str | None:
    if not isinstance(body, dict) or str(body.get("symbol") or "") != symbol:
        return None
    return _price_text(body.get("price"))


def _bybit_price(body: object, symbol: str) -> str | None:
    if not isinstance(body, dict):
        return None
    result = body.get("result")
    if not isinstance(result, dict):
        return None
    rows = result.get("list")
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return None
    if str(rows[0].get("symbol") or "") != symbol:
        return None
    return _price_text(rows[0].get("lastPrice"))


def _okx_price(body: object, inst_id: str) -> str | None:
    if not isinstance(body, dict):
        return None
    rows = body.get("data")
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return None
    if str(rows[0].get("instId") or "") != inst_id:
        return None
    return _price_text(rows[0].get("last"))


def _price_text(raw: object) -> str | None:
    """A peer price is decimal text. A JSON float is omitted, not parsed."""
    if raw in (None, ""):
        return None
    try:
        return decimal_text(raw)
    except MoneyError:
        return None
