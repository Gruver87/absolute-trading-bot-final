"""Research-only ATR stop sizing for gate experiments.

RESEARCH_ATR_MULT=N → stop_bps = clamp(N * ATR(14) / entry * 10000, 100, 2000).
Off by default. Replay only; does not flip SPOT_ENTRIES.
"""

from __future__ import annotations

import os


def research_atr_mult() -> int | None:
    raw = os.environ.get("RESEARCH_ATR_MULT", "").strip()
    if not raw:
        return None
    if not raw.isdigit():
        raise ValueError(f"RESEARCH_ATR_MULT must be a positive int, got {raw!r}")
    mult = int(raw)
    if mult < 1 or mult > 20:
        raise ValueError(f"RESEARCH_ATR_MULT out of range 1..20: {mult}")
    return mult


def _whole(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int)


def atr_wilder(highs: list[int], lows: list[int], closes: list[int], period: int = 14) -> int | None:
    """Last Wilder ATR over `period` true ranges. None when the window is short."""
    if period < 1 or len(closes) < period + 1 or len(highs) != len(closes) or len(lows) != len(closes):
        return None
    if any(not _whole(x) or x <= 0 or x >= 10**24 for x in closes + highs + lows):
        return None
    trs: list[int] = []
    for i in range(1, len(closes)):
        high, low, prev = highs[i], lows[i], closes[i - 1]
        tr = max(high - low, abs(high - prev), abs(low - prev))
        trs.append(tr)
    if len(trs) < period:
        return None
    atr = sum(trs[:period]) // period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) // period
    return atr if atr > 0 else None


def atr_stop_bps(
    highs: list[int],
    lows: list[int],
    closes: list[int],
    entry: int,
    mult: int,
    *,
    period: int = 14,
    floor_bps: int = 100,
    cap_bps: int = 2000,
) -> int | None:
    """Stop distance in bps from mult×ATR/entry. None when ATR cannot be priced."""
    if not _whole(entry) or entry <= 0 or entry >= 10**24:
        return None
    if not _whole(mult) or mult < 1:
        return None
    atr = atr_wilder(highs, lows, closes, period)
    if atr is None:
        return None
    bps = atr * mult * 10_000 // entry
    if bps < floor_bps:
        return floor_bps
    if bps > cap_bps:
        return cap_bps
    return bps
