# Agent Skills companion

**Product:** [dup-agent-skills](https://github.com/Gruver87/dup-agent-skills) · Not financial advice.

Cursor skills that matter for this bot:

| Skill | Policy |
|-------|--------|
| `bot-holdout-wait` | MEASUREMENT v1 stopped; no silent retune; `SPOT_ENTRIES` off |
| `secrets-hygiene` | Never print/commit KuCoin keys |
| `evidence-honesty` | No invented PASS / expectancy |
| `no-futures-auto` | This bot is spot-only; futures stay refused |
| `l1-boundary` | Do not mix DUP L1 mesh claims into bot status |

## Link into this checkout

```powershell
.\scripts\link_agent_skills.ps1
```

Expects sibling `..\dup-agent-skills` (or Desktop path). Copies into gitignored `.agents/skills/`.

## Status pointer

In-tree truth: [`PROTOCOL_STATUS.md`](PROTOCOL_STATUS.md). Historical v1 windows: [`MEASUREMENT.md`](MEASUREMENT.md) — do not silently rewrite.

## Honesty gate

```powershell
python scripts\bot_gate.py
```

CI runs the same gate. Exit 0 only when PROTOCOL_STATUS / AGENT_SKILLS needles stay present — not an edge claim.
