# MEASUREMENT protocol v2 (research branch)

**Status:** Accepted 2026-11-17. Lives on **`research/trend-following` only** until a gate **PASS**. Do not merge strategy to `main` until PASS. `SPOT_ENTRIES` stays off.

**v1 archive:** [`docs/archive/MEASUREMENT_v1.md`](archive/MEASUREMENT_v1.md)  
**Project store draft (accepted):** Project Context → `docs/measurement-protocol-v2-draft.md`  
**Stop record:** Project Context → `docs/strategy-stop-2026-11-17.md`

## Cuts

| Name | Value |
|---|---|
| `research_cut` / `holdout_start` | **2026-11-18 00:00 UTC** |
| Window length | 1000 × 5m (adjacent early/late halves via `holdout_cut`) |
| Tip holdout | Latest 1000 × 5m bars excluded from window ends |
| Slip | 30 bps each way |
| Taker | KuCoin exchange rule (~10 bps); not paper’s optimistic 5 bps |

Phase A research may use tape with open **&lt; research_cut**. Blind holdout unlock uses open **≥ holdout_start** only after Candidate Spec freeze. A research PASS on pre-cut / current sliding windows is **not** paper unlock.

## Candidate Spec — trend-following (frozen on this branch)

| Lever | Value |
|---|---|
| Entry | Donchian: close **&gt;** max high of prior **20** bars; quote volume ≥ **2×** median of prior 12 |
| Exit | Trailing stop **ATR(14) × 3** (Wilder); initial stop = trail gap = 3×ATR in bps at entry; take-profit disabled |
| Filters | **No** `--prior-pays` (volume + Donchian is the filter) |
| Sleeve / median | Same major/alt/meme books; zero-fee / no-lot pairs left out |
| Env | `RESEARCH_ENTRY=donchian_20` `RESEARCH_TRAIL_ATR_MULT=3` (gate defaults these on this branch) |

Both labeled halves (`rsi` / `lift-candles` paths) use this **same** entry+exit for the gate table (research pattern). Labels keep v1 names for tooling compatibility.

## PASS bundle (paper unlock later — not today’s merge bar)

All required on the **same** frozen candidate and holdout pair:

1. **A** — all eight pooled sleeve medians **strictly &gt; 0** (early/late × earlier/later × two paths)  
2. **B** — density: each of the eight cells has **≥ 8** closed trades across median pairs; else **SPARSE** (not PASS)  
3. **C** — no paint: params frozen before holdout; holdout unused in selection  
4. **D** — costs as above  
5. **E** — operator unlock step; this script never sets `SPOT_ENTRIES`

**Kill:** first holdout **FAIL** or **SPARSE** ends this candidate for unlock.

## Gate tooling

```bash
python scripts/unseen_gate.py          # readiness
python scripts/unseen_gate.py --run    # two windows; Donchian+ATR trail; entries stay off
```

PASS of the script still does **not** enable buys.
