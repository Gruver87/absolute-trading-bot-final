"""Research-only entry variants for gate experiments.

Selected with RESEARCH_ENTRY. Off by default — live/engine paths ignore this.
Does not flip SPOT_ENTRIES. Replay only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from spotbot.liquidity import close_position_bps, volume_ratio_bps
from spotbot.signals import Entry, below_lower_band, lower_band, rsi


# breakout: close breaks max high of last N bars + volume >= 2x median of prior 12
# bb_mr: prior close at/under lower BB, this close reclaims above band and prior close
# breakout_10: same as breakout with lookback 10
# confluence: RSI<35 + BB reclaim + volume >= 1.5x (drop MACD block; tighter volume)
# vol_climax_fade: prior bar volume climax + close in lower third; this bar closes up
MODES = frozenset(
    {
        "breakout",
        "bb_mr",
        "breakout_10",
        "confluence",
        "vol_climax_fade",
    }
)


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


def breakout_entry(
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
    # Align volume list with closes: volume_ratio_bps expects forming bar as last (+1).
    vol_window = volumes if len(volumes) == len(closes) + 1 else volumes + [1]
    if not _volume_confirms(vol_window, min_volume_bps):
        return None
    return Entry(symbol, 0, f"breakout_{lookback}")


def bb_mean_reversion_entry(symbol: str, closes: list[int], period: int = 20) -> Entry | None:
    """Prior close at/under lower BB(period, 2σ); this close reclaims above band and prior.

    Testable rule (no RSI, no MACD):
    - prices[-2] <= lower_band(prices[:-1])
    - prices[-1] > lower_band(prices) and prices[-1] > prices[-2]
    """
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


def confluence_entry(
    symbol: str,
    closes: list[int],
    volumes: list[int],
    *,
    rsi_buy: int = 35,
    min_volume_bps: int = 15_000,
) -> Entry | None:
    """RSI oversold + BB reclaim + volume confirmation. No MACD sell block."""
    if not isinstance(symbol, str) or len(symbol) > 32 or not _prices_ok(closes):
        return None
    if isinstance(rsi_buy, bool) or not isinstance(rsi_buy, int) or rsi_buy < 1 or rsi_buy > 99:
        return None
    if not _vol_ok(volumes) or len(closes) < 21:
        return None
    value = rsi(closes[:-1])
    if value is None or value >= rsi_buy:
        return None
    if closes[-1] <= closes[-2]:
        return None
    if not below_lower_band(closes[:-1]) or below_lower_band(closes):
        return None
    vol_window = volumes if len(volumes) == len(closes) + 1 else volumes + [1]
    if not _volume_confirms(vol_window, min_volume_bps):
        return None
    return Entry(symbol, value, "rsi+bb+vol")


def vol_climax_fade_entry(
    symbol: str,
    closes: list[int],
    highs: list[int],
    lows: list[int],
    volumes: list[int],
    *,
    min_volume_bps: int = 30_000,
    max_close_pos_bps: int = 3_500,
) -> Entry | None:
    """Fade a volume climax dump: prior bar high volume + close in lower third; this bar green reclaim.

    Prior bar (index -2): volume >= 3x median of 12 before it, close_pos <= 35%.
    Signal bar: close > prior close (and preferably above prior mid).
    """
    if not isinstance(symbol, str) or len(symbol) > 32:
        return None
    if not _prices_ok(closes) or not _prices_ok(highs) or not _prices_ok(lows):
        return None
    if not _vol_ok(volumes) or len(closes) < 16 or len(highs) != len(closes) or len(lows) != len(closes):
        return None
    # volume_ratio_bps uses volumes[-2] as last closed vs median of [-14:-2].
    # For the *prior* bar relative to signal, feed volumes ending at the signal bar
    # so [-2] is the dump bar.
    vol_window = volumes if len(volumes) == len(closes) + 1 else list(volumes) + [1]
    if len(vol_window) < 15:
        return None
    # Evaluate climax on bar before signal: truncate one closed bar.
    prior_vols = vol_window[:-1]
    ratio = volume_ratio_bps(prior_vols)
    if ratio is None or ratio < min_volume_bps:
        return None
    pos = close_position_bps(highs[-2], lows[-2], closes[-2])
    if pos is None or pos > max_close_pos_bps:
        return None
    if closes[-1] <= closes[-2]:
        return None
    return Entry(symbol, ratio // 100, "vol_climax_fade")


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
    if mode == "breakout":
        if highs is None or volumes is None:
            return None
        return breakout_entry(symbol, closes, highs, volumes, lookback=20)
    if mode == "breakout_10":
        if highs is None or volumes is None:
            return None
        return breakout_entry(symbol, closes, highs, volumes, lookback=10)
    if mode == "bb_mr":
        return bb_mean_reversion_entry(symbol, closes)
    if mode == "confluence":
        if volumes is None:
            return None
        return confluence_entry(symbol, closes, volumes, rsi_buy=rsi_buy)
    if mode == "vol_climax_fade":
        if highs is None or lows is None or volumes is None:
            return None
        return vol_climax_fade_entry(symbol, closes, highs, lows, volumes)
    return None


def research_fill_ok(
    mode: str,
    closes: list[int],
    fill: int,
    *,
    highs: list[int] | None = None,
    lookback: int | None = None,
) -> bool:
    """Next-open fill still matches the research entry (no fall-through)."""
    if isinstance(fill, bool) or not isinstance(fill, int) or fill <= 0 or fill >= 10**24:
        return False
    if mode in ("bb_mr", "confluence"):
        # Same as reclaim_still: ask still above band and prior close.
        if not isinstance(closes, list) or len(closes) < 21:
            return False
        prior = closes[-2]
        band = lower_band(closes)
        if band is None or not _whole(prior) or prior <= 0:
            return False
        return fill > band and fill > prior
    if mode in ("breakout", "breakout_10"):
        lb = lookback if lookback is not None else (10 if mode == "breakout_10" else 20)
        if highs is None:
            return False
        level = _max_high(highs, lb)
        if level is None:
            return False
        return fill > level
    if mode == "vol_climax_fade":
        if not isinstance(closes, list) or len(closes) < 2:
            return False
        return fill > closes[-2]
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
    """Bar-path (lift half) research entry. bars = (high, low, close, quote_vol)."""
    if not isinstance(bars, list) or len(bars) < 16:
        return None
    closes = [b[2] for b in bars]
    highs = [b[0] for b in bars]
    lows = [b[1] for b in bars]
    volumes = [b[3] for b in bars]
    found = research_entry(
        mode,
        symbol,
        closes,
        highs=highs,
        lows=lows,
        volumes=volumes,
        rsi_buy=rsi_buy,
    )
    if found is None:
        return None
    return ResearchBarEntry(symbol, found.reason)
