"""RSI, MACD cross, and Bollinger from the earlier strategies module.

The old spot loop entered on RSI < 35 only. MACD and Bollinger were written
and never called. Entry here requires RSI plus one of those two confirmations.
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
    prev_sig = _ema_last(macd_line[:-1], signal)
    last_sig = _ema_last(macd_line, signal)
    if prev_sig is None or last_sig is None:
        return None
    prev, last = macd_line[-2], macd_line[-1]
    if last > last_sig and prev <= prev_sig:
        return "buy"
    if last < last_sig and prev >= prev_sig:
        return "sell"
    return None


def below_lower_band(prices: list[int], period: int = 20) -> bool:
    """True when the last price is at or under the lower Bollinger band (2 std)."""
    if not isinstance(prices, list) or not _whole(period) or period < 1 or period > 500:
        return False
    if len(prices) < period:
        return False
    if any(not _whole(price) or price <= 0 or price >= 10**24 for price in prices):
        return False
    window = prices[-period:]
    mean = sum(window) // period
    var = sum((p - mean) ** 2 for p in window) // period
    std = math.isqrt(var)
    return prices[-1] <= mean - 2 * std


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
    """BUY only on oversold RSI confirmed by Bollinger or a MACD buy cross."""
    if not isinstance(symbol, str) or len(symbol) > 32 or not isinstance(prices, list):
        return None
    if isinstance(rsi_buy, bool) or not isinstance(rsi_buy, int) or rsi_buy < 1 or rsi_buy > 500:
        return None
    if any(isinstance(price, bool) or not isinstance(price, int) or price <= 0 or price >= 10**24 for price in prices):
        return None
    value = rsi(prices)
    if value is None or value >= rsi_buy:
        return None
    cross = macd_cross(prices)
    if cross == "sell":
        return None
    if below_lower_band(prices):
        return Entry(symbol, value, "rsi+bollinger")
    if cross == "buy":
        return Entry(symbol, value, "rsi+macd")
    return None
