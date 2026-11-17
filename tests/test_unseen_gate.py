"""Unit tests for unseen-tape gate planner (no network, no bot changes)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from unseen_gate import (  # noqa: E402
    LIMIT,
    UNSEEN_AFTER_MS,
    BAR_MS,
    eight_strictly_positive,
    limit_for_interval,
    parse_pooled_medians,
    plan_windows,
)


def test_plan_not_ready_when_tape_short():
    # Right after unseen cut: cannot fit 3000 bars.
    now = UNSEEN_AFTER_MS + 500 * BAR_MS
    plan = plan_windows(now)
    assert plan.ready is False
    assert plan.shortfall_bars > 0


def test_plan_ready_after_full_span():
    # early_start >= UNSEEN_AFTER when now covers 3 * LIMIT bars after cut.
    now = UNSEEN_AFTER_MS + 3 * LIMIT * BAR_MS
    plan = plan_windows(now)
    assert plan.ready is True
    assert plan.shortfall_bars == 0
    assert plan.early_start_ms >= UNSEEN_AFTER_MS
    assert plan.late_end_ms == now - LIMIT * BAR_MS
    assert plan.early_end_ms == plan.late_end_ms - LIMIT * BAR_MS


def test_late_end_leaves_tip_holdout():
    now = UNSEEN_AFTER_MS + 3 * LIMIT * BAR_MS + 17 * BAR_MS
    plan = plan_windows(now)
    assert plan.late_end_ms <= now - LIMIT * BAR_MS


def test_parse_pooled_ignores_sleeve_lines():
    text = "\n".join(
        [
            "median earlier rsi pairs=10 net=1.250000",
            "median earlier rsi major pairs=3 net=9.000000",
            "median earlier lift-candles pairs=10 net=0.010000",
            "median later rsi pairs=10 net=-0.500000",
            "median later lift-candles pairs=10 net=2.000000",
        ]
    )
    got = parse_pooled_medians(text)
    assert got["earlier rsi"] == 1.25
    assert got["earlier lift-candles"] == 0.01
    assert got["later rsi"] == -0.5
    assert got["later lift-candles"] == 2.0
    assert "major" not in "".join(got)


def test_eight_positive_requires_all():
    labels = (
        "earlier rsi",
        "earlier lift-candles",
        "later rsi",
        "later lift-candles",
    )
    good = {k: 0.01 for k in labels}
    bad = dict(good)
    bad["later rsi"] = 0.0
    assert eight_strictly_positive(good, good) is True
    assert eight_strictly_positive(good, bad) is False
    assert eight_strictly_positive(good, {}) is False


def test_unseen_after_is_oct_15_utc():
    dt = datetime.fromtimestamp(UNSEEN_AFTER_MS / 1000, tz=timezone.utc)
    assert dt.year == 2026 and dt.month == 10 and dt.day == 15
    assert dt.hour == 0 and dt.minute == 0


def test_higher_tf_limits_map_calendar():
    # 1000×5m = 5000min → 15m ceil 334; 1h ceil 84 → floored to 160 for split.
    assert limit_for_interval("5m") == 1000
    assert limit_for_interval("15m") == 334
    assert limit_for_interval("1h") == 160


def test_plan_windows_15m_ready_shape():
    now = UNSEEN_AFTER_MS + 3 * 334 * 900_000
    plan = plan_windows(now, "15m")
    assert plan.ready is True
    assert plan.limit == 334
    assert plan.bar_ms == 900_000
    assert plan.late_end_ms == now - 334 * 900_000
