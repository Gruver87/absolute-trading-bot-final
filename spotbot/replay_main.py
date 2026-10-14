"""Fetch public 5m candles and print both rules after taker fees. Does not trade.

The liquidity print uses only the candle half. The live rule also requires
the book and the other venues, which are not in this tape.
"""

from __future__ import annotations

import argparse
import sys
import time

from spotbot.mexc import MexcClient, MexcError, MexcRateLimit
from spotbot.rules import RuleError
from spotbot.money import format_price, format_usdt, parse_micro
from spotbot.replay import ReplayResult, hold_net, holdout_cut, median_micro, replay_closes, replay_lift_bars
from spotbot.sanity import tick_fits
from spotbot.sleeves import sleeve_symbols

# Same cap the live buy already refuses. The tape has no historical spread.
SPREAD_SLIP_BPS = 30


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay RSI exits on MEXC 5m candles")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--sleeves", action="store_true", help="replay the fixed 14 pairs and print the median")
    args = parser.parse_args(argv)
    if args.limit < 80 or args.limit > 1000:
        print("limit must be 80..1000", file=sys.stderr)
        return 2
    symbols = list(sleeve_symbols()) if args.sleeves else [args.symbol.upper()]
    later_rsi: list[int] = []
    later_lift: list[int] = []
    earlier_rsi: list[int] = []
    earlier_lift: list[int] = []
    zero_fee: list[str] = []
    left_out: list[str] = []
    client = MexcClient()
    for index, symbol in enumerate(symbols):
        if index:
            time.sleep(0.2)
        try:
            rule = client.symbol_rule(symbol)
            if not rule.tradable or rule.base_step_atoms <= 0:
                reason = rule.refuse_reason or "no lot"
                if not args.sleeves:
                    print(f"replay refused: {symbol} {reason}", file=sys.stderr)
                    return 1
                left_out.append(symbol)
                print(f"{symbol}: {reason}; left out of the median")
                continue
            rows = client.ohlcv(symbol, "5m", args.limit)
        except MexcRateLimit as exc:
            print(f"replay stopped on rate limit: {exc}", file=sys.stderr)
            print("median refused: the tape is incomplete")
            return 1
        except (MexcError, RuleError) as exc:
            if not args.sleeves:
                print(f"replay failed: {symbol} {exc}", file=sys.stderr)
                return 1
            left_out.append(symbol)
            print(f"{symbol}: {exc}; left out of the median")
            continue
        if len(rows) >= 2:
            rows = rows[:-1]
        opens = [row[0] for row in rows]
        closes = [row[3] for row in rows]
        bars = [(row[1], row[2], row[3], row[4]) for row in rows]
        step = rule.base_step_atoms
        taker = rule.taker_bps
        if taker == 0:
            zero_fee.append(symbol)
            print(f"{symbol}: exchange reported taker 0; left out of the median")
        keep = taker > 0
        if len(rows) >= 160:
            cut = holdout_cut(len(rows))
            e_rsi, e_lift = _run_pair(
                "earlier", symbol, closes[:cut], bars[:cut], step, rule.price_tick, taker, median=keep, opens=opens[:cut]
            )
            rsi_net, lift_net = _run_pair(
                "later",
                symbol,
                closes,
                bars,
                step,
                rule.price_tick,
                taker,
                median=keep,
                entry_from=cut,
                opens=opens,
            )
            if e_rsi is not None:
                earlier_rsi.append(e_rsi)
            if e_lift is not None:
                earlier_lift.append(e_lift)
            if rsi_net is not None:
                later_rsi.append(rsi_net)
            if lift_net is not None:
                later_lift.append(lift_net)
        else:
            _run_pair("full", symbol, closes, bars, step, rule.price_tick, taker, median=False, opens=opens)
    if args.sleeves:
        _print_median("earlier rsi", earlier_rsi)
        _print_median("earlier lift-candles", earlier_lift)
        _print_median("later rsi", later_rsi)
        _print_median("later lift-candles", later_lift)
        if zero_fee:
            print("zero taker left out: " + ",".join(zero_fee))
        if left_out:
            print("no lot left out: " + ",".join(left_out))
        print("median is closed trades plus the open mark; a positive median does not rest a limit or open the book socket")
    elif later_rsi or later_lift:
        print("both slices use the same fixed rule; a positive slice does not rest a limit or open the book socket")
    print("lift-candles omits the book and the oracle; it is not the live liquidity rule")
    print("hold buys the same allocation as the rule; an open position is marked and is not subtracted from the hold")
    return 0


