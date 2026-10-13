"""Refuse a print that cannot be a 5-minute spot close.

A single bad candle (100x the last close) otherwise becomes an entry or an
exit and the paper result is fiction.
"""

from __future__ import annotations

MAX_JUMP_BPS = 1_500


def jump_bps(prev: int, cur: int) -> int:
    if prev <= 0 or cur <= 0:
        raise ValueError("prices must be positive")
    return abs(cur - prev) * 10_000 // prev


def price_ok(prev: int, cur: int, limit_bps: int = MAX_JUMP_BPS) -> bool:
    return jump_bps(prev, cur) <= limit_bps
