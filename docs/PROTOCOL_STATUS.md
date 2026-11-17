# Protocol status (pointer)

**As of 2026-11-17** (main tip after PR #4: `dfc3e6f`):

- **MEASUREMENT v1** is **stopped** (no-edge). Historical text on `main` remains `docs/MEASUREMENT.md` until a future docs-only sync; on branch `research/trend-following` it is archived at `docs/archive/MEASUREMENT_v1.md`.
- **MEASUREMENT v2** was **accepted** 2026-11-17. In-repo copy + Candidate Spec live on **`research/trend-following` only** (`docs/MEASUREMENT_v2.md`). Do **not** merge strategy to `main` until a gate **PASS**.
- Project Context:
  - Stop: `docs/strategy-stop-2026-11-17.md`
  - Accepted protocol: `docs/measurement-protocol-v2-draft.md`
- Candidate on branch: Donchian-20 + volume entry; ATR×3 trailing exit (`docs/RESEARCH_TREND_FOLLOWING.md`).
- `SPOT_ENTRIES` stays off. KuCoin client, CI, kill switch, and gate journal remain the maintained base.
