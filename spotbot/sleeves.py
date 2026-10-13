"""Three cash sleeves. Each trades only its own list and keeps its own result.

A new main-balance deposit is split in integer satoshi and added on top.
Sleeve profit and sleeve loss stay in that sleeve. The split never pulls
cash back out.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from pathlib import Path

from spotbot.config import Config
from spotbot.engine import run_cycle
from spotbot.mexc import MexcClient, MexcError, MexcRateLimit
from spotbot.money import format_usdt
from spotbot.state import load_book, save_book, write_atomic

LOG = logging.getLogger("spotbot")


class SleeveError(RuntimeError):
    """Refused sleeve funding."""


@dataclass(frozen=True)
class Sleeve:
    name: str
    symbols: tuple[str, ...]


SLEEVES: tuple[Sleeve, ...] = (
    Sleeve("major", ("BTCUSDT", "ETHUSDT")),
    Sleeve("alt", ("SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT")),
    Sleeve("meme", ("DOGEUSDT", "SHIBUSDT", "PEPEUSDT", "FLOKIUSDT", "BONKUSDT", "WIFUSDT")),
)


def split_equal(amount_micro: int, parts: int = 3) -> tuple[int, ...]:
    """Split satoshi. The first part receives the remainder so the sum matches."""
    if amount_micro < 0 or parts < 1:
        raise SleeveError("split amount must be >= 0")
    base = amount_micro // parts
    out = [base] * parts
    out[0] += amount_micro - base * parts
    return tuple(out)


def ledger_dir(root: Path, live: bool) -> Path:
    """Paper cash and live cash never share a directory."""
    return root / ("live" if live else "paper")


def sleeve_symbols() -> tuple[str, ...]:
    """The fixed pair list. One coin belongs to one sleeve."""
    seen: set[str] = set()
    out: list[str] = []
    for sleeve in SLEEVES:
        for symbol in sleeve.symbols:
            if symbol in seen or not symbol.endswith("USDT") or len(symbol) <= 4:
                raise SleeveError(f"{symbol} is in more than one sleeve")
            seen.add(symbol)
            out.append(symbol)
    return tuple(out)


def apply_funding(data_dir: Path, main_micro: int, live: bool = False) -> tuple[int, ...]:
    """Add only the new main-balance delta. Existing sleeve cash is kept."""
    sleeve_symbols()
    if main_micro < 0:
        raise SleeveError("main balance must be >= 0")
    data_dir = ledger_dir(data_dir, live)
    data_dir.mkdir(parents=True, exist_ok=True)
    treasury = data_dir / "treasury.json"
    funded = 0
    treasury_exists = treasury.exists()
    if treasury_exists:
        raw = json.loads(treasury.read_text(encoding="utf-8"))
        funded = int(raw["funded_micro"])
    if main_micro < funded:
        raise SleeveError("main balance is below the amount already split; sleeve cash is not pulled back")
    parts: list[int] = []
    for index, sleeve in enumerate(SLEEVES):
        path = data_dir / f"sleeve_{sleeve.name}.json"
        existed = path.exists()
        book = load_book(path, 0)
        if book.credited_main_micro is None:
            if existed and not treasury_exists:
                raise SleeveError("sleeve book has no funding mark and treasury is missing")
            book.credited_main_micro = funded if existed else 0
        if book.credited_main_micro > main_micro:
            raise SleeveError("main balance is below the amount already split; sleeve cash is not pulled back")
        part = split_equal(main_micro - book.credited_main_micro, len(SLEEVES))[index]
        book.cash_micro += part
        book.credited_main_micro = main_micro
        save_book(path, book)
        parts.append(part)
    write_atomic(
        treasury,
        json.dumps({"funded_micro": main_micro, "sleeves": [sleeve.name for sleeve in SLEEVES]}, indent=2),
    )
    if main_micro - funded:
        LOG.info(
            "funded delta=%s major=%s alt=%s meme=%s",
            format_usdt(main_micro - funded),
            format_usdt(parts[0]),
            format_usdt(parts[1]),
            format_usdt(parts[2]),
        )
    return tuple(parts)


def run_sleeves(cfg: Config, client: MexcClient, data_dir: Path) -> None:
    """One pass over major, alt, then meme. Books do not share cash."""
    apply_funding(data_dir, cfg.paper_cash_micro, live=cfg.live)
    books = ledger_dir(data_dir, cfg.live)
    paths = {sleeve.name: books / f"sleeve_{sleeve.name}.json" for sleeve in SLEEVES}
    for sleeve in SLEEVES:
        child = replace(
            cfg,
            symbols=sleeve.symbols,
            max_positions=1,
            alloc_bps=10_000,
            symbol_lock=True,
        )
        path = paths[sleeve.name]
        siblings = tuple(item for name, item in paths.items() if name != sleeve.name)
        LOG.info("sleeve=%s symbols=%s", sleeve.name, ",".join(sleeve.symbols))
        try:
            run_cycle(child, client, path, book_name=sleeve.name, sibling_paths=siblings)
        except MexcRateLimit:
            LOG.error("sleeve %s stopped on rate limit; the other sleeves wait", sleeve.name)
            raise
        except MexcError as exc:
            LOG.error("sleeve %s failed closed: %s", sleeve.name, exc)
