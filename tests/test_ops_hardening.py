"""Ops hardening: kill switch, gate journal, keyed smoke fail-closed (no network)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def test_kill_switch_file_blocks_entries_exits_still_run(tmp_path, monkeypatch) -> None:
    from spotbot.config import Config
    from spotbot.engine import run_cycle
    from spotbot.killswitch import kill_switch_active, stop_file_path
    from spotbot.rules import SymbolRule
    from spotbot.state import Book, Position, load_book, save_book

    monkeypatch.setattr("spotbot.engine.venue_quotes", lambda _symbol: {})
    data_dir = tmp_path
    stop = stop_file_path(data_dir)
    stop.write_text("halt entries\n", encoding="utf-8")
    assert kill_switch_active(data_dir) is True

    class _Book:
        def forget_rules(self) -> None:
            return None

        def symbol_rule(self, symbol: str) -> SymbolRule:
            return SymbolRule(symbol, True, "", 5, 1, 1, 0, "BTC")

        def book_top(self, _symbol: str) -> tuple[int, int]:
            return 90_000_000_000_000, 90_100_000_000_000

        def klines(self, _symbol: str) -> list[int]:
            raise AssertionError("entries must not scan while kill switch is on")

    cfg = Config(
        symbols=("BTCUSDT",),
        paper_cash_micro=1_000_000,
        interval_sec=60,
        max_positions=1,
        alloc_bps=10_000,
        min_notional_micro=1,
        rsi_buy=35,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        live=False,
        mode="rsi",
        taker_bps=5,
        daily_loss_bps=500,
        stop_cooldown_sec=0,
        symbol_lock=True,
        api_key="",
        api_secret="",
        entries=True,
    )
    # Book path under data_dir so ops_root resolves to data_dir (not paper/).
    path = data_dir / "off.json"
    save_book(
        path,
        Book(
            cash_micro=0,
            positions=[
                Position(
                    "BTCUSDT",
                    100_000_000_000_000,
                    100_000_000_000_000,
                    10_000_000,
                    100_000_000,
                    "test",
                )
            ],
            realized_micro=0,
        ),
    )
    report = run_cycle(cfg, _Book(), path)
    saved = load_book(path, 0)
    assert report.exits == 1
    assert report.entries == 0
    assert saved.positions == []


def test_kill_switch_env_blocks_without_file(tmp_path, monkeypatch) -> None:
    from spotbot.killswitch import kill_switch_active, kill_switch_reason

    monkeypatch.setenv("SPOT_KILL", "1")
    assert kill_switch_active(tmp_path) is True
    assert "SPOT_KILL=1" in kill_switch_reason(tmp_path)
    monkeypatch.setenv("SPOT_KILL", "0")
    assert kill_switch_active(tmp_path) is False


def test_kill_switch_bad_env_fails_closed(monkeypatch, tmp_path) -> None:
    from spotbot.killswitch import kill_switch_active

    monkeypatch.setenv("SPOT_KILL", "maybe")
    assert kill_switch_active(tmp_path) is True


def test_gate_journal_append_eight_medians(tmp_path) -> None:
    from spotbot.gate_journal import append_record, build_record, MEDIAN_LABELS

    early = {k: 0.01 for k in MEDIAN_LABELS}
    late = {k: 0.02 for k in MEDIAN_LABELS}
    row = build_record(
        kind="run",
        result="FAIL",
        tip="abc123",
        early=early,
        late=late,
        ready=True,
        now_ms=1_700_000_000_000,
    )
    path = tmp_path / "gate_history.jsonl"
    append_record(path, row)
    append_record(path, build_record(kind="readiness", result="READY", tip="abc123", ready=True))
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["tip_sha"] == "abc123"
    assert first["result"] == "FAIL"
    assert first["early_earlier_rsi"] == 0.01
    assert first["late_later_lift_candles"] == 0.02
    assert "at" in first
    second = json.loads(lines[1])
    assert second["kind"] == "readiness"
    assert second["early_earlier_rsi"] is None


def test_unseen_gate_journals_readiness(tmp_path, monkeypatch) -> None:
    import unseen_gate

    monkeypatch.setattr(unseen_gate, "ROOT", tmp_path)
    # Force a ready plan without network.
    ready_now = unseen_gate.UNSEEN_AFTER_MS + 3 * unseen_gate.LIMIT * unseen_gate.BAR_MS
    code = unseen_gate.main(["--now-ms", str(ready_now)])
    assert code == 0
    journal = tmp_path / "data" / "gate_history.jsonl"
    assert journal.is_file()
    row = json.loads(journal.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert row["kind"] == "readiness"
    assert row["result"] == "READY"
    assert row["ready"] is True


def test_unseen_gate_no_journal_flag(tmp_path, monkeypatch) -> None:
    import unseen_gate

    monkeypatch.setattr(unseen_gate, "ROOT", tmp_path)
    ready_now = unseen_gate.UNSEEN_AFTER_MS + 3 * unseen_gate.LIMIT * unseen_gate.BAR_MS
    code = unseen_gate.main(["--now-ms", str(ready_now), "--no-journal"])
    assert code == 0
    assert not (tmp_path / "data" / "gate_history.jsonl").exists()


def test_keyed_smoke_refuses_spot_live(monkeypatch) -> None:
    import kucoin_keyed_smoke

    monkeypatch.setenv("SPOT_LIVE", "1")
    monkeypatch.setenv("KUCOIN_API_KEY", "k")
    monkeypatch.setenv("KUCOIN_API_SECRET", "s")
    monkeypatch.setenv("KUCOIN_API_PASSPHRASE", "p")
    assert kucoin_keyed_smoke.main([]) == 2


def test_keyed_smoke_refuses_live_flag(monkeypatch) -> None:
    import kucoin_keyed_smoke

    monkeypatch.setenv("SPOT_LIVE", "0")
    assert kucoin_keyed_smoke.main(["--live"]) == 2


def test_keyed_smoke_refuses_missing_keys(monkeypatch) -> None:
    import kucoin_keyed_smoke

    monkeypatch.setenv("SPOT_LIVE", "0")
    monkeypatch.delenv("KUCOIN_API_KEY", raising=False)
    monkeypatch.delenv("KUCOIN_API_SECRET", raising=False)
    monkeypatch.delenv("KUCOIN_API_PASSPHRASE", raising=False)
    # Avoid loading a real .env from the checkout if present.
    monkeypatch.setattr(kucoin_keyed_smoke, "_load_env", lambda: None)
    assert kucoin_keyed_smoke.main([]) == 2
