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
from spotbot.mexc import KLINE_LIMIT
from spotbot.signals import entry_signal, reclaim_still


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
    entry_from: int = 0,
    opens: list[int] | None = None,
    cooldown_bars: int = 0,
    lookback_bars: int = 0,
    lock_bars: int = 0,
    lock_count: int = 3,
) -> ReplayResult:
    if (
        not closes
        or closes[0] <= 0
        or base_step_atoms <= 0
        or isinstance(entry_from, bool)
        or not isinstance(entry_from, int)
        or entry_from < 0
        or not _bar_span(cooldown_bars)
        or not _bar_span(lookback_bars)
        or not _bar_span(lock_bars)
        or isinstance(lock_count, bool)
        or not isinstance(lock_count, int)
        or lock_count < 2
        or (opens is not None and (not isinstance(opens, list) or len(opens) != len(closes)))
    ):
        return ReplayResult(0, 0, 0, 0, False, ())
    clean: list[int] = []
    clean_opens: list[int] | None = [] if opens is not None else None
    for index, price in enumerate(closes):
        if not _usable(price):
            continue
        if opens is not None and not _usable(opens[index]):
            continue
        clean.append(price)
        if clean_opens is not None and opens is not None:
            clean_opens.append(opens[index])
    if not clean:
        return ReplayResult(0, 0, 0, 0, False, ())
    closes = clean
    opens = clean_opens
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
    stamps: list[int] = []
    cooldown_until = 0
    lock_until = 0
    while i < len(closes):
        if entry == 0:
            if i < entry_from or i < cooldown_until or i < lock_until or _entry_jump(closes, i):
                i += 1
                continue
            window = _signal_closes(closes, i)
            if entry_signal("REPLAY", window, rsi_buy) is None:
                i += 1
                continue
            fill = _fill_price(opens, closes, i)
            if fill is not None and fill > 0 and not reclaim_still(window, fill):
                i += 1
                continue
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
            i += 1
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
        sold = price
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
        stamps, cooldown_until, lock_until = _after_stop(
            reason, i, cooldown_bars, lookback_bars, lock_bars, lock_count, stamps, cooldown_until, lock_until
        )
        entry = 0
        base = 0
        spent = 0
        i += 1
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
    entry_from: int = 0,
    opens: list[int] | None = None,
    cooldown_bars: int = 0,
    lookback_bars: int = 0,
    lock_bars: int = 0,
    lock_count: int = 3,
) -> ReplayResult:
    """Candle half of the liquidity rule. Bid/ask and the oracle are not in the tape.

    Each bar is high, low, close, quote volume. A jumped close stays in the tape.
    """
    if (
        not bars
        or bars[0][2] <= 0
        or base_step_atoms <= 0
        or isinstance(entry_from, bool)
        or not isinstance(entry_from, int)
        or entry_from < 0
        or not _bar_span(cooldown_bars)
        or not _bar_span(lookback_bars)
        or not _bar_span(lock_bars)
        or isinstance(lock_count, bool)
        or not isinstance(lock_count, int)
        or lock_count < 2
        or (opens is not None and (not isinstance(opens, list) or len(opens) != len(bars)))
    ):
        return ReplayResult(0, 0, 0, 0, False, ())
    clean: list[tuple[int, int, int, int]] = []
    clean_opens: list[int] | None = [] if opens is not None else None
    for index, bar in enumerate(bars):
        if bar[2] <= 0:
            continue
        if opens is not None and not _usable(opens[index]):
            continue
        clean.append(bar)
        if clean_opens is not None and opens is not None:
            clean_opens.append(opens[index])
    if not clean:
        return ReplayResult(0, 0, 0, 0, False, ())
    bars = clean
    opens = clean_opens
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
    stamps: list[int] = []
    cooldown_until = 0
    lock_until = 0
    while i < len(bars):
        if entry == 0:
            if i < entry_from or i < cooldown_until or i < lock_until or _entry_jump([bar[2] for bar in bars], i):
                i += 1
                continue
            window = bars[: i + 1]
            volumes = [bar[3] for bar in window] + [1]
            high, low, close, _quote = window[-1]
            if candle_lift("REPLAY", volumes, high, low, close) is None:
                i += 1
                continue
            fill = _fill_price(opens, [bar[2] for bar in bars], i)
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
            i += 1
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
        sold = close
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
        stamps, cooldown_until, lock_until = _after_stop(
            reason, i, cooldown_bars, lookback_bars, lock_bars, lock_count, stamps, cooldown_until, lock_until
        )
        entry = 0
        base = 0
        spent = 0
        i += 1
    last = bars[-1][2] if bars else 0
    mark, known = _open_mark(entry, peak, base, spent, last, taker_bps, slip_bps)
    return ReplayResult(
        trades, wins, net, fees, ended_open=entry != 0, fills=tuple(fills), open_micro=mark, open_known=known
    )


def _entry_jump(closes: list[int], index: int) -> bool:
    """The cycle keeps a jumped close and only refuses the entry on that bar."""
    if index <= 0:
        return False
    try:
        return not price_ok(closes[index - 1], closes[index])
    except ValueError:
        return True


def _signal_closes(closes: list[int], index: int) -> list[int]:
    """Same closed bars the cycle sees: the fetch minus the candle that is still open."""
    keep = KLINE_LIMIT - 1
    if keep < 1 or index < 0:
        return []
    start = 0 if index + 1 <= keep else index + 1 - keep
    return closes[start : index + 1]


def _bar_span(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _after_stop(
    reason: str,
    index: int,
    cooldown_bars: int,
    lookback_bars: int,
    lock_bars: int,
    lock_count: int,
    stamps: list[int],
    cooldown_until: int,
    lock_until: int,
) -> tuple[list[int], int, int]:
    """A stop waits, and enough stops inside a day lock the pair. Other exits do not."""
    if reason != "stop":
        return stamps, cooldown_until, lock_until
    if cooldown_bars > 0:
        cooldown_until = index + cooldown_bars
    if lookback_bars > 0:
        stamps = [stamp for stamp in stamps if index - lookback_bars < stamp <= index]
    stamps.append(index)
    stamps = stamps[-8:]
    if lock_bars > 0 and len(stamps) >= lock_count:
        lock_until = index + lock_bars
    return stamps, cooldown_until, lock_until


def _usable(price: object) -> bool:
    return isinstance(price, int) and not isinstance(price, bool) and 0 < price < 10**24


def _fill_price(opens: list[int] | None, closes: list[int], index: int) -> int | None:
    """First traded price after the signal bar.

    A market order fires at the next open. Callers without opens keep the next close.
    """
    nxt = index + 1
    if opens is not None:
        if nxt >= len(opens) or not _usable(opens[nxt]):
            return None
        return opens[nxt]
    return _next_price(closes, index)


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
