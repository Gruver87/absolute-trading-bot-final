# Research: trend-following (Donchian + ATR×3 trail)

**Branch:** `research/trend-following`  
**Protocol:** [`MEASUREMENT_v2.md`](MEASUREMENT_v2.md)  
**Live / paper entries:** off. Replay + `unseen_gate` only.

## Rule

1. **Entry:** close breaks the prior 20-bar Donchian high; quote volume ≥ 2× median of the prior 12 bars.  
2. **Exit:** trailing stop at **3 × ATR(14)** (Wilder) below peak; same distance as initial stop; no fixed take-profit.  
3. **No** `--prior-pays`.

## Env

| Variable | Default on this branch gate | Meaning |
|---|---|---|
| `RESEARCH_ENTRY` | `donchian_20` | Donchian 20 + volume |
| `RESEARCH_TRAIL_ATR_MULT` | `3` | ATR multiple for stop/trail gap |

## Run

```bash
python3 scripts/unseen_gate.py --run
```

Does not flip `SPOT_ENTRIES`. Do not merge to `main` until gate PASS under v2 bundle (and operator still must unlock).
