#!/usr/bin/env python3
"""Unseen-tape gate helper (MEASUREMENT.md). Read-only: does not trade or change rules.

Default (5m): two adjacent 1000-bar windows entirely after 2026-10-14, with the
late window ending before a tip holdout of the latest 1000 bars.

Higher-TF research (``--interval 15m|1h``): same *calendar* window as 1000×5m
(= 5000 minutes), converted to bar counts (ceil). 1h is floored at 160 bars so
holdout_cut / indicator warmup still work (documented bump vs pure calendar).

Each window runs ``python -m spotbot.replay_main --sleeves --prior-pays`` with
matching ``--interval`` / ``--limit``.

Default: readiness check only. Pass ``--run`` when ready.
Never flips SPOT_ENTRIES / live buys.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Frozen 5m reference from MEASUREMENT.md.
REF_INTERVAL = "5m"
REF_BAR_MS = 300_000
REF_LIMIT = 1000
REF_WINDOW_MS = REF_LIMIT * REF_BAR_MS  # 5000 minutes

_INTERVAL_MS = {
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
}

# holdout_cut requires >= 160 bars; 1h calendar map is only ~84.
_MIN_SPLIT_BARS = 160

# Candles must be entirely after this calendar day (open >= 2026-10-15 00:00 UTC).
UNSEEN_AFTER_MS = int(datetime(2026, 10, 15, tzinfo=timezone.utc).timestamp() * 1000)

# Back-compat aliases used by unit tests / importers.
BAR_MS = REF_BAR_MS
LIMIT = REF_LIMIT

# Pooled medians only (not "earlier rsi major").
_MEDIAN_LINE = re.compile(
    r"^median (earlier rsi|earlier lift-candles|later rsi|later lift-candles) "
    r"pairs=\d+ net=(-?\d+\.\d+)$"
)
_LABELS = (
    "earlier rsi",
    "earlier lift-candles",
    "later rsi",
    "later lift-candles",
)


@dataclass(frozen=True)
class GatePlan:
    now_ms: int
    early_end_ms: int
    late_end_ms: int
    early_start_ms: int
    ready: bool
    shortfall_bars: int
    interval: str = REF_INTERVAL
    bar_ms: int = REF_BAR_MS
    limit: int = REF_LIMIT
    calendar_equivalent: bool = True


def limit_for_interval(interval: str) -> int:
    """Bars per window: calendar-equivalent of 1000×5m, floored at 160, capped at 1000."""
    if interval not in _INTERVAL_MS:
        raise ValueError(f"unsupported interval {interval!r}")
    bar_ms = _INTERVAL_MS[interval]
    raw = (REF_WINDOW_MS + bar_ms - 1) // bar_ms
    return max(_MIN_SPLIT_BARS, min(REF_LIMIT, int(raw)))


def plan_windows(now_ms: int, interval: str = REF_INTERVAL) -> GatePlan:
    """Late end leaves tip holdout; early end is the previous window."""
    if not isinstance(now_ms, int) or isinstance(now_ms, bool) or now_ms <= 0:
        raise ValueError("now_ms must be a positive int")
    if interval not in _INTERVAL_MS:
        raise ValueError(f"unsupported interval {interval!r}")
    bar_ms = _INTERVAL_MS[interval]
    limit = limit_for_interval(interval)
    late_end = now_ms - limit * bar_ms
    early_end = late_end - limit * bar_ms
    early_start = early_end - limit * bar_ms
    shortfall = 0
    if early_start < UNSEEN_AFTER_MS:
        shortfall = (UNSEEN_AFTER_MS - early_start + bar_ms - 1) // bar_ms
    return GatePlan(
        now_ms=now_ms,
        early_end_ms=early_end,
        late_end_ms=late_end,
        early_start_ms=early_start,
        ready=shortfall == 0 and early_end > 0 and late_end > early_end,
        shortfall_bars=int(shortfall),
        interval=interval,
        bar_ms=bar_ms,
        limit=limit,
        calendar_equivalent=limit == (REF_WINDOW_MS + bar_ms - 1) // bar_ms
        or interval == REF_INTERVAL,
    )


def parse_pooled_medians(text: str) -> dict[str, float]:
    """Extract the four pooled median nets from one replay_main stdout."""
    found: dict[str, float] = {}
    for line in text.splitlines():
        m = _MEDIAN_LINE.match(line.strip())
        if not m:
            continue
        label, net_s = m.group(1), m.group(2)
        found[label] = float(net_s)
    return found


def eight_strictly_positive(early: dict[str, float], late: dict[str, float]) -> bool:
    for label in _LABELS:
        if label not in early or label not in late:
            return False
        if early[label] <= 0 or late[label] <= 0:
            return False
    return True


def _print_plan(plan: GatePlan) -> None:
    after = datetime.fromtimestamp(UNSEEN_AFTER_MS / 1000, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )
    mins_per_bar = plan.bar_ms // 60_000
    window_mins = plan.limit * mins_per_bar
    print(f"unseen_after_open>={after}")
    print(f"now_ms={plan.now_ms}")
    print(f"interval={plan.interval} bar_ms={plan.bar_ms}")
    print(
        f"limit={plan.limit} (ref 1000×5m = {REF_WINDOW_MS // 60_000}min; "
        f"this window ≈ {window_mins}min)"
    )
    if plan.interval == "1h" and plan.limit > (REF_WINDOW_MS + plan.bar_ms - 1) // plan.bar_ms:
        print(
            f"note: 1h calendar map would be {(REF_WINDOW_MS + plan.bar_ms - 1) // plan.bar_ms} bars; "
            f"raised to {plan.limit} for holdout_cut/warmup (>= {_MIN_SPLIT_BARS})"
        )
    print(f"early_window end_ms={plan.early_end_ms} start_ms~={plan.early_start_ms}")
    print(f"late_window  end_ms={plan.late_end_ms}")
    print(f"tip_holdout_bars={plan.limit}")
    if plan.ready:
        print("ready: YES (two full windows fit after unseen cut + tip holdout)")
    else:
        mins = plan.shortfall_bars * mins_per_bar
        print(
            f"ready: NO (need ~{plan.shortfall_bars} more {plan.interval} bars, ~{mins} minutes)"
        )


def _run_replay(end_ms: int, *, interval: str, limit: int) -> tuple[int, str]:
    cmd = [
        sys.executable,
        "-m",
        "spotbot.replay_main",
        "--sleeves",
        "--prior-pays",
        "--interval",
        interval,
        "--limit",
        str(limit),
        "--end-ms",
        str(end_ms),
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    return int(proc.returncode), out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Unseen-tape gate (read-only). Does not enable entries."
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="when ready, run two replay_main windows (public candles only)",
    )
    parser.add_argument(
        "--interval",
        default=REF_INTERVAL,
        choices=sorted(_INTERVAL_MS),
        help="candle interval (default 5m; research: 15m/1h)",
    )
    parser.add_argument(
        "--now-ms",
        type=int,
        default=0,
        help="override server time (tests); 0 = ask KuCoin public clock",
    )
    args = parser.parse_args(argv)

    now_ms = int(args.now_ms) if args.now_ms else 0
    if now_ms <= 0:
        # Local import so --help and unit tests of plan_windows need no network.
        sys.path.insert(0, str(ROOT))
        from spotbot.kucoin import KucoinClient, KucoinError, KucoinRateLimit

        try:
            now_ms = int(KucoinClient().server_time_ms())
        except (KucoinError, KucoinRateLimit) as exc:
            print(f"gate clock failed: {exc}", file=sys.stderr)
            return 1

    plan = plan_windows(now_ms, args.interval)
    _print_plan(plan)
    if not plan.ready:
        print("GATE: NOT_READY (entries stay off; bot code untouched)")
        return 2

    if not args.run:
        print("GATE: READY (pass --run to execute both windows; entries stay off)")
        return 0

    print("--- window early ---")
    code_e, out_e = _run_replay(plan.early_end_ms, interval=plan.interval, limit=plan.limit)
    print(out_e.rstrip())
    if code_e != 0:
        print(f"GATE: FAIL (early window replay exit {code_e})", file=sys.stderr)
        return 1
    early = parse_pooled_medians(out_e)
    print("--- window late ---")
    code_l, out_l = _run_replay(plan.late_end_ms, interval=plan.interval, limit=plan.limit)
    print(out_l.rstrip())
    if code_l != 0:
        print(f"GATE: FAIL (late window replay exit {code_l})", file=sys.stderr)
        return 1
    late = parse_pooled_medians(out_l)

    print("--- eight medians ---")
    missing = False
    for label in _LABELS:
        e = early.get(label)
        l = late.get(label)
        print(f"{label}: early={e!s} late={l!s}")
        if e is None or l is None:
            missing = True

    if missing:
        print("GATE: FAIL (missing pooled median line; entries stay off)")
        return 1

    if eight_strictly_positive(early, late):
        print(
            "GATE: PASS (all eight medians > 0). "
            "Paper entries still require an explicit operator step; this script does not enable them."
        )
        return 0

    print("GATE: FAIL (not all eight medians strictly > 0; entries stay off)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
