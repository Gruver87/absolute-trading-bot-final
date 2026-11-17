"""Unit tests for v2 research/holdout window planners."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from v2_windows import (  # noqa: E402
    BAR_MS,
    HOLDOUT_START_MS,
    LIMIT,
    RESEARCH_CUT_MS,
    plan_holdout_windows,
    plan_research_windows,
)


def test_research_windows_before_cut():
    plan = plan_research_windows()
    assert plan.ready is True
    assert plan.phase == "research"
    assert plan.late_end_ms == RESEARCH_CUT_MS - LIMIT * BAR_MS
    assert plan.early_end_ms == plan.late_end_ms - LIMIT * BAR_MS
    assert plan.early_start_ms == plan.early_end_ms - LIMIT * BAR_MS
    # Entire span ends before cut (tip holdout).
    assert plan.late_end_ms < RESEARCH_CUT_MS


def test_holdout_not_ready_before_cut():
    # "Now" still before holdout_start → cannot fit post-cut windows.
    now = HOLDOUT_START_MS - BAR_MS
    plan = plan_holdout_windows(now)
    assert plan.ready is False
    assert plan.shortfall_bars > 0


def test_holdout_ready_after_full_span():
    now = HOLDOUT_START_MS + 3 * LIMIT * BAR_MS
    plan = plan_holdout_windows(now)
    assert plan.ready is True
    assert plan.early_start_ms >= HOLDOUT_START_MS


def test_cut_is_nov_18_utc():
    assert RESEARCH_CUT_MS == int(
        datetime(2026, 11, 18, tzinfo=timezone.utc).timestamp() * 1000
    )
    assert HOLDOUT_START_MS == RESEARCH_CUT_MS
