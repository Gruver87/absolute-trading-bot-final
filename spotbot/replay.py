"""Replay one symbol on closed candles. No lookahead, taker fee on both sides.

The result is the rule on this window, not a forecast.
"""

from __future__ import annotations

from dataclasses import dataclass

from spotbot.exits import exit_reason
from spotbot.fees import paper_buy, paper_sell
from spotbot.liquidity import candle_lift
from spotbot.sanity import price_ok
from spotbot.signals import entry_signal


@dataclass(frozen=True)
class Fill:
    entry_micro: int
    exit_micro: int
    pnl_micro: int


@dataclass(frozen=True)
class ReplayResult:
    trades: int
    wins: int
    net_micro: int
    fees_micro: int
    ended_open: bool
    fills: tuple[Fill, ...]


def holdout_cut(count: int) -> int:
    """Start index of the later slice. The earlier slice is everything before it.

    Parameters are not fitted on either slice. Both need enough bars for the
    indicator warmup, so a short tape is not split.
    """
    if count < 160:
        raise ValueError("need at least 160 bars to split")
    later = max(80, count * 2 // 5)
    return count - later


def replay_closes(
    closes: list[int],
    *,
    cash_micro: int,
    alloc_bps: int,
    taker_bps: int,
    rsi_buy: int,
    stop_bps: int,
    take_bps: int,
    trail_arm_bps: int,
    trail_gap_bps: int,
    min_notional_micro: int,
) -> ReplayResult:
    clean = [closes[0]]
    for price in closes[1:]:
        if price_ok(clean[-1], price):
            clean.append(price)
    closes = clean
    cash = cash_micro
    net = 0
    fees = 0
    trades = 0
    wins = 0
    fills: list[Fill] = []
    entry = 0
    peak = 0
    base = 0
    spent = 0
    start = 40
    i = start
    while i < len(closes):
        if entry == 0:
            window = closes[: i + 1]
            if entry_signal("REPLAY", window, rsi_buy) is None:
                i += 1
                continue
            price = closes[i]
            spend = cash * alloc_bps // 10_000
            if spend < min_notional_micro:
                break
            bought, fee = paper_buy(spend, price, taker_bps)
            if bought <= 0:
                break
            cash -= spend
            fees += fee
            entry = price
            peak = price
            base = bought
            spent = spend
            i += 1
            continue
        price = closes[i]
        if price > peak:
            peak = price
        reason = exit_reason(entry, price, peak, stop_bps, take_bps, trail_arm_bps, trail_gap_bps)
        if reason is None:
            i += 1
            continue
        credit, fee = paper_sell(base, price, taker_bps)
        fees += fee
        cash += credit
        pnl = credit - spent
        net += pnl
        trades += 1
        if pnl > 0:
            wins += 1
        fills.append(Fill(entry, price, pnl))
        entry = 0
        base = 0
        spent = 0
        i += 1
    return ReplayResult(trades, wins, net, fees, ended_open=entry != 0, fills=tuple(fills))


def replay_lift_bars(
    bars: list[tuple[int, int, int, int]],
    *,
    cash_micro: int,
    alloc_bps: int,
    taker_bps: int,
    stop_bps: int = 150,
    take_bps: int = 250,
    trail_arm_bps: int = 120,
    trail_gap_bps: int = 80,
    min_notional_micro: int,
) -> ReplayResult:
    """Candle half of the liquidity rule. Bid/ask and the oracle are not in the tape.

    Each bar is high, low, close, quote volume. A jump in close is dropped.
    """
    if not bars:
        return ReplayResult(0, 0, 0, 0, False, ())
    clean = [bars[0]]
    for bar in bars[1:]:
        if price_ok(clean[-1][2], bar[2]):
            clean.append(bar)
    bars = clean
    cash = cash_micro
    net = 0
    fees = 0
    trades = 0
    wins = 0
    fills: list[Fill] = []
    entry = 0
    peak = 0
    base = 0
    spent = 0
    i = 14
    while i < len(bars):
        if entry == 0:
            window = bars[: i + 1]
            volumes = [bar[3] for bar in window] + [1]
            high, low, close, _quote = window[-1]
            if candle_lift("REPLAY", volumes, high, low, close) is None:
                i += 1
                continue
            spend = cash * alloc_bps // 10_000
            if spend < min_notional_micro:
                break
            bought, fee = paper_buy(spend, close, taker_bps)
            if bought <= 0:
                break
            cash -= spend
            fees += fee
            entry = close
            peak = close
            base = bought
            spent = spend
            i += 1
            continue
        close = bars[i][2]
        if close > peak:
            peak = close
        reason = exit_reason(entry, close, peak, stop_bps, take_bps, trail_arm_bps, trail_gap_bps)
        if reason is None:
            i += 1
            continue
        credit, fee = paper_sell(base, close, taker_bps)
        fees += fee
        cash += credit
        pnl = credit - spent
        net += pnl
        trades += 1
        if pnl > 0:
            wins += 1
        fills.append(Fill(entry, close, pnl))
        entry = 0
        base = 0
        spent = 0
        i += 1
    return ReplayResult(trades, wins, net, fees, ended_open=entry != 0, fills=tuple(fills))
