"""One pass: exits first, then at most the free slots of new entries."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from spotbot.config import Config
from spotbot.exits import exit_reason, pnl_bps
from spotbot.liquidity import ask_wall_exit, lift_signal
from spotbot.analyzer import score
from spotbot.oracle import deviation_bps, peer_prices
from spotbot.mexc import MexcClient, MexcError
from spotbot.money import BASE_ATOMS, SATOSHI_MULTIPLIER, format_usdt
from spotbot.signals import entry_signal, rsi
from spotbot.state import Book, Position, load_book, save_book

LOG = logging.getLogger("spotbot")


@dataclass(frozen=True)
class CycleReport:
    exits: int
    entries: int
    skipped: int


def run_cycle(cfg: Config, client: MexcClient, path: Path) -> CycleReport:
    book = load_book(path, cfg.paper_cash_micro)
    exits = _close_positions(cfg, client, book)
    entries, skipped = _open_positions(cfg, client, book)
    save_book(path, book)
    LOG.info(
        "cash=%s realized=%s positions=%s exits=%s entries=%s skipped=%s live=%s",
        format_usdt(book.cash_micro),
        format_usdt(book.realized_micro),
        len(book.positions),
        exits,
        entries,
        skipped,
        cfg.live,
    )
    return CycleReport(exits=exits, entries=entries, skipped=skipped)


def _close_positions(cfg: Config, client: MexcClient, book: Book) -> int:
    kept: list[Position] = []
    closed = 0
    for pos in book.positions:
        try:
            price = client.price(pos.symbol)
        except MexcError as exc:
            LOG.warning("price failed, position kept: %s", exc)
            kept.append(pos)
            continue
        if price > pos.peak_micro:
            pos.peak_micro = price
        stop, take, arm, gap = _risk(cfg)
        reason = exit_reason(pos.entry_micro, price, pos.peak_micro, stop, take, arm, gap)
        if reason is None and cfg.mode == "liquidity":
            try:
                bid, ask = client.depth_notional(pos.symbol)
            except MexcError as exc:
                LOG.warning("depth failed, position kept: %s", exc)
                kept.append(pos)
                continue
            if ask_wall_exit(bid, ask, pnl_bps(pos.entry_micro, price)):
                reason = "ask_wall"
        if reason is None:
            kept.append(pos)
            continue
        if cfg.live:
            client.market_sell_base(pos.symbol, pos.base_atoms)
        proceeds = pos.base_atoms * price // BASE_ATOMS
        book.cash_micro += proceeds
        book.realized_micro += proceeds - pos.quote_micro
        closed += 1
        LOG.info("exit %s %s price=%s", reason, pos.symbol, format_usdt(price))
    book.positions = kept
    return closed


def _open_positions(cfg: Config, client: MexcClient, book: Book) -> tuple[int, int]:
    slots = cfg.max_positions - len(book.positions)
    if slots <= 0:
        return 0, 0
    held = {pos.symbol for pos in book.positions}
    if cfg.mode == "liquidity":
        return _open_liquidity(cfg, client, book, held, slots)
    opened = 0
    skipped = 0
    for symbol in cfg.symbols:
        if opened >= slots:
            break
        if symbol in held:
            continue
        try:
            closes = client.klines(symbol)
        except MexcError as exc:
            LOG.warning("klines failed: %s", exc)
            skipped += 1
            continue
        signal = entry_signal(symbol, closes, cfg.rsi_buy)
        if signal is None:
            continue
        spend = book.cash_micro * cfg.alloc_bps // 10_000
        if spend < cfg.min_notional_micro:
            skipped += 1
            continue
        price = closes[-1]
        if cfg.live:
            base_atoms = client.market_buy_quote(symbol, spend)
        else:
            base_atoms = spend * BASE_ATOMS // price
        if base_atoms <= 0:
            skipped += 1
            continue
        book.cash_micro -= spend
        book.positions.append(
            Position(
                symbol=symbol,
                entry_micro=price,
                peak_micro=price,
                quote_micro=spend,
                base_atoms=base_atoms,
                reason=signal.reason,
            )
        )
        opened += 1
        LOG.info("entry %s %s rsi=%s spend=%s", signal.reason, symbol, signal.rsi, format_usdt(spend))
    return opened, skipped


def _open_liquidity(cfg: Config, client: MexcClient, book: Book, held: set[str], slots: int) -> tuple[int, int]:
    opened = 0
    skipped = 0
    try:
        symbols = client.liquid_usdt(200_000 * SATOSHI_MULTIPLIER, 50, 1_200, 8)
    except MexcError as exc:
        LOG.warning("ticker scan failed: %s", exc)
        return 0, 1
    LOG.info("liquidity candidates=%s", ",".join(symbols) if symbols else "none")
    probes: dict[str, tuple[list[tuple[int, int, int, int, int]], int, int, list[int]]] = {}
    wanted = [symbol for symbol in symbols if symbol not in held]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_probe_lift, client, symbol): symbol for symbol in wanted}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                probes[symbol] = future.result()
            except MexcError as exc:
                LOG.warning("lift check failed: %s", exc)
                skipped += 1
    for symbol in symbols:
        if opened >= slots:
            break
        if symbol not in probes:
            continue
        rows, bid, ask, peers = probes[symbol]
        closed = rows[-2]
        signal = lift_signal(
            symbol,
            [row[4] for row in rows],
            closed[1],
            closed[2],
            closed[3],
            bid,
            ask,
        )
        if signal is None:
            continue
        dev = deviation_bps([closed[3], *peers])
        if dev is None:
            skipped += 1
            continue
        rsi_value = rsi([row[3] for row in rows])
        points = score(
            signal.volume_ratio_bps,
            signal.close_pos_bps,
            dev,
            100 if rsi_value is None else rsi_value,
            bid,
            ask,
        )
        if points <= 0:
            skipped += 1
            continue
        spend = book.cash_micro * cfg.alloc_bps // 10_000
        if spend < cfg.min_notional_micro:
            skipped += 1
            continue
        price = closed[3]
        if cfg.live:
            base_atoms = client.market_buy_quote(symbol, spend)
        else:
            base_atoms = spend * BASE_ATOMS // price
        if base_atoms <= 0:
            skipped += 1
            continue
        book.cash_micro -= spend
        book.positions.append(
            Position(
                symbol=symbol,
                entry_micro=price,
                peak_micro=price,
                quote_micro=spend,
                base_atoms=base_atoms,
                reason=f"lift:{signal.volume_ratio_bps}bps",
            )
        )
        opened += 1
        target = price * (10_000 + _risk(cfg)[1]) // 10_000
        LOG.info(
            "entry lift %s score=%s vol=%s.%02dx close_pos=%s target=%s spend=%s",
            symbol,
            points,
            signal.volume_ratio_bps // 10_000,
            (signal.volume_ratio_bps % 10_000) // 100,
            signal.close_pos_bps,
            format_usdt(target),
            format_usdt(spend),
        )
    return opened, skipped


def _probe_lift(
    client: MexcClient, symbol: str
) -> tuple[list[tuple[int, int, int, int, int]], int, int, list[int]]:
    rows = client.ohlcv(symbol, "5m", 20)
    bid, ask = client.depth_notional(symbol)
    return rows, bid, ask, peer_prices(symbol)


def _risk(cfg: Config) -> tuple[int, int, int, int]:
    if cfg.mode == "liquidity":
        return 150, 250, 120, 80
    return cfg.stop_bps, cfg.take_bps, cfg.trail_arm_bps, cfg.trail_gap_bps
