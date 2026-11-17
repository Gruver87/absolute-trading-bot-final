# Protocol status (pointer)

**As of 2026-11-17** (main tip after PR #4: `dfc3e6f`):

- **MEASUREMENT v1** is **stopped** (no-edge). On research branches archived at `docs/archive/MEASUREMENT_v1.md`.
- **MEASUREMENT v2** accepted 2026-11-17. Active research branch: **`research/v2-holdout`** (`docs/MEASUREMENT_v2.md`, `docs/CANDIDATE_SPEC_v2.md`).
- **Frozen candidate A3:** Donchian-55 + vol≥2×; ATR×3 trail; `holdout_start` = 2026-11-18 00:00 UTC.
- Phase A (pre-cut): all five candidates FAIL; A3 least-bad. Phase C holdout: run `scripts/v2_holdout.py` when post-cut tape is READY.
- Do **not** merge strategy to `main` until HOLD_PASS. `SPOT_ENTRIES` stays off.
- Project Context: stop + accepted protocol + candidate-spec-v2 + v2-research-holdout report.
