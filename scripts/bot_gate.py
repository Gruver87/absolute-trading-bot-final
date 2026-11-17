#!/usr/bin/env python3
"""Static honesty gate for absolute-trading-bot-final.

Exit 0 only when required status/skills needles are present.
Does not claim edge, unlock entries, or run exchange orders.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAILURES: list[str] = []


def need(path: Path, needle: str, label: str) -> None:
    if not path.is_file():
        FAILURES.append(f"missing_file:{label}:{path.name}")
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    if needle not in text:
        FAILURES.append(f"missing_needle:{label}:{needle[:64]}")


def main() -> int:
    need(ROOT / "docs" / "PROTOCOL_STATUS.md", "SPOT_ENTRIES", "protocol_entries")
    need(ROOT / "docs" / "PROTOCOL_STATUS.md", "stopped", "protocol_stopped")
    need(ROOT / "docs" / "PROTOCOL_STATUS.md", "MEASUREMENT", "protocol_measurement")
    need(ROOT / "docs" / "PROTOCOL_STATUS.md", "AGENT_SKILLS", "protocol_agent_skills")
    need(ROOT / "docs" / "MEASUREMENT.md", "не включаются", "measurement_no_entries")
    need(ROOT / "docs" / "AGENT_SKILLS.md", "dup-agent-skills", "agent_skills_doc")
    need(ROOT / "docs" / "AGENT_SKILLS.md", "bot-holdout-wait", "agent_skills_bot_freeze")
    need(ROOT / "docs" / "AGENT_SKILLS.md", "SPOT_ENTRIES", "agent_skills_entries_off")
    need(ROOT / "scripts" / "link_agent_skills.ps1", "link_agent_skills", "link_script")
    need(ROOT / "scripts" / "test_all.ps1", "bot_gate", "test_all_script")
    need(ROOT / "README.md", "PROTOCOL_STATUS", "readme_protocol")
    need(ROOT / "README.md", "AGENT_SKILLS", "readme_agent_skills")
    need(ROOT / "README.md", "SPOT_ENTRIES", "readme_entries")
    need(ROOT / "docs" / "REFUSALS.md", "кассу", "refusals")

    if FAILURES:
        print("bot_gate FAIL")
        for f in FAILURES[:32]:
            print(" ", f)
        return 1
    print("bot_gate PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
