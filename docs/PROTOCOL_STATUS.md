# Protocol status (pointer)

**As of 2026-11-17** (repo tip lineage through ops hardening / `33f3d6d`):

- The frozen **MEASUREMENT v1** strategy is **stopped** — accepted **no-edge** on the current tape. New buys stay off.
- `docs/MEASUREMENT.md` remains the **historical** v1 record. It is **not** the active unlock path and must **not** be silently rewritten.
- Decision record and the **draft** next protocol live in **Project Context** (Cursor Project store), not as a replacement of this file’s rules:
  - Strategy stop: Project Context → `docs/strategy-stop-2026-11-17.md`
  - Protocol v2 draft (accept/reject): Project Context → `docs/measurement-protocol-v2-draft.md`
- `SPOT_ENTRIES` stays off. Do **not** enable entries under the old eight-median gate.
- KuCoin client, CI, kill switch, and gate journal remain the maintained base.

Until an accepted v2 is written into the repo by an explicit operator decision, treat this stub as the in-tree status pointer only.
