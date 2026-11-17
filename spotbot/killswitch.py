"""Operator kill switch: pause new entries while exits keep running.

Active when ``data/STOP`` exists as a regular file, or when ``SPOT_KILL=1``.
Neither path enables entries; both only block buys once entries would otherwise
be allowed. Removing the file / setting ``SPOT_KILL=0`` clears the pause.
"""

from __future__ import annotations

import os
from pathlib import Path


def stop_file_path(data_dir: Path) -> Path:
    """Canonical STOP path next to ops.log / paper|live ledgers."""
    return Path(data_dir) / "STOP"


def kill_switch_active(data_dir: Path | None = None) -> bool:
    """True when the operator asked to halt new entries."""
    if _env_kill():
        return True
    if data_dir is None:
        return False
    path = stop_file_path(data_dir)
    try:
        return path.is_file()
    except OSError:
        # Unreadable STOP is treated as active: fail closed on entries.
        return True


def kill_switch_reason(data_dir: Path | None = None) -> str:
    """Short operator-facing reason, or empty when inactive."""
    reasons: list[str] = []
    if _env_kill():
        reasons.append("SPOT_KILL=1")
    if data_dir is not None:
        path = stop_file_path(data_dir)
        try:
            if path.is_file():
                reasons.append(f"file {path.name}")
        except OSError:
            reasons.append(f"unreadable {path.name}")
    return ", ".join(reasons)


def _env_kill() -> bool:
    raw = os.environ.get("SPOT_KILL", "0")
    if not isinstance(raw, str):
        return True
    raw = raw.strip()
    if raw not in ("0", "1"):
        # Bad value fails closed for entries.
        return True
    return raw == "1"
