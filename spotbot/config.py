"""Runtime config. Live trading stays off unless both the env and the CLI ask."""

from __future__ import annotations

import os
from dataclasses import dataclass

from spotbot.money import parse_micro


class ConfigError(RuntimeError):
    """Refused config."""


@dataclass(frozen=True)
class Config:
    symbols: tuple[str, ...]
    paper_cash_micro: int
    interval_sec: int
    max_positions: int
    alloc_bps: int
    min_notional_micro: int
    rsi_buy: int
    stop_bps: int
    take_bps: int
    trail_arm_bps: int
    trail_gap_bps: int
    live: bool
    mode: str
    api_key: str
    api_secret: str
    telegram_token: str
    telegram_chat_id: str


def load_config(live_flag: bool, mode: str | None = None) -> Config:
    symbols = tuple(
        part.strip().upper()
        for part in os.environ.get("SPOT_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",")
        if part.strip()
    )
    if not symbols:
        raise ConfigError("SPOT_SYMBOLS is empty")
    interval = int(os.environ.get("SPOT_INTERVAL_SEC", "60"))
    if interval < 15:
        raise ConfigError("SPOT_INTERVAL_SEC must be >= 15")
    env_live = os.environ.get("SPOT_LIVE", "0") == "1"
    live = bool(live_flag and env_live)
    key = os.environ.get("MEXC_API_KEY", "").strip()
    secret = os.environ.get("MEXC_API_SECRET", "").strip()
    if live and (not key or not secret):
        raise ConfigError("live mode needs MEXC_API_KEY and MEXC_API_SECRET in the environment")
    if live_flag and not env_live:
        raise ConfigError("refusing --live without SPOT_LIVE=1")
    chosen = (mode or os.environ.get("SPOT_MODE", "rsi")).strip().lower()
    if chosen not in ("rsi", "liquidity"):
        raise ConfigError("SPOT_MODE must be rsi or liquidity")
    return Config(
        symbols=symbols,
        paper_cash_micro=parse_micro(os.environ.get("SPOT_PAPER_CASH_USDT", "1000")),
        interval_sec=interval,
        max_positions=int(os.environ.get("SPOT_MAX_POSITIONS", "3")),
        alloc_bps=int(os.environ.get("SPOT_ALLOC_BPS", "2000")),
        min_notional_micro=parse_micro(os.environ.get("SPOT_MIN_USDT", "3")),
        rsi_buy=int(os.environ.get("SPOT_RSI_BUY", "35")),
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        live=live,
        mode=chosen,
        api_key=key,
        api_secret=secret,
        telegram_token=os.environ.get("TELEGRAM_TOKEN", "").strip(),
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", "").strip(),
    )
