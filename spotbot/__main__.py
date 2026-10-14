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
from spotbot.config import Config, ConfigError, load_config
from spotbot.engine import run_cycle
from spotbot.mexc import MexcClient, MexcError, MexcRateLimit, backoff_sec
from spotbot.money import MoneyError
from spotbot.ops_http import DEFAULT_PORT, OpsError, parse_ops_port, serve
from spotbot.sleeves import SleeveError, ledger_dir, run_sleeves
from spotbot.state import LedgerError, hold_ledger

# A money or value error stops this pass. The process stays up and the next pass reads the book again.
CYCLE_HOLDS = (MoneyError, ValueError, TypeError)


def _env_too_big(path: Path) -> bool:
    """A planted env file is not read. A missing file is the normal paper start."""
    if not path.exists():
        return False
    try:
        return path.stat().st_size > 65_536
    except OSError:
        return True


def _log_line(exc: BaseException) -> str:
    """A cycle error stays on one line. The body is not copied into the log."""
    text = str(exc)
    return text if len(text) <= 180 else text[:180]


def main(argv: list[str] | None = None) -> int:
    given = list(sys.argv[1:] if argv is None else argv)
    if len(given) > 16 or any(not isinstance(item, str) or len(item) > 32 for item in given):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        logging.error("command is too wide")
        return 2
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
    args = parser.parse_args(given)
    root = Path(__file__).resolve().parents[1]
    env_path = root / ".env"
    if _env_too_big(env_path):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        logging.error("env file is too large")
        return 2
    load_dotenv(env_path)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    file_log = logging.FileHandler(data_dir / "ops.log", encoding="utf-8")
    file_log.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(file_log)
    try:
        cfg = load_config(live_flag=args.live, mode=args.mode)
    except ConfigError as exc:
        logging.error("%s", _log_line(exc))
        return 2
    if args.ops:
        try:
            ops_port = parse_ops_port(os.environ.get("SPOT_OPS_PORT", str(DEFAULT_PORT)))
        except OpsError as exc:
            logging.error("%s", _log_line(exc))
            return 2
        threading.Thread(target=serve, args=(data_dir, ops_port), name="spot-ops", daemon=True).start()
        logging.info("ops http://127.0.0.1:%s", ops_port)
    client = MexcClient(cfg.api_key, cfg.api_secret)
    try:
        with hold_ledger(ledger_dir(data_dir, cfg.live)):
            return _trade(args, cfg, client, data_dir)
    except LedgerError as exc:
        logging.error("%s", _log_line(exc))
        return 2


def _trade(args: argparse.Namespace, cfg: Config, client: MexcClient, data_dir: Path) -> int:
    """One process, one ledger. The caller already holds the directory."""
    if args.sleeves:
        logging.info("mode=%s sleeves=major,alt,meme strategy=%s", "LIVE" if cfg.live else "PAPER", cfg.mode)
        while True:
            try:
                run_sleeves(cfg, client, data_dir)
            except (SleeveError, LedgerError) as exc:
                logging.error("%s", _log_line(exc))
                return 2
            except MexcRateLimit as exc:
                logging.error("cycle failed closed: %s", _log_line(exc))
                if args.once:
                    return 1
                pause = backoff_sec(exc.retry_after_sec, cfg.interval_sec)
                logging.error("rate limit pause %ss", pause)
            except MexcError as exc:
                logging.error("cycle failed closed: %s", _log_line(exc))
                if args.once:
                    return 1
                pause = cfg.interval_sec
            except CYCLE_HOLDS:
                logging.exception("cycle failed closed")
                if args.once:
                    return 1
                pause = cfg.interval_sec
            except OSError as exc:
                logging.error("cycle paused, the link failed: %s", _log_line(exc))
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
            logging.error("cycle failed closed: %s", _log_line(exc))
            if args.once:
                return 1
            pause = backoff_sec(exc.retry_after_sec, cfg.interval_sec)
            logging.error("rate limit pause %ss", pause)
        except (MexcError, LedgerError) as exc:
            logging.error("cycle failed closed: %s", _log_line(exc))
            if args.once:
                return 1
            pause = cfg.interval_sec
        except CYCLE_HOLDS:
            logging.exception("cycle failed closed")
            if args.once:
                return 1
            pause = cfg.interval_sec
        except OSError as exc:
            logging.error("cycle paused, the link failed: %s", _log_line(exc))
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
