"""Replay one symbol on closed candles. No lookahead, taker fee on both sides.

The result is the rule on this window, not a forecast.
"""

from __future__ import annotations

from dataclasses import dataclass

from spotbot.exits import exit_reason
from spotbot.fees import paper_sell
from spotbot.liquidity import candle_lift
from spotbot.money import notional_micro
from spotbot.rules import budget_micro, plan_paper_buy
from spotbot.sanity import mark_ok, price_ok, slip_price
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
    open_micro: int = 0
    open_known: bool = True


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
    base_step_atoms: int = 1,
    slip_bps: int = 0,
) -> ReplayResult:
    if not closes or closes[0] <= 0 or base_step_atoms <= 0:
        return ReplayResult(0, 0, 0, 0, False, ())
    clean = [closes[0]]
    for price in closes[1:]:
        if price > 0 and price_ok(clean[-1], price):
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
            fill = _next_price(closes, i)
            paid = slip_price(fill or 0, slip_bps, True)
            if paid <= 0:
                break
            spend = budget_micro(cash, alloc_bps)
            if spend < min_notional_micro:
                break
            planned = plan_paper_buy(spend, paid, base_step_atoms, taker_bps)
            if planned is None:
                break
            bought, fee, debit = planned
            cash -= debit
            fees += fee
            entry = paid
            peak = paid
            base = bought
            spent = debit
            i += 2
            continue
        price = slip_price(closes[i], slip_bps, False)
        if price <= 0 or not mark_ok(peak, price):
            i += 1
            continue
        if price > peak:
            peak = price
        reason = exit_reason(entry, price, peak, stop_bps, take_bps, trail_arm_bps, trail_gap_bps)
        if reason is None:
            i += 1
            continue
        fill = _next_price(closes, i)
        sold = slip_price(fill or 0, slip_bps, False)
        if sold <= 0 or not mark_ok(peak, sold):
            i += 1
            continue
        credit, fee = paper_sell(base, sold, taker_bps)
        gross = notional_micro(base, sold)
        if credit <= 0 or fee < 0 or credit + fee != gross:
            i += 1
            continue
        fees += fee
        cash += credit
        pnl = credit - spent
        net += pnl
        trades += 1
        if pnl > 0:
            wins += 1
        fills.append(Fill(entry, sold, pnl))
        entry = 0
        base = 0
        spent = 0
        i += 2
    mark, known = _open_mark(entry, peak, base, spent, closes[-1] if closes else 0, taker_bps, slip_bps)
    return ReplayResult(
        trades, wins, net, fees, ended_open=entry != 0, fills=tuple(fills), open_micro=mark, open_known=known
    )


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
    base_step_atoms: int = 1,
    slip_bps: int = 0,
) -> ReplayResult:
    """Candle half of the liquidity rule. Bid/ask and the oracle are not in the tape.

    Each bar is high, low, close, quote volume. A jump in close is dropped.
    """
    if not bars or bars[0][2] <= 0 or base_step_atoms <= 0:
        return ReplayResult(0, 0, 0, 0, False, ())
    clean = [bars[0]]
    for bar in bars[1:]:
        if bar[2] > 0 and price_ok(clean[-1][2], bar[2]):
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
            fill = _next_price([bar[2] for bar in bars], i)
            paid = slip_price(fill or 0, slip_bps, True)
            if paid <= 0:
                break
            spend = budget_micro(cash, alloc_bps)
            if spend < min_notional_micro:
                break
            planned = plan_paper_buy(spend, paid, base_step_atoms, taker_bps)
            if planned is None:
                break
            bought, fee, debit = planned
            cash -= debit
            fees += fee
            entry = paid
            peak = paid
            base = bought
            spent = debit
            i += 2
            continue
        close = slip_price(bars[i][2], slip_bps, False)
        if close <= 0 or not mark_ok(peak, close):
            i += 1
            continue
        if close > peak:
            peak = close
        reason = exit_reason(entry, close, peak, stop_bps, take_bps, trail_arm_bps, trail_gap_bps)
        if reason is None:
            i += 1
            continue
        fill = _next_price([bar[2] for bar in bars], i)
        sold = slip_price(fill or 0, slip_bps, False)
        if sold <= 0 or not mark_ok(peak, sold):
            i += 1
            continue
        credit, fee = paper_sell(base, sold, taker_bps)
        gross = notional_micro(base, sold)
        if credit <= 0 or fee < 0 or credit + fee != gross:
            i += 1
            continue
        fees += fee
        cash += credit
        pnl = credit - spent
        net += pnl
        trades += 1
        if pnl > 0:
            wins += 1
        fills.append(Fill(entry, sold, pnl))
        entry = 0
        base = 0
        spent = 0
        i += 2
    last = bars[-1][2] if bars else 0
    mark, known = _open_mark(entry, peak, base, spent, last, taker_bps, slip_bps)
    return ReplayResult(
        trades, wins, net, fees, ended_open=entry != 0, fills=tuple(fills), open_micro=mark, open_known=known
    )


def _next_price(prices: list[int], index: int) -> int | None:
    """Close of the following bar. The signal bar is not the fill."""
    nxt = index + 1
    if nxt >= len(prices) or prices[nxt] <= 0:
        return None
    return prices[nxt]


def _open_mark(
    entry: int, peak: int, base: int, spent: int, price: int, taker_bps: int, slip_bps: int
) -> tuple[int, bool]:
    """Open mark after the sell fee and the spread. Unknown when the price cannot be used."""
    if entry == 0:
        return 0, True
    sold = slip_price(price, slip_bps, False)
    if base <= 0 or spent <= 0 or sold <= 0 or not mark_ok(peak, sold):
        return 0, False
    credit, fee = paper_sell(base, sold, taker_bps)
    gross = notional_micro(base, sold)
    if credit <= 0 or fee < 0 or credit + fee != gross:
        return 0, False
    return credit - spent, True


def hold_net(
    closes: list[int],
    *,
    cash_micro: int,
    alloc_bps: int,
    taker_bps: int,
    base_step_atoms: int,
    min_notional_micro: int,
    slip_bps: int = 0,
) -> int | None:
    """Buy the same allocation as the rule after warmup and sell on the last close.

    None means the hold could not be priced.
    """
    if len(closes) < 42 or base_step_atoms <= 0 or closes[41] <= 0 or closes[-1] <= 0:
        return None
    spend = budget_micro(cash_micro, alloc_bps)
    if spend < min_notional_micro:
        return None
    buy = slip_price(closes[41], slip_bps, True)
    sell = slip_price(closes[-1], slip_bps, False)
    if buy <= 0 or sell <= 0:
        return None
    planned = plan_paper_buy(spend, buy, base_step_atoms, taker_bps)
    if planned is None:
        return None
    base, _fee, debit = planned
    credit, fee = paper_sell(base, sell, taker_bps)
    gross = notional_micro(base, sell)
    if credit <= 0 or fee < 0 or credit + fee != gross:
        return None
    return credit - debit


def median_micro(values: list[int]) -> int | None:
    """Middle value. An even count uses the lower of the two middle values."""
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return min(ordered[mid - 1], ordered[mid])
