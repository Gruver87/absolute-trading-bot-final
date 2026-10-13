"""Spot paper bot. Does not import DUP Protocol and does not place orders unless asked twice."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

from spotbot.analyzer import backend
from spotbot.config import ConfigError, load_config
from spotbot.engine import run_cycle
from spotbot.mexc import MexcClient, MexcError, MexcRateLimit, backoff_sec
from spotbot.ops_http import DEFAULT_PORT, OpsError, check_ops_port, serve
from spotbot.sleeves import SleeveError, ledger_dir, run_sleeves
from spotbot.state import LedgerError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MEXC spot bot, paper by default")
    parser.add_argument("--live", action="store_true", help="send real orders; also requires SPOT_LIVE=1")
    parser.add_argument("--mode", choices=("rsi", "liquidity"), default=None)
    parser.add_argument("--once", action="store_true", help="run a single cycle and exit")
    parser.add_argument(
        "--sleeves",
        action="store_true",
        help="split the main balance into major, alt, and meme books",
    )
    parser.add_argument(
        "--ops",
        action="store_true",
        help="also serve the read-only page on 127.0.0.1:19280",
    )
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    file_log = logging.FileHandler(data_dir / "ops.log", encoding="utf-8")
    file_log.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(file_log)
    try:
        cfg = load_config(live_flag=args.live, mode=args.mode)
    except ConfigError as exc:
        logging.error("%s", exc)
        return 2
    if args.ops:
        ops_port = int(os.environ.get("SPOT_OPS_PORT", str(DEFAULT_PORT)))
        try:
            check_ops_port(ops_port)
        except OpsError as exc:
            logging.error("%s", exc)
            return 2
        threading.Thread(target=serve, args=(data_dir, ops_port), name="spot-ops", daemon=True).start()
        logging.info("ops http://127.0.0.1:%s", ops_port)
    client = MexcClient(cfg.api_key, cfg.api_secret)
    if args.sleeves:
        logging.info("mode=%s sleeves=major,alt,meme strategy=%s", "LIVE" if cfg.live else "PAPER", cfg.mode)
        while True:
            try:
                run_sleeves(cfg, client, data_dir)
            except (SleeveError, LedgerError) as exc:
                logging.error("%s", exc)
                return 2
            except MexcRateLimit as exc:
                logging.error("cycle failed closed: %s", exc)
                if args.once:
                    return 1
                pause = backoff_sec(exc.retry_after_sec, cfg.interval_sec)
                logging.error("rate limit pause %ss", pause)
            except MexcError as exc:
                logging.error("cycle failed closed: %s", exc)
                if args.once:
                    return 1
                pause = cfg.interval_sec
            else:
                pause = cfg.interval_sec
            if args.once:
                return 0
            time.sleep(pause)
    book_path = ledger_dir(data_dir, cfg.live) / (
        "book_liquidity.json" if cfg.mode == "liquidity" else "book.json"
    )
    mode = "LIVE" if cfg.live else "PAPER"
    logging.info("mode=%s strategy=%s analyzer=%s", mode, cfg.mode, backend())
    while True:
        try:
            run_cycle(cfg, client, book_path)
        except MexcRateLimit as exc:
            logging.error("cycle failed closed: %s", exc)
            if args.once:
                return 1
            pause = backoff_sec(exc.retry_after_sec, cfg.interval_sec)
            logging.error("rate limit pause %ss", pause)
        except (MexcError, LedgerError) as exc:
            logging.error("cycle failed closed: %s", exc)
            if args.once:
                return 1
            pause = cfg.interval_sec
        else:
            pause = cfg.interval_sec
        if args.once:
            return 0
        time.sleep(pause)


if __name__ == "__main__":
    sys.exit(main())
