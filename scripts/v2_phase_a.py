#!/usr/bin/env python3
"""MEASUREMENT v2 Phase A — pre-cut research only.

Runs a small candidate set on two windows ending before research_cut (2026-11-18).
Does not use post-cut tape. Does not enable SPOT_ENTRIES. Does not merge to main.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from v2_windows import LIMIT, RESEARCH_CUT_MS, plan_research_windows  # noqa: E402

_MEDIAN_LINE = re.compile(
    r"^median (earlier rsi|earlier lift-candles|later rsi|later lift-candles) "
    r"pairs=\d+ net=(-?\d+\.\d+)$"
)
_TRADE_LINE = re.compile(
    r"^rule=(rsi|lift-candles):(earlier|later) symbol=\S+ bars=\d+ trades=(\d+)\b"
    r".* stops=(\d+) trails=(\d+) takes=(\d+)"
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

# Disciplined set — survive cost stack; no combinatorial grid.
CANDIDATES = (
    {"id": "A1", "entry": "donchian_20", "atr": "3", "note": "baseline Donchian-20 + ATR×3"},
    {"id": "A2", "entry": "donchian_20", "atr": "4", "note": "wider ATR×4 trail"},
    {"id": "A3", "entry": "donchian_55", "atr": "3", "note": "longer Donchian-55 + ATR×3"},
    {"id": "A4", "entry": "donchian_20_vol15", "atr": "3", "note": "Donchian-20 vol≥1.5× + ATR×3"},
    {"id": "A5", "entry": "bb_mr", "atr": "3", "note": "BB reclaim alt entry + ATR×3"},
)


@dataclass
class WindowScore:
    medians: dict[str, float]
    trades: dict[str, int]
    stops: dict[str, int]
    trails: dict[str, int]
    takes: dict[str, int]


def parse_window(text: str) -> WindowScore:
    medians: dict[str, float] = {}
    trades: dict[str, int] = defaultdict(int)
    stops: dict[str, int] = defaultdict(int)
    trails: dict[str, int] = defaultdict(int)
    takes: dict[str, int] = defaultdict(int)
    for line in text.splitlines():
        s = line.strip()
        m = _MEDIAN_LINE.match(s)
        if m:
            medians[m.group(1)] = float(m.group(2))
            continue
        t = _TRADE_LINE.match(s)
        if t:
            label = _RULE_TO_LABEL.get((t.group(1), t.group(2)))
            if label is None:
                continue
            trades[label] += int(t.group(3))
            stops[label] += int(t.group(4))
            trails[label] += int(t.group(5))
            takes[label] += int(t.group(6))
    return WindowScore(medians, dict(trades), dict(stops), dict(trails), dict(takes))


def run_replay(end_ms: int, entry: str, atr: str) -> tuple[int, str]:
    env = os.environ.copy()
    env["RESEARCH_ENTRY"] = entry
    env["RESEARCH_TRAIL_ATR_MULT"] = atr
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
        env=env,
    )
    out = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    return int(proc.returncode), out


def score_candidate(early: WindowScore, late: WindowScore) -> dict[str, object]:
    eight = []
    sparse = False
    all_pos = True
    for label in _LABELS:
        e = early.medians.get(label)
        l = late.medians.get(label)
        et = early.trades.get(label, 0)
        lt = late.trades.get(label, 0)
        es = early.stops.get(label, 0)
        ls = late.stops.get(label, 0)
        eight.append(
            {
                "label": label,
                "early": e,
                "late": l,
                "trades_e": et,
                "trades_l": lt,
                "stops_e": es,
                "stops_l": ls,
                "stop_share_e": (es / et) if et else None,
                "stop_share_l": (ls / lt) if lt else None,
            }
        )
        if e is None or l is None:
            all_pos = False
            sparse = True
            continue
        if e <= 0 or l <= 0:
            all_pos = False
        if et < 8 or lt < 8:
            sparse = True
    if sparse and not all_pos:
        outcome = "SPARSE" if any(
            (r["trades_e"] or 0) < 8 or (r["trades_l"] or 0) < 8 for r in eight
        ) and not all_pos else "FAIL"
        # Prefer SPARSE only when density fails
        dens_fail = any((r["trades_e"] or 0) < 8 or (r["trades_l"] or 0) < 8 for r in eight)
        outcome = "SPARSE" if dens_fail else ("PASS" if all_pos else "FAIL")
    else:
        dens_fail = any((r["trades_e"] or 0) < 8 or (r["trades_l"] or 0) < 8 for r in eight)
        if dens_fail:
            outcome = "SPARSE"
        elif all_pos:
            outcome = "PASS"
        else:
            outcome = "FAIL"
    # Rank key: how many of 8 cells > 0, then sum of medians, then density
    n_green = sum(
        1
        for r in eight
        if isinstance(r["early"], float)
        and isinstance(r["late"], float)
        and r["early"] > 0
        and r["late"] > 0
    )
    # Count individual half greens (0..8)
    n_half = 0
    median_sum = 0.0
    for r in eight:
        for side in ("early", "late"):
            v = r[side]
            if isinstance(v, float):
                median_sum += v
                if v > 0:
                    n_half += 1
    return {
        "outcome": outcome,
        "n_green_pairs": n_green,
        "n_half_green": n_half,
        "median_sum": median_sum,
        "rows": eight,
    }


def main() -> int:
    plan = plan_research_windows()
    cut = datetime.fromtimestamp(RESEARCH_CUT_MS / 1000, tz=timezone.utc).isoformat()
    print(f"phase=A research_cut={cut}")
    print(
        f"windows early_end_ms={plan.early_end_ms} late_end_ms={plan.late_end_ms} "
        f"early_start_ms={plan.early_start_ms} ready={plan.ready}"
    )
    if not plan.ready:
        print("PHASE_A: NOT_READY")
        return 2

    results = []
    for cand in CANDIDATES:
        print(f"\n=== {cand['id']} {cand['note']} ===")
        print(f"RESEARCH_ENTRY={cand['entry']} RESEARCH_TRAIL_ATR_MULT={cand['atr']}")
        print("--- early window ---")
        ce, out_e = run_replay(plan.early_end_ms, cand["entry"], cand["atr"])
        print(out_e.rstrip()[-4000:] if len(out_e) > 4000 else out_e.rstrip())
        if ce != 0:
            print(f"{cand['id']}: FAIL replay early exit={ce}")
            results.append({"id": cand["id"], **cand, "outcome": "FAIL", "error": f"early {ce}"})
            continue
        print("--- late window ---")
        cl, out_l = run_replay(plan.late_end_ms, cand["entry"], cand["atr"])
        print(out_l.rstrip()[-4000:] if len(out_l) > 4000 else out_l.rstrip())
        if cl != 0:
            print(f"{cand['id']}: FAIL replay late exit={cl}")
            results.append({"id": cand["id"], **cand, "outcome": "FAIL", "error": f"late {cl}"})
            continue
        early = parse_window(out_e)
        late = parse_window(out_l)
        scored = score_candidate(early, late)
        print(f"--- score {cand['id']} outcome={scored['outcome']} "
              f"half_green={scored['n_half_green']}/8 median_sum={scored['median_sum']:.4f} ---")
        for row in scored["rows"]:
            print(
                f"{row['label']}: early={row['early']} late={row['late']} "
                f"trades={row['trades_e']}/{row['trades_l']} "
                f"stops={row['stops_e']}/{row['stops_l']} "
                f"stop_share={row['stop_share_e']}/{row['stop_share_l']}"
            )
        results.append({"id": cand["id"], **cand, **scored})

    print("\n=== Phase A ranking ===")
    ranked = sorted(
        [r for r in results if "median_sum" in r],
        key=lambda r: (r.get("n_half_green", 0), r.get("median_sum", -1e9)),
        reverse=True,
    )
    for r in ranked:
        print(
            f"{r['id']} {r['entry']} atr×{r['atr']}: {r['outcome']} "
            f"half_green={r['n_half_green']}/8 sum={r['median_sum']:.4f}"
        )
    if ranked:
        best = ranked[0]
        print(f"BEST_FOR_SPEC={best['id']} entry={best['entry']} atr={best['atr']} outcome={best['outcome']}")
    else:
        print("BEST_FOR_SPEC=none")
    print("SPOT_ENTRIES=off; no post-cut peek; no main merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
