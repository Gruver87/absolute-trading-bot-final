"""Unit tests for Donchian + ATR trail research hooks (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from spotbot.research_atr import atr_stop_bps, atr_wilder, research_trail_atr_mult
from spotbot.research_entry import donchian_entry, research_mode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from unseen_gate import density_ok, parse_trade_counts  # noqa: E402


def test_research_mode_donchian(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RESEARCH_ENTRY", raising=False)
    assert research_mode() is None
    monkeypatch.setenv("RESEARCH_ENTRY", "donchian_20")
    assert research_mode() == "donchian_20"
    monkeypatch.setenv("RESEARCH_ENTRY", "breakout")
    with pytest.raises(ValueError):
        research_mode()


def test_donchian_breaks_prior_high_with_volume() -> None:
    highs = [100] * 20 + [105]
    closes = [99] * 20 + [101]
    vols = [1000] * 20 + [5000]
    found = donchian_entry("BTCUSDT", closes, highs, vols, lookback=20)
    assert found is not None
    assert found.reason == "donchian_20"
    assert donchian_entry("BTCUSDT", closes[:-1] + [100], highs, vols) is None


def test_atr_trail_mult_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RESEARCH_TRAIL_ATR_MULT", raising=False)
    assert research_trail_atr_mult() is None
    monkeypatch.setenv("RESEARCH_TRAIL_ATR_MULT", "3")
    assert research_trail_atr_mult() == 3


def test_atr_stop_bps_positive() -> None:
    closes = list(range(1000, 1030))
    highs = [c + 10 for c in closes]
    lows = [c - 10 for c in closes]
    atr = atr_wilder(highs, lows, closes, 14)
    assert atr is not None and atr > 0
    bps = atr_stop_bps(highs, lows, closes, entry=closes[-1], mult=3)
    assert bps is not None and 100 <= bps <= 2000


def test_parse_trade_counts_and_density() -> None:
    text = "\n".join(
        [
            "rule=rsi:earlier symbol=BTCUSDT bars=400 trades=3 wins=1 net=0.1 fees=0.0 open_at_end=False taker_bps=10",
            "rule=rsi:earlier symbol=ETHUSDT bars=400 trades=5 wins=2 net=0.1 fees=0.0 open_at_end=False taker_bps=10",
            "rule=lift-candles:earlier symbol=BTCUSDT bars=400 trades=8 wins=1 net=0.1 fees=0.0 open_at_end=False taker_bps=10",
            "rule=rsi:later symbol=BTCUSDT bars=600 trades=2 wins=0 net=-1.0 fees=0.0 open_at_end=False taker_bps=10",
            "rule=lift-candles:later symbol=BTCUSDT bars=600 trades=9 wins=1 net=0.1 fees=0.0 open_at_end=False taker_bps=10",
        ]
    )
    got = parse_trade_counts(text)
    assert got["earlier rsi"] == 8
    assert got["earlier lift-candles"] == 8
    assert got["later rsi"] == 2
    assert got["later lift-candles"] == 9
    early = {"earlier rsi": 8, "earlier lift-candles": 8, "later rsi": 8, "later lift-candles": 8}
    late = dict(early)
    assert density_ok(early, late) is True
    late_bad = dict(late)
    late_bad["later rsi"] = 2
    assert density_ok(early, late_bad) is False
