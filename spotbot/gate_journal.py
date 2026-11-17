"""Append-only journal for unseen_gate readiness and --run results.

Writes one JSON line per call under ``data/gate_history.jsonl`` (or an
override path). Never flips entries or live trading.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# Labels match scripts/unseen_gate.py pooled median lines.
MEDIAN_LABELS = (
    "earlier rsi",
    "earlier lift-candles",
    "later rsi",
    "later lift-candles",
)


def default_journal_path(root: Path) -> Path:
    return Path(root) / "data" / "gate_history.jsonl"


def tip_sha(root: Path) -> str:
    """Best-effort git tip. Missing git → unknown (journal still writes)."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    text = (proc.stdout or "").strip()
    if proc.returncode != 0 or not text or len(text) > 64:
        return "unknown"
    return text


def build_record(
    *,
    kind: str,
    result: str,
    tip: str,
    early: dict[str, float] | None = None,
    late: dict[str, float] | None = None,
    ready: bool | None = None,
    now_ms: int | None = None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    """One journal row. Eight median keys are always present (null if unknown)."""
    if not isinstance(kind, str) or kind not in ("readiness", "run"):
        raise ValueError("kind must be readiness or run")
    if not isinstance(result, str) or not result or len(result) > 32:
        raise ValueError("result is missing or too long")
    if not isinstance(tip, str) or not tip or len(tip) > 64:
        raise ValueError("tip SHA is missing or too long")
    row: dict[str, object] = {
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "kind": kind,
        "result": result,
        "tip_sha": tip,
    }
    if ready is not None:
        row["ready"] = bool(ready)
    if now_ms is not None and isinstance(now_ms, int) and not isinstance(now_ms, bool) and now_ms > 0:
        row["now_ms"] = now_ms
    for label in MEDIAN_LABELS:
        key = label.replace(" ", "_").replace("-", "_")
        e_key = f"early_{key}"
        l_key = f"late_{key}"
        row[e_key] = None
        row[l_key] = None
        if early is not None and label in early:
            row[e_key] = float(early[label])
        if late is not None and label in late:
            row[l_key] = float(late[label])
    if extra:
        for key, value in extra.items():
            if not isinstance(key, str) or len(key) > 32 or key in row:
                continue
            if isinstance(value, (bool, int, float, str)) or value is None:
                row[key] = value
    return row


def append_record(path: Path, record: dict[str, object]) -> None:
    """Append one JSONL line. Creates parent dirs. Raises on I/O failure."""
    if not isinstance(record, dict) or len(record) > 64:
        raise ValueError("gate journal record is too wide")
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    if len(line) > 8_000:
        raise ValueError("gate journal record is too long")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
