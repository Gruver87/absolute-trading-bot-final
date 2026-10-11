"""Spot paper bot. Does not import DUP Protocol and does not place orders unless asked twice."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from spotbot.analyzer import backend
from spotbot.config import ConfigError, load_config
from spotbot.engine import run_cycle
from spotbot.mexc import MexcClient, MexcError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MEXC spot bot, paper by default")
    parser.add_argument("--live", action="store_true", help="send real orders; also requires SPOT_LIVE=1")
    parser.add_argument("--mode", choices=("rsi", "liquidity"), default=None)
    parser.add_argument("--once", action="store_true", help="run a single cycle and exit")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        cfg = load_config(live_flag=args.live, mode=args.mode)
    except ConfigError as exc:
        logging.error("%s", exc)
        return 2
    client = MexcClient(cfg.api_key, cfg.api_secret)
    book_path = root / "data" / ("book_liquidity.json" if cfg.mode == "liquidity" else "book.json")
    mode = "LIVE" if cfg.live else "PAPER"
    logging.info("mode=%s strategy=%s analyzer=%s", mode, cfg.mode, backend())
    while True:
        try:
            run_cycle(cfg, client, book_path)
        except MexcError as exc:
            logging.error("cycle failed closed: %s", exc)
            if args.once:
                return 1
        if args.once:
            return 0
        time.sleep(cfg.interval_sec)


if __name__ == "__main__":
    sys.exit(main())
