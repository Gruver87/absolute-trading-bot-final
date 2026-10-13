"""Runtime config. Live trading stays off unless both the env and the CLI ask."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from spotbot.money import MoneyError, parse_micro

_SYMBOL = re.compile(r"^[A-Z0-9]{2,10}USDT$")


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
    taker_bps: int
    daily_loss_bps: int
    stop_cooldown_sec: int
    symbol_lock: bool
    api_key: str
    api_secret: str
    drawdown_bps: int = 1_000
    stop_lock_count: int = 3
    stop_lock_sec: int = 14_400
    spread_bps: int = 30
    entries: bool = False


def require_cycle_config(cfg: Config) -> None:
    """Refuse a config the cycle must not trade. Same bounds as the env loader."""
    if not cfg.symbols or len(set(cfg.symbols)) != len(cfg.symbols):
        raise ConfigError("symbols are empty or repeated")
    for symbol in cfg.symbols:
        if not isinstance(symbol, str) or _SYMBOL.fullmatch(symbol) is None:
            raise ConfigError(f"{symbol} is not a USDT pair")
    if not isinstance(cfg.live, bool) or not isinstance(cfg.symbol_lock, bool) or not isinstance(cfg.entries, bool):
        raise ConfigError("live, entries, and the pair lock must be on or off")
    if not isinstance(cfg.api_key, str) or not isinstance(cfg.api_secret, str):
        raise ConfigError("api key must be text")
    if len(cfg.api_key) > 256 or len(cfg.api_secret) > 256 or any(ch in cfg.api_key or ch in cfg.api_secret for ch in "\r\n\x00"):
        raise ConfigError("API key is not a single line")
    if cfg.mode not in ("rsi", "liquidity"):
        raise ConfigError("mode must be rsi or liquidity")
    numbers = (
        cfg.paper_cash_micro,
        cfg.interval_sec,
        cfg.max_positions,
        cfg.alloc_bps,
        cfg.min_notional_micro,
        cfg.rsi_buy,
        cfg.stop_bps,
        cfg.take_bps,
        cfg.trail_arm_bps,
        cfg.trail_gap_bps,
        cfg.taker_bps,
        cfg.daily_loss_bps,
        cfg.stop_cooldown_sec,
        cfg.drawdown_bps,
        cfg.stop_lock_count,
        cfg.stop_lock_sec,
        cfg.spread_bps,
    )
    if any(isinstance(item, bool) or not isinstance(item, int) for item in numbers):
        raise ConfigError("config numbers must be integers")
    if cfg.interval_sec < 15 or cfg.interval_sec > 86_400:
        raise ConfigError("interval is out of range")
    if cfg.max_positions < 1 or cfg.max_positions > 14:
        raise ConfigError("slots are out of range")
    if cfg.alloc_bps < 1 or cfg.alloc_bps > 10_000:
        raise ConfigError("allocation is out of range")
    if cfg.rsi_buy < 1 or cfg.rsi_buy > 99:
        raise ConfigError("rsi is out of range")
    if cfg.taker_bps < 0 or cfg.taker_bps > 100:
        raise ConfigError("taker fee is out of range")
    if cfg.daily_loss_bps < 0 or cfg.daily_loss_bps > 10_000:
        raise ConfigError("daily loss is out of range")
    if cfg.stop_cooldown_sec < 0 or cfg.stop_cooldown_sec > 86_400:
        raise ConfigError("stop cooldown is out of range")
    if cfg.drawdown_bps < 0 or cfg.drawdown_bps > 10_000:
        raise ConfigError("drawdown is out of range")
    if cfg.stop_lock_count < 2 or cfg.stop_lock_count > 10:
        raise ConfigError("stop lock count is out of range")
    if cfg.stop_lock_sec < 0 or cfg.stop_lock_sec > 86_400:
        raise ConfigError("stop lock is out of range")
    if cfg.spread_bps < 1 or cfg.spread_bps > 500:
        raise ConfigError("spread limit is out of range")
    if cfg.paper_cash_micro < 0 or cfg.min_notional_micro <= 0:
        raise ConfigError("cash must be >= 0 and the minimum order > 0")
    if min(cfg.stop_bps, cfg.take_bps, cfg.trail_arm_bps, cfg.trail_gap_bps) <= 0:
        raise ConfigError("exit percents must be positive")


def _env_int(name: str, default: str, low: int, high: int) -> int:
    """Read one integer env. A blank, a sign, a fraction, or a huge digit string is refused."""
    raw = os.environ.get(name, default)
    if not isinstance(raw, str):
        raise ConfigError(f"{name} must be an integer")
    raw = raw.strip()
    if len(raw) > 8 or not raw.isdigit():
        raise ConfigError(f"{name} must be an integer")
    value = int(raw)
    if value < low or value > high:
        raise ConfigError(f"{name} must be {low}..{high}")
    return value


def _env_flag(name: str, default: str) -> bool:
    """Read 0 or 1. Anything else is refused, not treated as on."""
    raw = os.environ.get(name, default)
    if not isinstance(raw, str):
        raise ConfigError(f"{name} must be 0 or 1")
    raw = raw.strip()
    if raw not in ("0", "1"):
        raise ConfigError(f"{name} must be 0 or 1")
    return raw == "1"


def load_config(live_flag: bool, mode: str | None = None) -> Config:
    if not isinstance(live_flag, bool):
        raise ConfigError("live flag must be on or off")
    if mode is not None and (not isinstance(mode, str) or len(mode) > 32):
        raise ConfigError("SPOT_MODE must be rsi or liquidity")
    raw_symbols = os.environ.get("SPOT_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT")
    if not isinstance(raw_symbols, str) or len(raw_symbols) > 512:
        raise ConfigError("SPOT_SYMBOLS is empty")
    symbols = tuple(
        part.strip().upper()
        for part in raw_symbols.split(",")
        if part.strip()
    )
    if not symbols:
        raise ConfigError("SPOT_SYMBOLS is empty")
    if len(set(symbols)) != len(symbols):
        raise ConfigError("SPOT_SYMBOLS has a duplicate")
    for symbol in symbols:
        if _SYMBOL.fullmatch(symbol) is None:
            raise ConfigError(f"{symbol} is not a USDT pair")
    interval = _env_int("SPOT_INTERVAL_SEC", "60", 15, 86_400)
    env_live = os.environ.get("SPOT_LIVE", "0") == "1"
    live = live_flag and env_live
    key = os.environ.get("MEXC_API_KEY", "").strip()
    secret = os.environ.get("MEXC_API_SECRET", "").strip()
    if any(ch in key or ch in secret for ch in "\r\n\x00"):
        raise ConfigError("API key is not a single line")
    if live and (not key or not secret):
        raise ConfigError("live mode needs MEXC_API_KEY and MEXC_API_SECRET in the environment")
    if live_flag and not env_live:
        raise ConfigError("refusing --live without SPOT_LIVE=1")
    chosen = (mode or os.environ.get("SPOT_MODE", "rsi")).strip().lower()
    if chosen not in ("rsi", "liquidity"):
        raise ConfigError("SPOT_MODE must be rsi or liquidity")
    taker_bps = _env_int("SPOT_TAKER_BPS", "5", 0, 100)
    daily_loss_bps = _env_int("SPOT_DAILY_LOSS_BPS", "500", 0, 10_000)
    stop_cooldown_sec = _env_int("SPOT_STOP_COOLDOWN_SEC", "900", 0, 86_400)
    drawdown_bps = _env_int("SPOT_DRAWDOWN_BPS", "1000", 0, 10_000)
    stop_lock_count = _env_int("SPOT_STOP_LOCK_COUNT", "3", 2, 10)
    stop_lock_sec = _env_int("SPOT_STOP_LOCK_SEC", "14400", 0, 86_400)
    spread_bps = _env_int("SPOT_SPREAD_BPS", "30", 1, 500)
    entries = _env_flag("SPOT_ENTRIES", "0")
    try:
        paper_cash = parse_micro(os.environ.get("SPOT_PAPER_CASH_USDT", "1000"))
        min_notional = parse_micro(os.environ.get("SPOT_MIN_USDT", "3"))
    except MoneyError as exc:
        raise ConfigError(str(exc)) from exc
    built = Config(
        symbols=symbols,
        paper_cash_micro=paper_cash,
        interval_sec=interval,
        max_positions=_env_int("SPOT_MAX_POSITIONS", "3", 1, 14),
        alloc_bps=_env_int("SPOT_ALLOC_BPS", "2000", 1, 10_000),
        min_notional_micro=min_notional,
        rsi_buy=_env_int("SPOT_RSI_BUY", "35", 1, 99),
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        live=live,
        mode=chosen,
        taker_bps=taker_bps,
        daily_loss_bps=daily_loss_bps,
        stop_cooldown_sec=stop_cooldown_sec,
        symbol_lock=False,
        api_key=key,
        api_secret=secret,
        drawdown_bps=drawdown_bps,
        stop_lock_count=stop_lock_count,
        stop_lock_sec=stop_lock_sec,
        spread_bps=spread_bps,
        entries=entries,
    )
    require_cycle_config(built)
    return built
