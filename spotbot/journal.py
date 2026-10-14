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
    clean: dict[str, object] = {}
    for key, value in fields.items():
        if not isinstance(key, str) or len(key) > 32:
            continue
        if isinstance(value, str):
            clean[key] = value if len(value) <= 180 else value[:180]
        elif isinstance(value, bool) or value is None:
            clean[key] = value
        elif isinstance(value, int) and -10**24 < value < 10**24:
            clean[key] = value
    row = {"at": _now(), **clean}
    try:
        with _LOCK:
            data_dir.mkdir(parents=True, exist_ok=True)
            path = data_dir / "ops_events.jsonl"
            prior = _event_lines(path) if path.exists() else []
            prior.append(json.dumps(row, ensure_ascii=False))
            _write(path, "\n".join(prior[-_MAX_EVENTS:]) + "\n")
    except (OSError, UnicodeError, TypeError, ValueError, MemoryError) as exc:
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
    if not isinstance(symbol, str) or not symbol or len(symbol) > 32:
        return
    venues = (_venue_text(mexc), _venue_text(binance), _venue_text(bybit), _venue_text(okx))
    lag = _small_bps(lag_bps)
    width = _small_bps(width_bps)
    try:
        with _LOCK:
            data_dir.mkdir(parents=True, exist_ok=True)
            path = data_dir / "ops_quotes.json"
            raw: dict[str, object] = {}
            if path.exists() and path.stat().st_size <= 1_000_000:
                try:
                    loaded = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError, MemoryError):
                    loaded = None
                if isinstance(loaded, dict) and len(loaded) <= 32:
                    raw = loaded
            raw[symbol] = {
                "at": _now(),
                "mexc": venues[0],
                "binance": venues[1],
                "bybit": venues[2],
                "okx": venues[3],
                "lag_bps": lag,
                "width_bps": width,
            }
            _write(path, json.dumps(raw, indent=2))
    except (OSError, UnicodeError, TypeError, ValueError, MemoryError) as exc:
        LOG.warning("ops quote was not written: %s", exc)


def _venue_text(value: object) -> str:
    """A shown price is short text. A long or non-text value is not a quote."""
    if not isinstance(value, str) or len(value) > 80:
        return "unreadable"
    return value


def _small_bps(value: object) -> int | None:
    """A width or a lag is a small integer. A fraction or a ceiling is omitted."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= -1_000_000_000 or value >= 1_000_000_000:
        return None
    return value


def _event_lines(path: Path) -> list[str]:
    """Recent event lines. A planted huge file is not loaded whole into the cycle."""
    size = path.stat().st_size
    if size > 262_144:
        with path.open("rb") as handle:
            handle.seek(size - 262_144)
            text = handle.read().decode("utf-8", errors="replace")
        text = text.split("\n", 1)[-1]
    else:
        text = path.read_text(encoding="utf-8")
    return [line for line in text.splitlines() if line.strip()]


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _write(path: Path, text: str) -> None:
    from spotbot.state import write_atomic

    write_atomic(path, text)


def note_heartbeat(data_dir: Path, book: str) -> None:
    """One timestamp for the ops page. Age is how long since the last finished cycle."""
    if not isinstance(book, str) or len(book) > 32:
        book = ""
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        payload = {"at": _now(), "book": book}
        _write(data_dir / "ops_heartbeat.json", json.dumps(payload))
    except (OSError, UnicodeError, TypeError, ValueError, MemoryError) as exc:
        LOG.warning("ops heartbeat was not written: %s", exc)
