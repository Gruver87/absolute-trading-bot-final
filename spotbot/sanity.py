"""Refuse a print that cannot be a 5-minute spot close.

A single bad candle (100x the last close) otherwise becomes an entry or an
exit and the paper result is fiction.
"""

from __future__ import annotations

MAX_JUMP_BPS = 1_500
# Five times the stored peak. A gap through the stop still exits. A 100x print does not.
EXIT_JUMP_BPS = 40_000


def jump_bps(prev: int, cur: int) -> int:
    if isinstance(prev, bool) or isinstance(cur, bool) or not isinstance(prev, int) or not isinstance(cur, int) or prev <= 0 or cur <= 0 or prev >= 10**24 or cur >= 10**24:
        raise ValueError("prices must be positive")
    return abs(cur - prev) * 10_000 // prev


def price_ok(prev: int, cur: int, limit_bps: int = MAX_JUMP_BPS) -> bool:
    if isinstance(limit_bps, bool) or not isinstance(limit_bps, int):
        return False
    if isinstance(prev, int) and not isinstance(prev, bool) and (prev >= 10**24 or (isinstance(cur, int) and not isinstance(cur, bool) and cur >= 10**24)):
        return False
    return jump_bps(prev, cur) <= limit_bps


def price_grid_ok(price: int, stop_bps: int) -> bool:
    """Our smallest price unit must be finer than the stop."""
    return tick_fits(price, 1, stop_bps)


def tick_fits(price: int, tick: int, stop_bps: int) -> bool:
    """The exchange price step must be a smaller move than the stop."""
    if (
        isinstance(price, bool)
        or isinstance(tick, bool)
        or isinstance(stop_bps, bool)
        or not isinstance(price, int)
        or not isinstance(tick, int)
        or not isinstance(stop_bps, int)
    ):
        return False
    if price <= 0 or tick <= 0 or stop_bps <= 0 or price >= 10**24 or tick >= 10**24:
        return False
    return tick * 10_000 // price < stop_bps


def slip_price(price: int, bps: int, buy: bool) -> int:
    """Move a fill against the trade by bps. Zero means the fill cannot be priced."""
    if isinstance(price, bool) or isinstance(bps, bool) or not isinstance(price, int) or not isinstance(bps, int) or not isinstance(buy, bool) or price <= 0 or price >= 10**24 or bps < 0 or bps > 10_000:
        return 0
    if buy:
        moved = price * (10_000 + bps) // 10_000
    else:
        moved = price * (10_000 - bps) // 10_000
    if moved <= 0 or moved >= 10**24:
        return 0
    return moved


def follows_close(close: int, ask: int) -> bool:
    """The live ask must stay inside the same jump limit as two closes."""
    try:
        return price_ok(close, ask)
    except ValueError:
        return False


def mark_ok(peak: int, price: int) -> bool:
    """An exit mark may gap through a stop. It may not be non-positive or many times the peak."""
    if isinstance(peak, bool) or isinstance(price, bool) or not isinstance(peak, int) or not isinstance(price, int) or peak <= 0 or price <= 0 or peak >= 10**24 or price >= 10**24:
        return False
    return price_ok(peak, price, EXIT_JUMP_BPS)
