"""Liquidity-lift rules for spot. Public data only.

A rising 5-minute quote volume and a bid-heavy book are observable.
They are not proof that the price will continue. The sell is placed as a
target at entry; an ask-heavy book while the trade is green exits earlier.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Lift:
    symbol: str
    volume_ratio_bps: int
    close_pos_bps: int


def volume_ratio_bps(quote_volumes: list[int]) -> int | None:
    """Last closed bar versus the median of the 12 bars before it."""
    if len(quote_volumes) < 14 or any(isinstance(item, bool) for item in quote_volumes):
        return None
    closed = quote_volumes[-2]
    prior = sorted(quote_volumes[-14:-2])
    median = prior[len(prior) // 2]
    if median <= 0 or closed <= 0:
        return None
    return closed * 10_000 // median


def close_position_bps(high: int, low: int, close: int) -> int | None:
    if isinstance(high, bool) or isinstance(low, bool) or isinstance(close, bool):
        return None
    span = high - low
    if span <= 0 or close <= 0:
        return None
    return (close - low) * 10_000 // span


def candle_lift(
    symbol: str,
    quote_volumes: list[int],
    high: int,
    low: int,
    close: int,
    min_volume_bps: int = 20_000,
    min_close_pos_bps: int = 6_500,
) -> Lift | None:
    """Volume and close location only. The live buy also requires the book."""
    if isinstance(min_volume_bps, bool) or isinstance(min_close_pos_bps, bool):
        return None
    ratio = volume_ratio_bps(quote_volumes)
    pos = close_position_bps(high, low, close)
    if ratio is None or pos is None:
        return None
    if ratio < min_volume_bps or pos < min_close_pos_bps:
        return None
    return Lift(symbol, ratio, pos)


def lift_signal(
    symbol: str,
    quote_volumes: list[int],
    high: int,
    low: int,
    close: int,
    bid_micro: int,
    ask_micro: int,
    min_volume_bps: int = 20_000,
    min_close_pos_bps: int = 6_500,
) -> Lift | None:
    """BUY when the last closed bar expanded and buyers are still the larger side."""
    found = candle_lift(
        symbol,
        quote_volumes,
        high,
        low,
        close,
        min_volume_bps,
        min_close_pos_bps,
    )
    if found is None:
        return None
    if isinstance(bid_micro, bool) or isinstance(ask_micro, bool) or bid_micro <= 0 or bid_micro <= ask_micro:
        return None
    return found


def ask_wall_exit(bid_micro: int, ask_micro: int, profit_bps: int, min_profit_bps: int = 30) -> bool:
    """True when sellers outweigh buyers and the position is already green."""
    if isinstance(bid_micro, bool) or isinstance(ask_micro, bool) or isinstance(profit_bps, bool) or isinstance(min_profit_bps, bool):
        return False
    return profit_bps >= min_profit_bps and ask_micro > bid_micro > 0
