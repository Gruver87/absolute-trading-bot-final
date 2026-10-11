"""Public prices from more than one venue, stored as satoshi.

A buy needs two agreeing prices. One missing venue is a skip, not a guessed price.
"""

from __future__ import annotations

import logging
import threading

import requests

from spotbot.money import MoneyError, parse_micro

LOG = logging.getLogger("spotbot.oracle")
_LOCAL = threading.local()


class OracleError(RuntimeError):
    """A venue returned nothing usable."""


def deviation_bps(prices: list[int]) -> int | None:
    """Width of the price set in basis points of the median. None if fewer than two."""
    vals = [price for price in prices if price > 0]
    if len(vals) < 2:
        return None
    ordered = sorted(vals)
    mid = ordered[len(ordered) // 2]
    if mid <= 0:
        return None
    return (ordered[-1] - ordered[0]) * 10_000 // mid


def peer_prices(symbol: str, timeout_sec: int = 5) -> list[int]:
    """Binance and Bybit spot mids. Failures are omitted, not filled with zero."""
    session = getattr(_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        _LOCAL.session = session
    found: list[int] = []
    for label, url, params, pick in (
        (
            "binance",
            "https://api.binance.com/api/v3/ticker/price",
            {"symbol": symbol},
            lambda body: body.get("price") if isinstance(body, dict) else None,
        ),
        (
            "bybit",
            "https://api.bybit.com/v5/market/tickers",
            {"category": "spot", "symbol": symbol},
            _bybit_price,
        ),
    ):
        try:
            response = session.get(url, params=params, timeout=timeout_sec)
        except requests.RequestException as exc:
            LOG.warning("oracle %s %s: %s", label, symbol, exc)
            continue
        if response.status_code != 200:
            LOG.warning("oracle %s %s HTTP %s", label, symbol, response.status_code)
            continue
        try:
            raw = pick(response.json())
            if raw is None:
                continue
            found.append(parse_micro(str(raw)))
        except (MoneyError, ValueError, TypeError) as exc:
            LOG.warning("oracle %s %s parse: %s", label, symbol, exc)
    return found


def _bybit_price(body: object) -> str | None:
    if not isinstance(body, dict):
        return None
    result = body.get("result")
    if not isinstance(result, dict):
        return None
    rows = result.get("list")
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return None
    last = rows[0].get("lastPrice")
    return str(last) if last else None
