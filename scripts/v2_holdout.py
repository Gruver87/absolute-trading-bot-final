#!/usr/bin/env python3
"""MEASUREMENT v2 Phase C — blind holdout (post-cut only).

Requires Candidate Spec env already frozen. Uses windows with open ≥ holdout_start
(2026-11-18). Never enables SPOT_ENTRIES.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from v2_windows import HOLDOUT_START_MS, LIMIT, plan_holdout_windows  # noqa: E402

_MEDIAN_LINE = re.compile(
    r"^median (earlier rsi|earlier lift-candles|later rsi|later lift-candles) "
    r"pairs=\d+ net=(-?\d+\.\d+)$"
)
_TRADE_LINE = re.compile(
    r"^rule=(rsi|lift-candles):(earlier|later) symbol=\S+ bars=\d+ trades=(\d+)\b"
)
_LABELS = (
    "earlier rsi",
    "earlier lift-candles",
    "later rsi",
    "later lift-candles",
)
_RULE_TO_LABEL = {
    ("rsi", "earlier"): "earlier rsi",
    ("lift-candles", "earlier"): "earlier lift-candles",
    ("rsi", "later"): "later rsi",
    ("lift-candles", "later"): "later lift-candles",
}
DENSITY_FLOOR = 8


def parse_medians(text: str) -> dict[str, float]:
    found: dict[str, float] = {}
    for line in text.splitlines():
        m = _MEDIAN_LINE.match(line.strip())
        if m:
            found[m.group(1)] = float(m.group(2))
    return found


def parse_trades(text: str) -> dict[str, int]:
    totals: dict[str, int] = defaultdict(int)
    for line in text.splitlines():
        m = _TRADE_LINE.match(line.strip())
        if not m:
            continue
        label = _RULE_TO_LABEL.get((m.group(1), m.group(2)))
        if label:
            totals[label] += int(m.group(3))
    return dict(totals)


def run_replay(end_ms: int) -> tuple[int, str]:
    cmd = [
        sys.executable,
        "-m",
        "spotbot.replay_main",
        "--sleeves",
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
        env=os.environ.copy(),
    )
    out = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    return int(proc.returncode), out


def main() -> int:
    entry = os.environ.get("RESEARCH_ENTRY", "").strip()
    atr = os.environ.get("RESEARCH_TRAIL_ATR_MULT", "").strip()
    if not entry or not atr:
        print(
            "HOLD: refuse — set RESEARCH_ENTRY and RESEARCH_TRAIL_ATR_MULT from frozen Candidate Spec",
            file=sys.stderr,
        )
        return 2

    from spotbot.kucoin import KucoinClient, KucoinError, KucoinRateLimit

    try:
        now_ms = int(KucoinClient().server_time_ms())
    except (KucoinError, KucoinRateLimit) as exc:
        print(f"holdout clock failed: {exc}", file=sys.stderr)
        return 1

    plan = plan_holdout_windows(now_ms)
    cut = datetime.fromtimestamp(HOLDOUT_START_MS / 1000, tz=timezone.utc).isoformat()
    print(f"phase=C holdout_start={cut}")
    print(f"candidate RESEARCH_ENTRY={entry} RESEARCH_TRAIL_ATR_MULT={atr}")
    print(f"now_ms={plan.now_ms}")
    print(
        f"early_end_ms={plan.early_end_ms} late_end_ms={plan.late_end_ms} "
        f"early_start_ms={plan.early_start_ms}"
    )
    if not plan.ready:
        mins = plan.shortfall_bars * 5
        print(
            f"HOLD: NOT_READY (need ~{plan.shortfall_bars} more 5m bars after holdout_start, "
            f"~{mins} minutes / ~{plan.shortfall_bars / 288:.1f} days)"
        )
        print("SPOT_ENTRIES=off; do not slide windows; wait for post-cut tape")
        return 2

    print("--- holdout early ---")
    ce, out_e = run_replay(plan.early_end_ms)
    print(out_e.rstrip())
    if ce != 0:
        print(f"HOLD: FAIL (early replay exit {ce})")
        return 1
    print("--- holdout late ---")
    cl, out_l = run_replay(plan.late_end_ms)
    print(out_l.rstrip())
    if cl != 0:
        print(f"HOLD: FAIL (late replay exit {cl})")
        return 1

    early = parse_medians(out_e)
    late = parse_medians(out_l)
    et = parse_trades(out_e)
    lt = parse_trades(out_l)
    print("--- eight medians ---")
    missing = False
    dens_fail = False
    all_pos = True
    for label in _LABELS:
        e, l = early.get(label), late.get(label)
        print(
            f"{label}: early={e!s} late={l!s} "
            f"trades_early={et.get(label, 0)} trades_late={lt.get(label, 0)}"
        )
        if e is None or l is None:
            missing = True
            continue
        if e <= 0 or l <= 0:
            all_pos = False
        if et.get(label, 0) < DENSITY_FLOOR or lt.get(label, 0) < DENSITY_FLOOR:
            dens_fail = True

    if missing:
        print("HOLD: FAIL (missing median)")
        return 1
    if dens_fail:
        print(f"HOLD: SPARSE (trades < {DENSITY_FLOOR} in a cell); candidate dead for unlock")
        return 1
    if all_pos:
        print("HOLD: PASS (bundle ok). Still no SPOT_ENTRIES; Phase D required.")
        return 0
    print("HOLD: FAIL (medians not all > 0); kill this candidate for unlock")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
