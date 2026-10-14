"""Stop, take-profit, and trailing gap. Same percents as the old spot loop.

3.5% stop, 7% take-profit, trail arms at +3% and sells after a 2% giveback.
"""

from __future__ import annotations


def pnl_bps(entry: int, price: int) -> int:
    if isinstance(entry, bool) or isinstance(price, bool) or not isinstance(entry, int) or not isinstance(price, int) or entry <= 0 or price <= 0 or entry >= 10**24 or price >= 10**24:
        raise ValueError("entry and price must be positive")
    return (price - entry) * 10_000 // entry


def exit_reason(
    entry: int,
    price: int,
    peak: int,
    stop_bps: int,
    take_bps: int,
    trail_arm_bps: int,
    trail_gap_bps: int,
) -> str | None:
    nums = (entry, price, peak, stop_bps, take_bps, trail_arm_bps, trail_gap_bps)
    if any(isinstance(item, bool) or not isinstance(item, int) for item in nums) or min(stop_bps, take_bps, trail_arm_bps, trail_gap_bps) <= 0 or peak < 0 or peak >= 10**24:
        raise ValueError("exit percents must be positive")
    profit = pnl_bps(entry, price)
    peak_profit = pnl_bps(entry, max(peak, price))
    if profit <= -stop_bps:
        return "stop"
    if peak_profit >= trail_arm_bps and peak_profit - profit >= trail_gap_bps:
        return "trail"
    if profit >= take_bps:
        return "take_profit"
    return None
