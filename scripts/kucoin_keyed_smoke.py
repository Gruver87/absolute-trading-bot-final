#!/usr/bin/env python3
"""KuCoin keyed smoke: public + auth *read* only. Never places orders.

Requires KUCOIN_API_KEY / KUCOIN_API_SECRET / KUCOIN_API_PASSPHRASE in the
environment (or repo ``.env``). Fails closed if ``SPOT_LIVE=1`` or ``--live``
is present — this script is not a live trading path.

Checks:
  1. Public server time
  2. Public BTCUSDT last price (optional sanity)
  3. Signed GET /api/v1/accounts (trade balances)

Does not call market_buy / market_sell / hf/orders.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _refuse_live(argv: list[str]) -> str | None:
    """Any live signal means this smoke must not run."""
    if any(arg == "--live" for arg in argv):
        return "refusing keyed smoke with --live (orders path is out of scope)"
    live = os.environ.get("SPOT_LIVE", "0")
    if not isinstance(live, str) or live.strip() not in ("0", "1"):
        return "refusing keyed smoke: SPOT_LIVE must be 0 or 1"
    if live.strip() == "1":
        return "refusing keyed smoke while SPOT_LIVE=1 (fail closed; set SPOT_LIVE=0)"
    return None


def _load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    try:
        if env_path.stat().st_size > 65_536:
            raise SystemExit("env file is too large")
    except OSError as exc:
        raise SystemExit(f"env file unreadable: {exc}") from exc
    from dotenv import load_dotenv

    load_dotenv(env_path)


def main(argv: list[str] | None = None) -> int:
    given = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        description="KuCoin keyed smoke (read-only). Never places orders."
    )
    parser.add_argument(
        "--skip-price",
        action="store_true",
        help="skip public BTCUSDT price (still checks clock + accounts)",
    )
    # Accept --live only so we can refuse it explicitly (fail closed).
    parser.add_argument("--live", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(given)

    reason = _refuse_live(given if argv is not None else sys.argv[1:])
    if reason:
        print(reason, file=sys.stderr)
        return 2
    if args.live:
        print("refusing keyed smoke with --live", file=sys.stderr)
        return 2

    _load_env()
    # Re-check SPOT_LIVE after dotenv; argv --live already caught above.
    live = os.environ.get("SPOT_LIVE", "0")
    if not isinstance(live, str) or live.strip() not in ("0", "1"):
        print("refusing keyed smoke: SPOT_LIVE must be 0 or 1", file=sys.stderr)
        return 2
    if live.strip() == "1":
        print(
            "refusing keyed smoke while SPOT_LIVE=1 (fail closed; set SPOT_LIVE=0)",
            file=sys.stderr,
        )
        return 2

    key = os.environ.get("KUCOIN_API_KEY", "").strip()
    secret = os.environ.get("KUCOIN_API_SECRET", "").strip()
    passphrase = os.environ.get("KUCOIN_API_PASSPHRASE", "").strip()
    key_version = os.environ.get("KUCOIN_API_KEY_VERSION", "2").strip() or "2"
    if not key or not secret or not passphrase:
        print(
            "need KUCOIN_API_KEY, KUCOIN_API_SECRET, and KUCOIN_API_PASSPHRASE",
            file=sys.stderr,
        )
        return 2
    if key_version not in ("1", "2"):
        print("KUCOIN_API_KEY_VERSION must be 1 or 2", file=sys.stderr)
        return 2
    if any(ch in key or ch in secret or ch in passphrase for ch in "\r\n\x00"):
        print("API key is not a single line", file=sys.stderr)
        return 2

    from spotbot.kucoin import KucoinClient, KucoinError, KucoinRateLimit

    client = KucoinClient(key, secret, api_passphrase=passphrase, api_key_version=key_version)
    # Defense: never expose order helpers through this entrypoint's control flow.
    for banned in ("market_buy_quote", "market_sell_base"):
        if not hasattr(client, banned):
            print(f"client missing {banned}; smoke aborted", file=sys.stderr)
            return 1

    try:
        server_ms = int(client.server_time_ms())
        print(f"public server_time_ms={server_ms} OK")
        if not args.skip_price:
            price = int(client.price("BTCUSDT"))
            print(f"public price BTCUSDT={price} OK")
        free_usdt, locked_usdt, free_base, locked_base = client.spot_balances()
        n_free = len(free_base) if isinstance(free_base, dict) else -1
        n_locked = len(locked_base) if isinstance(locked_base, dict) else -1
        print(
            "auth accounts OK "
            f"free_usdt_micro={free_usdt} locked_usdt_micro={locked_usdt} "
            f"base_assets={n_free}+{n_locked}"
        )
    except KucoinRateLimit as exc:
        print(f"smoke rate-limited: {exc}", file=sys.stderr)
        return 1
    except KucoinError as exc:
        print(f"smoke failed: {exc}", file=sys.stderr)
        return 1

    print("keyed smoke PASS (read-only; no orders placed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
