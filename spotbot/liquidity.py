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


def _fit(value: object) -> bool:
    """A positive int under the money ceiling. A float is not a volume."""
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value < 10**24


def volume_ratio_bps(quote_volumes: list[int]) -> int | None:
    """Last closed bar versus the median of the 12 bars before it."""
    if not isinstance(quote_volumes, list) or len(quote_volumes) < 14 or any(not _fit(item) for item in quote_volumes):
        return None
    closed = quote_volumes[-2]
    prior = sorted(quote_volumes[-14:-2])
    median = prior[len(prior) // 2]
    if median <= 0 or closed <= 0:
        return None
    return closed * 10_000 // median


def close_position_bps(high: int, low: int, close: int) -> int | None:
    if not _fit(high) or not _fit(low) or not _fit(close):
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
    if not isinstance(symbol, str) or isinstance(min_volume_bps, bool) or isinstance(min_close_pos_bps, bool):
        return None
    if not isinstance(min_volume_bps, int) or not isinstance(min_close_pos_bps, int):
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
    if not _fit(bid_micro) or not _fit(ask_micro) or bid_micro <= ask_micro:
        return None
    return found


def ask_wall_exit(bid_micro: int, ask_micro: int, profit_bps: int, min_profit_bps: int = 30) -> bool:
    """True when sellers outweigh buyers and the position is already green."""
    if not _fit(bid_micro) or not _fit(ask_micro):
        return False
    if isinstance(profit_bps, bool) or not isinstance(profit_bps, int):
        return False
    if isinstance(min_profit_bps, bool) or not isinstance(min_profit_bps, int) or min_profit_bps < 0:
        return False
    return profit_bps >= min_profit_bps and ask_micro > bid_micro > 0
