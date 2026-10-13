"""Standalone ops page. Does not start the bot and does not bind the mesh ports."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from spotbot.ops_http import DEFAULT_PORT, OpsError, check_ops_port, serve


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only spot bot ops page")
    parser.add_argument("--port", type=int, default=int(os.environ.get("SPOT_OPS_PORT", str(DEFAULT_PORT))))
    args = parser.parse_args(argv)
    try:
        check_ops_port(args.port)
    except OpsError as exc:
        print(exc, file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parents[1]
    print(f"ops http://127.0.0.1:{args.port}")
    serve(root / "data", args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
