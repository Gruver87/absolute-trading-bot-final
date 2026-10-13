"""Local ops journal. The console reads these files; it does not trade."""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

_LOCK = threading.Lock()
_MAX_EVENTS = 200


def ops_root(book_path: Path) -> Path:
    """Quotes and events stay next to ops.log, not inside the paper or live ledger folder."""
    if book_path.parent.name in ("paper", "live"):
        return book_path.parent.parent
    return book_path.parent


def note_event(data_dir: Path, **fields: object) -> None:
    """Append one trade or skip. Values are already public strings or ints."""
    row = {"at": _now(), **fields}
    with _LOCK:
        data_dir.mkdir(parents=True, exist_ok=True)
        path = data_dir / "ops_events.jsonl"
        prior: list[str] = []
        if path.exists():
            prior = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        prior.append(json.dumps(row, ensure_ascii=False))
        path.write_text("\n".join(prior[-_MAX_EVENTS:]) + "\n", encoding="utf-8")


def note_quote(
    data_dir: Path,
    symbol: str,
    mexc: str,
    binance: str,
    bybit: str,
    okx: str,
    lag_bps: int | None,
    width_bps: int | None,
) -> None:
    with _LOCK:
        data_dir.mkdir(parents=True, exist_ok=True)
        path = data_dir / "ops_quotes.json"
        raw: dict[str, object] = {}
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                raw = loaded
        raw[symbol] = {
            "at": _now(),
            "mexc": mexc,
            "binance": binance,
            "bybit": bybit,
            "okx": okx,
            "lag_bps": lag_bps,
            "width_bps": width_bps,
        }
        path.write_text(json.dumps(raw, indent=2), encoding="utf-8")


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def note_heartbeat(data_dir: Path, book: str) -> None:
    """One timestamp for the ops page. Age is how long since the last finished cycle."""
    data_dir.mkdir(parents=True, exist_ok=True)
    payload = {"at": _now(), "book": book}
    (data_dir / "ops_heartbeat.json").write_text(json.dumps(payload), encoding="utf-8")
