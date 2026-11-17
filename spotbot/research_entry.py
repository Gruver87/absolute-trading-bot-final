"""Research-only entry: Donchian breakout + volume (trend-following candidate).

Selected with RESEARCH_ENTRY=donchian_20. Off by default on other branches.
Does not flip SPOT_ENTRIES. Replay only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from spotbot.liquidity import volume_ratio_bps
from spotbot.signals import Entry


MODES = frozenset({"donchian_20"})


def research_mode() -> str | None:
    """Return active RESEARCH_ENTRY mode, or None when baseline rules apply."""
    raw = os.environ.get("RESEARCH_ENTRY", "").strip().lower()
    if not raw:
        return None
    if raw not in MODES:
        raise ValueError(f"RESEARCH_ENTRY must be one of {sorted(MODES)}, got {raw!r}")
    return raw


def _whole(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int)


def _prices_ok(prices: list[int]) -> bool:
    return isinstance(prices, list) and all(
        _whole(p) and 0 < p < 10**24 for p in prices
    )


def _vol_ok(volumes: list[int] | None) -> bool:
    return volumes is not None and isinstance(volumes, list) and all(
        _whole(v) and 0 < v < 10**24 for v in volumes
    )


def _max_high(highs: list[int], lookback: int) -> int | None:
    """Max of the lookback highs *before* the signal bar (exclude last)."""
    if not isinstance(highs, list) or lookback < 1 or len(highs) < lookback + 1:
        return None
    window = highs[-(lookback + 1) : -1]
    if any(not _whole(h) or h <= 0 or h >= 10**24 for h in window):
        return None
    return max(window)


def _volume_confirms(volumes: list[int], min_ratio_bps: int) -> bool:
    """Last closed bar quote volume vs median of the 12 before it."""
    ratio = volume_ratio_bps(volumes)
    if ratio is None:
        return False
    return ratio >= min_ratio_bps


def donchian_entry(
    symbol: str,
    closes: list[int],
    highs: list[int],
    volumes: list[int],
    *,
    lookback: int = 20,
    min_volume_bps: int = 20_000,
) -> Entry | None:
    """Long when close breaks the prior lookback max high with volume confirmation."""
    if not isinstance(symbol, str) or len(symbol) > 32:
        return None
    if not _prices_ok(closes) or not _prices_ok(highs) or not _vol_ok(volumes):
        return None
    if len(closes) != len(highs) or len(closes) < lookback + 1 or len(volumes) < 14:
        return None
    level = _max_high(highs, lookback)
    if level is None:
        return None
    close = closes[-1]
    if close <= level:
        return None
    # volume_ratio_bps expects forming bar as last (+1) so [-2] is the signal bar.
    vol_window = volumes if len(volumes) == len(closes) + 1 else list(volumes) + [1]
    if not _volume_confirms(vol_window, min_volume_bps):
        return None
    return Entry(symbol, 0, f"donchian_{lookback}")


def research_entry(
    mode: str,
    symbol: str,
    closes: list[int],
    *,
    highs: list[int] | None = None,
    lows: list[int] | None = None,
    volumes: list[int] | None = None,
    rsi_buy: int = 35,
) -> Entry | None:
    """Dispatch RESEARCH_ENTRY mode. Returns Entry or None."""
    del lows, rsi_buy  # unused for donchian; kept for call-site parity
    if mode == "donchian_20":
        if highs is None or volumes is None:
            return None
        return donchian_entry(symbol, closes, highs, volumes, lookback=20)
    return None


def research_fill_ok(
    mode: str,
    closes: list[int],
    fill: int,
    *,
    highs: list[int] | None = None,
    lookback: int | None = None,
) -> bool:
    """Next-open fill still above the broken Donchian level."""
    del closes
    if isinstance(fill, bool) or not isinstance(fill, int) or fill <= 0 or fill >= 10**24:
        return False
    if mode == "donchian_20":
        lb = lookback if lookback is not None else 20
        if highs is None:
            return False
        level = _max_high(highs, lb)
        if level is None:
            return False
        return fill > level
    return False


@dataclass(frozen=True)
class ResearchBarEntry:
    symbol: str
    reason: str


def research_entry_from_bars(
    mode: str,
    symbol: str,
    bars: list[tuple[int, int, int, int]],
    *,
    rsi_buy: int = 35,
) -> ResearchBarEntry | None:
    """Bar-path research entry. bars = (high, low, close, quote_vol)."""
    del rsi_buy
    if not isinstance(bars, list) or len(bars) < 21:
        return None
    closes = [b[2] for b in bars]
    highs = [b[0] for b in bars]
    volumes = [b[3] for b in bars]
    found = research_entry(mode, symbol, closes, highs=highs, volumes=volumes)
    if found is None:
        return None
    return ResearchBarEntry(symbol, found.reason)
