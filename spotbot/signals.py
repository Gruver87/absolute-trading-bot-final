"""RSI, MACD, and Bollinger.

Entry is a band reclaim after a prior oversold bar. A fresh MACD sell cross
blocks the buy. A MACD buy by itself does not enter.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def _whole(value: object) -> bool:
    """True for a real int. A bool or a fraction is not a price or a period."""
    return not isinstance(value, bool) and isinstance(value, int)


def rsi(prices: list[int], period: int = 14) -> int | None:
    """Return RSI rounded to an integer, or None when the window is short."""
    if not isinstance(prices, list) or not _whole(period) or period < 1 or period > 500:
        return None
    if len(prices) < period + 1:
        return None
    if any(not _whole(price) or price <= 0 or price >= 10**24 for price in prices):
        return None
    gains = 0
    losses = 0
    window = prices[-(period + 1) :]
    for prev, cur in zip(window, window[1:]):
        delta = cur - prev
        if delta > 0:
            gains += delta
        elif delta < 0:
            losses -= delta
    if losses == 0:
        return 100 if gains > 0 else 50
    rs_milli = gains * 1000 // losses
    return int((100_000 - (100_000_000 // (1000 + rs_milli))) // 1000)


def _ema_last(values: list[int], period: int) -> int | None:
    if not isinstance(values, list) or not _whole(period) or period < 1 or period > 500 or len(values) < period:
        return None
    if any(not _whole(price) or price <= 0 or price >= 10**24 for price in values):
        return None
    return _ema_acc(values, period)


def _ema_signed(values: list[int], period: int) -> int | None:
    """EMA of a MACD line. The line is a difference and is often below zero."""
    if not isinstance(values, list) or not _whole(period) or period < 1 or period > 500 or len(values) < period:
        return None
    if any(not _whole(price) or price <= -(10**24) or price >= 10**24 for price in values):
        return None
    return _ema_acc(values, period)


def _ema_acc(values: list[int], period: int) -> int:
    acc = sum(values[:period]) // period
    num = 2
    den = period + 1
    for price in values[period:]:
        acc = ((price - acc) * num + acc * den) // den
    return acc


def macd_cross(prices: list[int], fast: int = 12, slow: int = 26, signal: int = 9) -> str | None:
    """Return buy/sell on a fresh MACD cross, else None."""
    if not isinstance(prices, list) or not all(_whole(item) and 1 <= item <= 500 for item in (fast, slow, signal)):
        return None
    if fast >= slow:
        return None
    if len(prices) < slow + signal + 1:
        return None
    if not all(_whole(price) and 0 < price < 10**24 for price in prices):
        return None
    macd_line: list[int] = []
    for end in range(slow, len(prices) + 1):
        fast_v = _ema_last(prices[:end], fast)
        slow_v = _ema_last(prices[:end], slow)
        if fast_v is None or slow_v is None:
            return None
        macd_line.append(fast_v - slow_v)
    if len(macd_line) < signal + 1:
        return None
    prev_sig = _ema_signed(macd_line[:-1], signal)
    last_sig = _ema_signed(macd_line, signal)
    if prev_sig is None or last_sig is None:
        return None
    prev, last = macd_line[-2], macd_line[-1]
    if last > last_sig and prev <= prev_sig:
        return "buy"
    if last < last_sig and prev >= prev_sig:
        return "sell"
    return None


def band_reclaim(prices: list[int], period: int = 20) -> bool:
    """True when price turns up through the lower band.

    The prior close was at or under the band, and this close is both back
    above the band and above the prior close. A lower close is still the drop.
    """
    if not isinstance(prices, list) or len(prices) < period + 1:
        return False
    if any(not _whole(price) or price <= 0 or price >= 10**24 for price in prices[-2:]):
        return False
    if prices[-1] <= prices[-2]:
        return False
    return below_lower_band(prices[:-1], period) and not below_lower_band(prices, period)


def lower_band(prices: list[int], period: int = 20) -> int | None:
    """Lower Bollinger band of the last `period` prices. None when the window is unusable."""
    if not isinstance(prices, list) or not _whole(period) or period < 1 or period > 500:
        return None
    if len(prices) < period:
        return None
    if any(not _whole(price) or price <= 0 or price >= 10**24 for price in prices):
        return None
    window = prices[-period:]
    mean = sum(window) // period
    var = sum((p - mean) ** 2 for p in window) // period
    return mean - 2 * math.isqrt(var)


def below_lower_band(prices: list[int], period: int = 20) -> bool:
    """True when the last price is at or under the lower Bollinger band (2 std)."""
    band = lower_band(prices, period)
    if band is None or not prices:
        return False
    return prices[-1] <= band


def reclaim_still(closes: list[int], ask: int) -> bool:
    """The live ask is still the reclaim, not a fall back through the band."""
    if not isinstance(closes, list) or len(closes) < 21:
        return False
    if isinstance(ask, bool) or not isinstance(ask, int) or ask <= 0 or ask >= 10**24:
        return False
    prior = closes[-2]
    if isinstance(prior, bool) or not isinstance(prior, int) or prior <= 0:
        return False
    band = lower_band(closes)
    if band is None:
        return False
    return ask > band and ask > prior


@dataclass(frozen=True)
class Entry:
    symbol: str
    rsi: int
    reason: str


def closed_prices(prices: list[int]) -> list[int]:
    """Drop the forming bar. MEXC klines end with the candle that is still open."""
    if not isinstance(prices, list) or len(prices) < 2:
        return []
    if any(isinstance(price, bool) or not isinstance(price, int) or price <= 0 or price >= 10**24 for price in prices):
        return []
    return prices[:-1]


def entry_signal(symbol: str, prices: list[int], rsi_buy: int) -> Entry | None:
    """BUY when the prior bar was oversold under the band and this close reclaims it.

    A close that is still under the band is the breakdown, not the turn.
    A fresh MACD sell cross blocks the buy.
    """
    if not isinstance(symbol, str) or len(symbol) > 32 or not isinstance(prices, list):
        return None
    if isinstance(rsi_buy, bool) or not isinstance(rsi_buy, int) or rsi_buy < 1 or rsi_buy > 500:
        return None
    if any(isinstance(price, bool) or not isinstance(price, int) or price <= 0 or price >= 10**24 for price in prices):
        return None
    value = rsi(prices[:-1])
    if value is None or value >= rsi_buy:
        return None
    cross = macd_cross(prices)
    if cross == "sell":
        return None
    if not band_reclaim(prices):
        return None
    return Entry(symbol, value, "rsi+reclaim")
