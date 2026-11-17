"""MEASUREMENT v2 window planners (pre-cut research vs post-cut holdout)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

BAR_MS = 300_000
LIMIT = 1000
# Accepted v2 cut (day after accept 2026-11-17).
RESEARCH_CUT_MS = int(datetime(2026, 11, 18, tzinfo=timezone.utc).timestamp() * 1000)
HOLDOUT_START_MS = RESEARCH_CUT_MS


@dataclass(frozen=True)
class GatePlan:
    now_ms: int
    early_end_ms: int
    late_end_ms: int
    early_start_ms: int
    ready: bool
    shortfall_bars: int
    phase: str
    boundary_ms: int


def plan_research_windows(now_ms: int) -> GatePlan:
    """Two adjacent 1000×5m windows for Phase A selection.

    All selected bars must have open < research_cut. Tip holdout uses
    boundary = min(research_cut, live now) so windows also satisfy replay's
    live tip-holdout check before the cut date arrives.
    """
    if not isinstance(now_ms, int) or isinstance(now_ms, bool) or now_ms <= 0:
        raise ValueError("now_ms must be a positive int")
    boundary = min(RESEARCH_CUT_MS, now_ms)
    late_end = boundary - LIMIT * BAR_MS
    early_end = late_end - LIMIT * BAR_MS
    early_start = early_end - LIMIT * BAR_MS
    # Refuse if late window would reach into post-cut tape.
    ready = (
        early_start > 0
        and late_end > early_end
        and late_end <= RESEARCH_CUT_MS
        and late_end <= now_ms - LIMIT * BAR_MS
    )
    return GatePlan(
        now_ms=now_ms,
        early_end_ms=early_end,
        late_end_ms=late_end,
        early_start_ms=early_start,
        ready=ready,
        shortfall_bars=0 if ready else 1,
        phase="research",
        boundary_ms=boundary,
    )


def plan_holdout_windows(now_ms: int) -> GatePlan:
    """Two adjacent windows with open ≥ holdout_start, tip holdout from live now."""
    if not isinstance(now_ms, int) or isinstance(now_ms, bool) or now_ms <= 0:
        raise ValueError("now_ms must be a positive int")
    late_end = now_ms - LIMIT * BAR_MS
    early_end = late_end - LIMIT * BAR_MS
    early_start = early_end - LIMIT * BAR_MS
    shortfall = 0
    if early_start < HOLDOUT_START_MS:
        shortfall = (HOLDOUT_START_MS - early_start + BAR_MS - 1) // BAR_MS
    return GatePlan(
        now_ms=now_ms,
        early_end_ms=early_end,
        late_end_ms=late_end,
        early_start_ms=early_start,
        ready=shortfall == 0 and early_end > 0 and late_end > early_end,
        shortfall_bars=int(shortfall),
        phase="holdout",
        boundary_ms=HOLDOUT_START_MS,
    )
