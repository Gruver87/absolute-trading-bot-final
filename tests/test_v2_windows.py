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


def test_research_before_cut_uses_live_tip():
    # One day before cut: boundary = now; windows end before cut automatically.
    now = RESEARCH_CUT_MS - 24 * 60 * 60 * 1000
    plan = plan_research_windows(now)
    assert plan.ready is True
    assert plan.boundary_ms == now
    assert plan.late_end_ms == now - LIMIT * BAR_MS
    assert plan.late_end_ms < RESEARCH_CUT_MS
    assert plan.early_start_ms == plan.early_end_ms - LIMIT * BAR_MS


def test_research_after_cut_freezes_at_cut():
    now = RESEARCH_CUT_MS + 10 * LIMIT * BAR_MS
    plan = plan_research_windows(now)
    assert plan.ready is True
    assert plan.boundary_ms == RESEARCH_CUT_MS
    assert plan.late_end_ms == RESEARCH_CUT_MS - LIMIT * BAR_MS
    assert plan.late_end_ms <= now - LIMIT * BAR_MS


def test_holdout_not_ready_before_cut():
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
