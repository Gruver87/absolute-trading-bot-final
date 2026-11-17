#!/usr/bin/env python3
"""Unseen-tape gate helper (MEASUREMENT.md). Read-only: does not trade or change rules.

Computes two adjacent 1000-bar 5m windows entirely after 2026-10-14, with the
late window ending before the tip holdout of the latest 1000 bars. Each window
is run via ``python -m spotbot.replay_main --sleeves --prior-pays`` (unchanged).

Default: readiness check only (no heavy replay). Pass ``--run`` when ready.
Never flips SPOT_ENTRIES / live buys.

Each invocation appends one line to ``data/gate_history.jsonl`` (tip SHA,
timestamp, readiness or eight medians). Use ``--no-journal`` to skip.
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
sys.path.insert(0, str(ROOT))
from spotbot.gate_journal import (  # noqa: E402
    append_record,
    build_record,
    default_journal_path,
    tip_sha,
)
BAR_MS = 300_000
LIMIT = 1000
# Candles must be entirely after this calendar day (open >= 2026-10-15 00:00 UTC).
UNSEEN_AFTER_MS = int(datetime(2026, 10, 15, tzinfo=timezone.utc).timestamp() * 1000)

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


def plan_windows(now_ms: int) -> GatePlan:
    """Late end leaves tip holdout; early end is the previous 1000 bars."""
    if not isinstance(now_ms, int) or isinstance(now_ms, bool) or now_ms <= 0:
        raise ValueError("now_ms must be a positive int")
    late_end = now_ms - LIMIT * BAR_MS
    early_end = late_end - LIMIT * BAR_MS
    early_start = early_end - LIMIT * BAR_MS
    shortfall = 0
    if early_start < UNSEEN_AFTER_MS:
        shortfall = (UNSEEN_AFTER_MS - early_start + BAR_MS - 1) // BAR_MS
    return GatePlan(
        now_ms=now_ms,
        early_end_ms=early_end,
        late_end_ms=late_end,
        early_start_ms=early_start,
        ready=shortfall == 0 and early_end > 0 and late_end > early_end,
        shortfall_bars=int(shortfall),
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
    print(f"unseen_after_open>={after}")
    print(f"now_ms={plan.now_ms}")
    print(f"early_window end_ms={plan.early_end_ms} start_ms~={plan.early_start_ms}")
    print(f"late_window  end_ms={plan.late_end_ms}")
    print(f"limit={LIMIT} bar_ms={BAR_MS} tip_holdout_bars={LIMIT}")
    if plan.ready:
        print("ready: YES (two full windows fit after unseen cut + tip holdout)")
    else:
        mins = plan.shortfall_bars * 5
        print(
            f"ready: NO (need ~{plan.shortfall_bars} more 5m bars, ~{mins} minutes)"
        )


def _run_replay(end_ms: int) -> tuple[int, str]:
    cmd = [
        sys.executable,
        "-m",
        "spotbot.replay_main",
        "--sleeves",
        "--prior-pays",
        "--limit",
        str(LIMIT),
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


def _journal(
    enabled: bool,
    *,
    kind: str,
    result: str,
    ready: bool | None = None,
    now_ms: int | None = None,
    early: dict[str, float] | None = None,
    late: dict[str, float] | None = None,
) -> None:
    if not enabled:
        return
    try:
        record = build_record(
            kind=kind,
            result=result,
            tip=tip_sha(ROOT),
            early=early,
            late=late,
            ready=ready,
            now_ms=now_ms,
        )
        path = default_journal_path(ROOT)
        append_record(path, record)
        print(f"gate journal: appended {path}")
    except (OSError, ValueError, TypeError) as exc:
        print(f"gate journal write failed: {exc}", file=sys.stderr)


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
        "--now-ms",
        type=int,
        default=0,
        help="override server time (tests); 0 = ask KuCoin public clock",
    )
    parser.add_argument(
        "--no-journal",
        action="store_true",
        help="do not append data/gate_history.jsonl",
    )
    args = parser.parse_args(argv)
    journal_on = not bool(args.no_journal)

    now_ms = int(args.now_ms) if args.now_ms else 0
    if now_ms <= 0:
        # Local import so unit tests of plan_windows need no network.
        from spotbot.kucoin import KucoinClient, KucoinError, KucoinRateLimit

        try:
            now_ms = int(KucoinClient().server_time_ms())
        except (KucoinError, KucoinRateLimit) as exc:
            print(f"gate clock failed: {exc}", file=sys.stderr)
            return 1

    plan = plan_windows(now_ms)
    _print_plan(plan)
    if not plan.ready:
        print("GATE: NOT_READY (entries stay off; bot code untouched)")
        _journal(
            journal_on,
            kind="readiness",
            result="NOT_READY",
            ready=False,
            now_ms=plan.now_ms,
        )
        return 2

    if not args.run:
        print("GATE: READY (pass --run to execute both windows; entries stay off)")
        _journal(
            journal_on,
            kind="readiness",
            result="READY",
            ready=True,
            now_ms=plan.now_ms,
        )
        return 0

    print("--- window early ---")
    code_e, out_e = _run_replay(plan.early_end_ms)
    print(out_e.rstrip())
    if code_e != 0:
        print(f"GATE: FAIL (early window replay exit {code_e})", file=sys.stderr)
        _journal(
            journal_on,
            kind="run",
            result="FAIL",
            ready=True,
            now_ms=plan.now_ms,
        )
        return 1
    early = parse_pooled_medians(out_e)
    print("--- window late ---")
    code_l, out_l = _run_replay(plan.late_end_ms)
    print(out_l.rstrip())
    if code_l != 0:
        print(f"GATE: FAIL (late window replay exit {code_l})", file=sys.stderr)
        _journal(
            journal_on,
            kind="run",
            result="FAIL",
            ready=True,
            now_ms=plan.now_ms,
            early=early,
        )
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
        _journal(
            journal_on,
            kind="run",
            result="FAIL",
            ready=True,
            now_ms=plan.now_ms,
            early=early,
            late=late,
        )
        return 1

    if eight_strictly_positive(early, late):
        print(
            "GATE: PASS (all eight medians > 0). "
            "Paper entries still require an explicit operator step; this script does not enable them."
        )
        _journal(
            journal_on,
            kind="run",
            result="PASS",
            ready=True,
            now_ms=plan.now_ms,
            early=early,
            late=late,
        )
        return 0

    print("GATE: FAIL (not all eight medians strictly > 0; entries stay off)")
    _journal(
        journal_on,
        kind="run",
        result="FAIL",
        ready=True,
        now_ms=plan.now_ms,
        early=early,
        late=late,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
