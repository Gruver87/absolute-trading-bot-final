"""Refuse a print that cannot be a 5-minute spot close.

A single bad candle (100x the last close) otherwise becomes an entry or an
exit and the paper result is fiction.
"""

from __future__ import annotations

MAX_JUMP_BPS = 1_500
# Five times the stored peak. A gap through the stop still exits. A 100x print does not.
EXIT_JUMP_BPS = 40_000


def jump_bps(prev: int, cur: int) -> int:
    if prev <= 0 or cur <= 0:
        raise ValueError("prices must be positive")
    return abs(cur - prev) * 10_000 // prev


def price_ok(prev: int, cur: int, limit_bps: int = MAX_JUMP_BPS) -> bool:
    return jump_bps(prev, cur) <= limit_bps


def price_grid_ok(price: int, stop_bps: int) -> bool:
    """Our smallest price unit must be finer than the stop."""
    return tick_fits(price, 1, stop_bps)


def tick_fits(price: int, tick: int, stop_bps: int) -> bool:
    """The exchange price step must be a smaller move than the stop."""
    if price <= 0 or tick <= 0 or stop_bps <= 0:
        return False
    return tick * 10_000 // price < stop_bps


def slip_price(price: int, bps: int, buy: bool) -> int:
    """Move a fill against the trade by bps. Zero means the fill cannot be priced."""
    if price <= 0 or bps < 0:
        return 0
    if buy:
        return price * (10_000 + bps) // 10_000
    sold = price * (10_000 - bps) // 10_000
    return sold if sold > 0 else 0


def mark_ok(peak: int, price: int) -> bool:
    """An exit mark may gap through a stop. It may not be non-positive or many times the peak."""
    if peak <= 0 or price <= 0:
        return False
    return price_ok(peak, price, EXIT_JUMP_BPS)
