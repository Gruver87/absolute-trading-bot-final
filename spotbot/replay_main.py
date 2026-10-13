"""Fetch public 5m candles and print both rules after taker fees. Does not trade.

The liquidity print uses only the candle half. The live rule also requires
the book and the other venues, which are not in this tape.
"""

from __future__ import annotations

import argparse
import sys

from spotbot.fees import STANDARD_TAKER_BPS
from spotbot.mexc import MexcClient, MexcError
from spotbot.money import format_usdt, parse_micro
from spotbot.replay import ReplayResult, holdout_cut, replay_closes, replay_lift_bars


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay RSI exits on MEXC 5m candles")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args(argv)
    if args.limit < 80 or args.limit > 1000:
        print("limit must be 80..1000", file=sys.stderr)
        return 2
    try:
        rows = MexcClient().ohlcv(args.symbol.upper(), "5m", args.limit)
    except MexcError as exc:
        print(f"replay failed: {exc}", file=sys.stderr)
        return 1
    closes = [row[3] for row in rows]
    bars = [(row[1], row[2], row[3], row[4]) for row in rows]
    if len(rows) >= 160:
        cut = holdout_cut(len(rows))
        _run_pair("earlier", args.symbol.upper(), closes[:cut], bars[:cut])
        _run_pair("later", args.symbol.upper(), closes[cut:], bars[cut:])
        print("both slices use the same fixed rule; a positive slice does not rest a limit or open the book socket")
    else:
        _run_pair("full", args.symbol.upper(), closes, bars)
    print("lift-candles omits the book and the oracle; it is not the live liquidity rule")
    return 0


def _run_pair(label: str, symbol: str, closes: list[int], bars: list[tuple[int, int, int, int]]) -> None:
    cash = parse_micro("1000")
    floor = parse_micro("3")
    result = replay_closes(
        closes,
        cash_micro=cash,
        alloc_bps=2_000,
        taker_bps=STANDARD_TAKER_BPS,
        rsi_buy=35,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        min_notional_micro=floor,
    )
    _print_result(f"rsi:{label}", symbol, len(closes), result, STANDARD_TAKER_BPS)
    lift = replay_lift_bars(
        bars,
        cash_micro=cash,
        alloc_bps=2_000,
        taker_bps=STANDARD_TAKER_BPS,
        min_notional_micro=floor,
    )
    _print_result(f"lift-candles:{label}", symbol, len(bars), lift, STANDARD_TAKER_BPS)


def _print_result(label: str, symbol: str, bars: int, result: ReplayResult, taker_bps: int) -> None:
    print(
        f"rule={label} symbol={symbol} bars={bars} trades={result.trades} "
        f"wins={result.wins} net={format_usdt(result.net_micro)} "
        f"fees={format_usdt(result.fees_micro)} open_at_end={result.ended_open} "
        f"taker_bps={taker_bps}"
    )
    for fill in result.fills[:8]:
        print(
            f"fill entry={format_usdt(fill.entry_micro)} exit={format_usdt(fill.exit_micro)} "
            f"pnl={format_usdt(fill.pnl_micro)}"
        )
    if result.trades == 0:
        print(f"{label}: no closed trade on this window")
    elif result.net_micro <= 0:
        print(f"{label}: rule did not beat taker fees on this window")
    else:
        print(f"{label}: positive after taker fees on this window only")


if __name__ == "__main__":
    sys.exit(main())
