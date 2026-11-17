"""Research-only entries for MEASUREMENT v2 Phase A (pre-cut selection).

Env RESEARCH_ENTRY selects mode. Off by default. Does not flip SPOT_ENTRIES.
Replay only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from spotbot.liquidity import volume_ratio_bps
from spotbot.signals import Entry, below_lower_band, lower_band


MODES = frozenset(
    {
        "donchian_20",
        "donchian_55",
        "donchian_20_vol15",
        "bb_mr",
    }
)

_LOOKBACK = {
    "donchian_20": 20,
    "donchian_55": 55,
    "donchian_20_vol15": 20,
}

_VOL_BPS = {
    "donchian_20": 20_000,
    "donchian_55": 20_000,
    "donchian_20_vol15": 15_000,
}


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
    if closes[-1] <= level:
        return None
    vol_window = volumes if len(volumes) == len(closes) + 1 else list(volumes) + [1]
    if not _volume_confirms(vol_window, min_volume_bps):
        return None
    return Entry(symbol, 0, f"donchian_{lookback}")


def bb_mean_reversion_entry(symbol: str, closes: list[int], period: int = 20) -> Entry | None:
    """Prior close at/under lower BB; this close reclaims above band and prior close."""
    if not isinstance(symbol, str) or len(symbol) > 32 or not _prices_ok(closes):
        return None
    if len(closes) < period + 1:
        return None
    if closes[-1] <= closes[-2]:
        return None
    if not below_lower_band(closes[:-1], period):
        return None
    if below_lower_band(closes, period):
        return None
    return Entry(symbol, 0, "bb_mr_reclaim")


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
    del lows, rsi_buy
    if mode in _LOOKBACK:
        if highs is None or volumes is None:
            return None
        return donchian_entry(
            symbol,
            closes,
            highs,
            volumes,
            lookback=_LOOKBACK[mode],
            min_volume_bps=_VOL_BPS[mode],
        )
    if mode == "bb_mr":
        return bb_mean_reversion_entry(symbol, closes)
    return None


def research_fill_ok(
    mode: str,
    closes: list[int],
    fill: int,
    *,
    highs: list[int] | None = None,
    lookback: int | None = None,
) -> bool:
    if isinstance(fill, bool) or not isinstance(fill, int) or fill <= 0 or fill >= 10**24:
        return False
    if mode in _LOOKBACK:
        lb = lookback if lookback is not None else _LOOKBACK[mode]
        if highs is None:
            return False
        level = _max_high(highs, lb)
        if level is None:
            return False
        return fill > level
    if mode == "bb_mr":
        if not isinstance(closes, list) or len(closes) < 21:
            return False
        prior = closes[-2]
        band = lower_band(closes)
        if band is None or not _whole(prior) or prior <= 0:
            return False
        return fill > band and fill > prior
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
    del rsi_buy
    min_bars = 56 if mode == "donchian_55" else 21
    if not isinstance(bars, list) or len(bars) < min_bars:
        return None
    closes = [b[2] for b in bars]
    highs = [b[0] for b in bars]
    volumes = [b[3] for b in bars]
    found = research_entry(mode, symbol, closes, highs=highs, volumes=volumes)
    if found is None:
        return None
    return ResearchBarEntry(symbol, found.reason)