def _run_pair(
    label: str,
    symbol: str,
    closes: list[int],
    bars: list[tuple[int, int, int, int]],
    base_step_atoms: int,
    price_tick: int,
    taker_bps: int,
    median: bool,
    entry_from: int = 0,
    opens: list[int] | None = None,
) -> tuple[int | None, int | None]:
    cash = parse_micro("1000")
    floor = parse_micro("3")
    traded = closes[entry_from:]
    traded_bars = bars[entry_from:]
    rsi_net: int | None = None
    if _grid_ok(traded, price_tick, 350):
        result = replay_closes(
        closes,
        cash_micro=cash,
        alloc_bps=2_000,
        taker_bps=taker_bps,
        rsi_buy=35,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        min_notional_micro=floor,
        base_step_atoms=base_step_atoms,
        slip_bps=SPREAD_SLIP_BPS,
        entry_from=entry_from,
        opens=opens,
        cooldown_bars=3,
        lookback_bars=288,
        lock_bars=48,
        lock_count=3,
        )
        _print_result(f"rsi:{label}", symbol, len(traded), result, taker_bps)
        _print_hold(label, symbol, traded, result, taker_bps, base_step_atoms, floor)
        if median:
            rsi_net = _account(result)
    else:
        print(f"rsi:{label} symbol={symbol} refused: price step is wider than the 350 bps stop")
    lift_net: int | None = None
    if _grid_ok([bar[2] for bar in traded_bars], price_tick, 150):
        lift = replay_lift_bars(
        bars,
        cash_micro=cash,
        alloc_bps=2_000,
        taker_bps=taker_bps,
        min_notional_micro=floor,
        base_step_atoms=base_step_atoms,
        slip_bps=SPREAD_SLIP_BPS,
        entry_from=entry_from,
        opens=opens,
        cooldown_bars=3,
        lookback_bars=288,
        lock_bars=48,
        lock_count=3,
        )
        _print_result(f"lift-candles:{label}", symbol, len(traded_bars), lift, taker_bps)
        if median:
            lift_net = _account(lift)
    else:
        print(f"lift-candles:{label} symbol={symbol} refused: price step is wider than the 150 bps stop")
    return rsi_net, lift_net


def _print_result(label: str, symbol: str, bars: int, result: ReplayResult, taker_bps: int) -> None:
    print(
        f"rule={label} symbol={symbol} bars={bars} trades={result.trades} "
        f"wins={result.wins} net={format_usdt(result.net_micro)} "
        f"fees={format_usdt(result.fees_micro)} open_at_end={result.ended_open} "
        f"taker_bps={taker_bps}"
    )
    for fill in result.fills[:8]:
        print(
            f"fill entry={format_price(fill.entry_micro)} exit={format_price(fill.exit_micro)} "
            f"pnl={format_usdt(fill.pnl_micro)}"
        )
    if result.ended_open and not result.open_known:
        print(f"{label}: open mark unavailable; this pair is left out of the median")
    elif result.ended_open:
        print(f"{label}: open mark {format_usdt(result.open_micro)}; closed net does not include it")
    elif result.trades == 0:
        print(f"{label}: no closed trade on this window")
    elif result.net_micro <= 0:
        print(f"{label}: rule did not beat taker fees on this window")
    else:
        print(f"{label}: positive after taker fees on this window only")


def _account(result: ReplayResult) -> int | None:
    """Closed result plus the open mark. An open position we cannot price is left out."""
    if result.ended_open and not result.open_known:
        return None
    return result.net_micro + result.open_micro


def _grid_ok(prices: list[int], price_tick: int, stop_bps: int) -> bool:
    return bool(prices) and all(tick_fits(price, price_tick, stop_bps) for price in prices)


def _print_hold(
    label: str,
    symbol: str,
    closes: list[int],
    result: ReplayResult,
    taker_bps: int,
    base_step_atoms: int,
    floor: int,
) -> None:
    held = hold_net(
        closes,
        cash_micro=parse_micro("1000"),
        alloc_bps=2_000,
        taker_bps=taker_bps,
        base_step_atoms=base_step_atoms,
        min_notional_micro=floor,
        slip_bps=SPREAD_SLIP_BPS,
    )
    if held is None:
        print(f"hold:{label} symbol={symbol} unavailable")
        return
    if result.ended_open and not result.open_known:
        print(f"hold:{label} symbol={symbol} net={format_usdt(held)} open_mark=unavailable")
        return
    if result.ended_open:
        print(
            f"hold:{label} symbol={symbol} net={format_usdt(held)} "
            f"open_mark={format_usdt(result.open_micro)} not comparable while the rule is open"
        )
        return
    print(
        f"hold:{label} symbol={symbol} net={format_usdt(held)} "
        f"rule_minus_hold={format_usdt(result.net_micro - held)}"
    )


def _print_median(label: str, values: list[int]) -> None:
    mid = median_micro(values)
    if mid is None:
        print(f"median {label}: no slice")
        return
    print(f"median {label} pairs={len(values)} net={format_usdt(mid)}")
    if mid <= 0:
        print(f"median {label}: rule did not beat taker fees")
    else:
        print(f"median {label}: positive after taker fees on these windows only")


if __name__ == "__main__":
    sys.exit(main())
