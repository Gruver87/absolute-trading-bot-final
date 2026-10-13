"""Local ops journal. The console reads these files; it does not trade."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path

LOG = logging.getLogger("spotbot.journal")
_LOCK = threading.Lock()
_MAX_EVENTS = 200


def ops_root(book_path: Path) -> Path:
    """Quotes and events stay next to ops.log, not inside the paper or live ledger folder."""
    if book_path.parent.name in ("paper", "live"):
        return book_path.parent.parent
    return book_path.parent


def note_event(data_dir: Path, **fields: object) -> None:
    """Append one trade or skip. A journal failure does not abort the cycle."""
    row = {"at": _now(), **fields}
    try:
        with _LOCK:
            data_dir.mkdir(parents=True, exist_ok=True)
            path = data_dir / "ops_events.jsonl"
            prior: list[str] = []
            if path.exists():
                prior = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            prior.append(json.dumps(row, ensure_ascii=False))
            _write(path, "\n".join(prior[-_MAX_EVENTS:]) + "\n")
    except (OSError, UnicodeError) as exc:
        LOG.warning("ops event was not written: %s", exc)


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
    try:
        with _LOCK:
            data_dir.mkdir(parents=True, exist_ok=True)
            path = data_dir / "ops_quotes.json"
            raw: dict[str, object] = {}
            if path.exists():
                try:
                    loaded = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    loaded = None
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
            _write(path, json.dumps(raw, indent=2))
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        LOG.warning("ops quote was not written: %s", exc)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _write(path: Path, text: str) -> None:
    from spotbot.state import write_atomic

    write_atomic(path, text)


def note_heartbeat(data_dir: Path, book: str) -> None:
    """One timestamp for the ops page. Age is how long since the last finished cycle."""
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        payload = {"at": _now(), "book": book}
        _write(data_dir / "ops_heartbeat.json", json.dumps(payload))
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        LOG.warning("ops heartbeat was not written: %s", exc)
