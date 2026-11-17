# Research: higher-TF unseen gate (15m / 1h)

**Branch:** `research/higher-tf-gate` (forked from `research/entry-signals` hooks)  
**Base:** does **not** edit `main` or frozen `docs/MEASUREMENT.md`.  
**Live:** `SPOT_ENTRIES` stays off.

## Window mapping

Frozen MEASUREMENT window = **1000 × 5m** = **5000 minutes** calendar.

| Interval | Pure calendar bars | Bars used | Notes |
|---|---:|---:|---|
| 5m | 1000 | 1000 | unchanged |
| 15m | ceil(5000/15)=334 | **334** | same calendar span |
| 1h | ceil(5000/60)=84 | **160** | raised for `holdout_cut` (≥160) + warmup |

Tip holdout = one window of the same bar count. Unseen cut unchanged (`open ≥ 2026-10-15`).

```bash
python3 scripts/unseen_gate.py --interval 15m
RESEARCH_ENTRY=bb_mr python3 scripts/unseen_gate.py --interval 15m --run
RESEARCH_ENTRY=breakout RESEARCH_ATR_MULT=2 python3 scripts/unseen_gate.py --interval 1h --run
```

`RESEARCH_ENTRY` / `RESEARCH_ATR_MULT` are replay-only env knobs from the entry-signals research port.
