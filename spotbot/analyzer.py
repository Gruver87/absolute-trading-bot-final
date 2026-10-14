"""Integer score. Rust does the arithmetic when spotbot_native.dll is built.

This is not a model and not a forecast. A missing venue or a wide price
gap refuses the entry. The chain AI sprout is not imported.
"""

from __future__ import annotations

import ctypes
import logging
from pathlib import Path

LOG = logging.getLogger("spotbot.analyzer")

_LIB: ctypes.CDLL | None = None
_LOOKED = False


def _native_file(path: Path, limit: int = 8_000_000) -> bool:
    """A small real file. A directory or a planted huge file is not a library."""
    try:
        return path.is_file() and 0 < path.stat().st_size <= limit
    except OSError:
        return False


def _load() -> ctypes.CDLL | None:
    global _LIB, _LOOKED
    if _LOOKED:
        return _LIB
    _LOOKED = True
    root = Path(__file__).resolve().parents[1]
    candidates = [
        root / "native" / "target" / "release" / "spotbot_native.dll",
        root / "native" / "target" / "debug" / "spotbot_native.dll",
    ]
    for path in candidates:
        if not _native_file(path):
            continue
        try:
            lib = ctypes.CDLL(str(path))
            lib.sb_score.argtypes = [
                ctypes.c_int32,
                ctypes.c_int32,
                ctypes.c_int32,
                ctypes.c_int32,
                ctypes.c_int64,
                ctypes.c_int64,
            ]
            lib.sb_score.restype = ctypes.c_int32
        except (OSError, AttributeError):
            continue
        _LIB = lib
        LOG.info("analyzer backend=rust %s", path.name)
        return lib
    LOG.info("analyzer backend=python (native dll not built)")
    return None


def score(
    volume_bps: int,
    close_pos_bps: int,
    oracle_dev_bps: int,
    rsi_value: int,
    bid: int,
    ask: int,
) -> int:
    """Return 0 when the setup is refused, else a score in basis points of confidence."""
    nums = (volume_bps, close_pos_bps, oracle_dev_bps, rsi_value, bid, ask)
    if any(isinstance(item, bool) or not isinstance(item, int) for item in nums):
        return 0
    if any(item <= -(2**31) or item >= 2**31 for item in nums[:4]):
        return 0
    if bid <= -(2**63) or bid >= 2**63 or ask <= -(2**63) or ask >= 2**63:
        return 0
    lib = _load()
    if lib is not None:
        return int(
            lib.sb_score(
                int(volume_bps),
                int(close_pos_bps),
                int(oracle_dev_bps),
                int(rsi_value),
                int(bid),
                int(ask),
            )
        )
    return _score_python(volume_bps, close_pos_bps, oracle_dev_bps, rsi_value, bid, ask)


def _score_python(
    volume_bps: int,
    close_pos_bps: int,
    oracle_dev_bps: int,
    rsi_value: int,
    bid: int,
    ask: int,
) -> int:
    nums = (volume_bps, close_pos_bps, oracle_dev_bps, rsi_value, bid, ask)
    if any(isinstance(item, bool) or not isinstance(item, int) for item in nums):
        return 0
    if any(item <= -(2**31) or item >= 2**31 for item in nums[:4]):
        return 0
    if bid <= -(2**63) or bid >= 2**63 or ask <= -(2**63) or ask >= 2**63:
        return 0
    if bid <= 0 or ask < 0 or ask >= bid:
        return 0
    if volume_bps < 20_000 or close_pos_bps < 6_500:
        return 0
    if oracle_dev_bps < 0 or oracle_dev_bps > 30:
        return 0
    total = 4_000 + 2_000 + 3_000
    if 0 <= rsi_value < 45:
        total += 1_000
    return total


def backend() -> str:
    return "rust" if _load() is not None else "python"
