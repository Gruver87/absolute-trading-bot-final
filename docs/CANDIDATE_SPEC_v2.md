# Candidate Spec v2 — freeze (Phase B)

Mirror of Project Context `docs/candidate-spec-v2.md`. Branch: `research/v2-holdout` only.

**Frozen:** 2026-11-17  
**Candidate:** **A3** — `RESEARCH_ENTRY=donchian_55` + `RESEARCH_TRAIL_ATR_MULT=3`  
**Entry:** Donchian-55 high break + volume ≥ 2× median(12)  
**Exit:** ATR(14)×3 trailing stop; take disabled  
**Filters:** no `--prior-pays`  
**Costs:** slip 30 bps ×2; KuCoin taker  
**holdout_start / research_cut:** 2026-11-18 00:00 UTC  

```bash
export RESEARCH_ENTRY=donchian_55
export RESEARCH_TRAIL_ATR_MULT=3
python3 scripts/v2_holdout.py
```

Phase A: all candidates FAIL; A3 least-bad (median sum −21.97, density OK). Blind holdout required. `SPOT_ENTRIES` off. Do not merge to main until HOLD_PASS.
