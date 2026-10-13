"""One pass: exits first, then at most the free slots of new entries."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from spotbot.config import Config, require_cycle_config
from spotbot.guards import drawdown_blocks, marked_equity, note_pair_stop, pair_locked, spread_blocks, top_spread_bps
from spotbot.journal import note_event, note_heartbeat, note_quote, ops_root
from spotbot.exits import exit_reason, pnl_bps
from spotbot.fees import paper_sell
from spotbot.rules import budget_micro, cap_spend, plan_paper_buy, round_base_atoms, round_quote_micro, uses_slot
from spotbot.liquidity import ask_wall_exit, lift_signal
from spotbot.analyzer import score
from spotbot.oracle import ahead_exit, cheapest_first, deviation_bps, entry_allowed, lag_bps, venue_quotes
from spotbot.mexc import (
    MexcClient,
    MexcError,
    MexcRateLimit,
    clock_allows,
    executed_fill,
    new_client_order_id,
    quantities_from_order,
)
from spotbot.reconcile import (
    FeeAssetError,
    base_is_free,
    inventory_mismatch,
    order_filled,
    order_finished,
    order_is_ours,
    order_missing,
    pending_gone,
    ack_fee_matches,
    fee_fits,
    fills_match,
    split_commission,
)
from spotbot.money import (
    BASE_ATOMS,
    SATOSHI_MULTIPLIER,
    MoneyError,
    format_price,
    format_usdt,
    implied_price_micro,
    notional_micro,
)
from spotbot.sanity import mark_ok, price_grid_ok, price_ok, tick_fits
from spotbot.signals import closed_prices, entry_signal, rsi
from spotbot.state import (
    Book,
    Position,
    apply_buy_progress,
    apply_sell_progress,
    bind_ledger,
    clear_pending,
    exchange_order_id_ok,
    load_book,
    record_buy,
    record_sell_fill,
    remember_pending,
    save_book,
)

LOG = logging.getLogger("spotbot")
CYCLE_BUDGET_SEC = 40
PROBE_CAP = 8
CLOCK_SKEW_MS = 2000


@dataclass(frozen=True)
class CycleReport:
    exits: int
    entries: int
    skipped: int


def run_cycle(
    cfg: Config,
    client: MexcClient,
    path: Path,
    book_name: str = "",
    sibling_paths: tuple[Path, ...] = (),
) -> CycleReport:
    require_cycle_config(cfg)
    client.forget_rules()
    book = load_book(path, cfg.paper_cash_micro)
    bind_ledger(book, cfg.live)
    _roll_guard(book)
    name = book_name or path.stem
    clock_ok = _clock_ok(client) if cfg.live else True
    other_pending = sibling_pending(sibling_paths) if cfg.live else None
    if other_pending:
        LOG.warning("sibling order blocks this book: %s", other_pending)
    orders_allowed = clock_ok and other_pending is None
    exits, marks, unmarked = _close_positions(cfg, client, book, path, name, orders_allowed)
    pending_problem = _resolve_pending(client, book, path) if cfg.live and book.pending_client_id else None
    exit_fees = _exit_fees(client, book)
    equity = None if exit_fees is None else marked_equity(book.cash_micro, book.positions, marks, exit_fees)
    if equity is not None and equity > book.equity_peak_micro:
        book.equity_peak_micro = equity
    drawn = equity is not None and drawdown_blocks(book.equity_peak_micro, equity, cfg.drawdown_bps)
    open_loss = 0 if exit_fees is None else open_loss_micro(book.positions, marks, exit_fees)
    unpriced = bool(book.positions) and equity is None
    halt = bool(unmarked) or unpriced or _entries_halted(book, cfg.daily_loss_bps, open_loss) or drawn
    cooled = book.cooldown_until > int(time.time())
    conflict = _account_conflict(client, book, sibling_paths) if cfg.live else None
    if halt:
        if unmarked:
            LOG.warning("daily loss halt book=%s no mark for %s", name, ",".join(unmarked))
        elif unpriced:
            LOG.warning("entry halt book=%s equity is not priced after the sell fee", name)
        elif drawn:
            LOG.warning("drawdown halt book=%s peak=%s", name, book.equity_peak_micro)
        else:
            LOG.warning("daily loss halt book=%s", name)
    if conflict:
        LOG.warning("account mismatch book=%s %s", name, conflict)
    if pending_problem:
        LOG.warning("pending order book=%s %s", name, pending_problem)
    if cooled:
        LOG.warning("stop cooldown book=%s until=%s", name, book.cooldown_until)
    if not orders_allowed:
        LOG.warning("live orders paused book=%s", name)
    if not cfg.entries:
        LOG.warning(
            "entries off book=%s: the measured rule does not beat fees and the spread",
            name,
        )
    if halt or conflict or pending_problem or cooled or not orders_allowed or not cfg.entries:
        entries, skipped = 0, 0
    else:
        deadline = time.monotonic() + CYCLE_BUDGET_SEC
        entries, skipped = _open_positions(cfg, client, book, path, name, deadline)
    save_book(path, book)
    note_heartbeat(ops_root(path), name)
    LOG.info(
        "cash=%s realized=%s fees=%s positions=%s exits=%s entries=%s skipped=%s live=%s",
        format_usdt(book.cash_micro),
        format_usdt(book.realized_micro),
        format_usdt(book.fees_micro),
        len(book.positions),
        exits,
        entries,
        skipped,
        cfg.live,
    )
    return CycleReport(exits=exits, entries=entries, skipped=skipped)


def _close_positions(
    cfg: Config,
    client: MexcClient,
    book: Book,
    path: Path,
    book_name: str,
    orders_allowed: bool,
) -> tuple[int, dict[str, int], tuple[str, ...]]:
    data_dir = ops_root(path)
    kept: list[Position] = []
    closed = 0
    marks: dict[str, int] = {}
    unmarked: list[str] = []
    for pos in list(book.positions):
        step = _lot_step(client, pos.symbol)
        dust = step is not None and not uses_slot(pos.base_atoms, step)
        try:
            bid, _ask = client.book_top(pos.symbol)
        except MexcError as exc:
            LOG.warning("book ticker failed, position kept: %s", exc)
            unmarked.append(pos.symbol)
            kept.append(pos)
            continue
        price = bid
        if not mark_ok(pos.peak_micro, price):
            LOG.warning("price refused, position kept: %s", pos.symbol)
            unmarked.append(pos.symbol)
            kept.append(pos)
            continue
        marks[pos.symbol] = price
        if price > pos.peak_micro:
            pos.peak_micro = price
        if dust:
            kept.append(pos)
            continue
        if cfg.live and book.pending_client_id:
            LOG.warning("pending %s blocks the sell of %s", book.pending_symbol, pos.symbol)
            kept.append(pos)
            continue
        stop, take, arm, gap = _risk(cfg)
        reason = exit_reason(pos.entry_micro, price, pos.peak_micro, stop, take, arm, gap)
        if reason is None and cfg.mode == "liquidity":
            try:
                bid_notional, ask_notional = client.depth_notional(pos.symbol)
            except MexcError as exc:
                LOG.warning("depth failed, position kept: %s", exc)
                kept.append(pos)
                continue
            if ask_wall_exit(bid_notional, ask_notional, pnl_bps(pos.entry_micro, price)):
                reason = "ask_wall"
        quotes = venue_quotes(pos.symbol)
        _log_oracle(pos.symbol, price, quotes, data_dir)
        if reason is None and ahead_exit(price, list(quotes.values()), pnl_bps(pos.entry_micro, price)):
            reason = "mexc_ahead"
        if reason is None:
            kept.append(pos)
            continue
        if cfg.live and not orders_allowed:
            LOG.warning("sell kept, live orders paused: %s", pos.symbol)
            kept.append(pos)
            continue
        if cfg.live:
            try:
                rule = client.symbol_rule(pos.symbol)
            except MexcError as exc:
                LOG.warning("rules %s, sell kept: %s", pos.symbol, exc)
                kept.append(pos)
                continue
            sell_atoms = round_base_atoms(pos.base_atoms, rule.base_step_atoms)
            if sell_atoms <= 0 or sell_atoms > pos.base_atoms:
                LOG.warning("sell kept, %s is below the lot", pos.symbol)
                kept.append(pos)
                continue
            try:
                _total, _free_usdt, _bases, free_bases = client.spot_balances()
            except MexcError as exc:
                LOG.warning("balance read failed, sell kept: %s", exc)
                kept.append(pos)
                continue
            if rule.base_asset != pos.symbol[:-4] or not pos.symbol.endswith("USDT"):
                LOG.warning("sell kept, %s base asset is %s", pos.symbol, rule.base_asset or "missing")
                kept.append(pos)
                continue
            if not base_is_free(free_bases.get(rule.base_asset, 0), sell_atoms):
                LOG.warning("sell kept, %s is not free", pos.symbol)
                kept.append(pos)
                continue
            client_id = new_client_order_id(pos.symbol, "S")
            remember_pending(book, client_id, pos.symbol, "SELL", sell_atoms)
            book.pending_open_base = pos.base_atoms
            book.pending_open_quote = pos.quote_micro
            save_book(path, book)
            try:
                fill = client.market_sell_base(pos.symbol, sell_atoms, client_id)
            except MexcError as exc:
                LOG.warning("sell failed, position kept: %s", exc)
                kept.append(pos)
                continue
            credit = fill.quote_micro
            fee = fill.fee_micro
            if fill.client_order_id != client_id:
                LOG.warning("sell ack client id is not the one we sent, left pending: %s", pos.symbol)
                kept.append(pos)
                continue
            if not exchange_order_id_ok(fill.exchange_order_id):
                LOG.warning("sell ack has no order id, left pending: %s", pos.symbol)
                kept.append(pos)
                continue
            book.pending_exchange_order_id = fill.exchange_order_id
            book.pending_ack_fee = fill.fee_micro
            book.pending_ack_base_fee = fill.base_fee_atoms
            save_book(path, book)
            got = _order_fees(client, pos.symbol, fill.exchange_order_id, "SELL")
            if got is None:
                kept.append(pos)
                continue
            extra, base_fee, traded_base, traded_quote = got
            if not fills_match(traded_base, traded_quote, fill.base_atoms, fill.quote_micro + fill.fee_micro):
                LOG.warning("sell trades do not match the fill, left pending: %s", pos.symbol)
                kept.append(pos)
                continue
            if not ack_fee_matches(fill.base_fee_atoms, base_fee):
                LOG.warning("sell ack base fee does not match the trades, left pending: %s", pos.symbol)
                kept.append(pos)
                continue
            if base_fee > 0:
                LOG.warning("sell fee is in the coin, left pending: %s", pos.symbol)
                kept.append(pos)
                continue
            if not ack_fee_matches(fee, extra):
                LOG.warning("sell ack fee does not match the trades, left pending: %s", pos.symbol)
                kept.append(pos)
                continue
            if fee == 0 and extra > 0:
                if not fee_fits(extra, credit):
                    LOG.warning("sell fee is above the fill, left pending: %s", pos.symbol)
                    kept.append(pos)
                    continue
                credit -= extra
                fee = extra
            gross = credit + fee
            if fill.base_atoms <= 0 or not apply_sell_progress(book, pos.symbol, fill.base_atoms, gross, fee):
                kept.append(pos)
                continue
            if any(item.symbol == pos.symbol for item in book.positions):
                kept.append(pos)
            clear_pending(book)
            mark_stop_cooldown(book, reason, cfg.stop_cooldown_sec, pos.symbol, cfg.stop_lock_count, cfg.stop_lock_sec)
            save_book(path, book)
            closed += 1
            LOG.info("exit %s %s price=%s", reason, pos.symbol, format_price(price))
            note_event(
                data_dir,
                book=book_name,
                kind="exit",
                symbol=pos.symbol,
                reason=reason,
                price=format_price(price),
            )
            continue
        try:
            rule = client.symbol_rule(pos.symbol)
            taker_bps = rule.taker_bps
            step = rule.base_step_atoms
        except MexcError as exc:
            LOG.warning("rules %s, paper sell kept: %s", pos.symbol, exc)
            kept.append(pos)
            continue
        if rule.base_asset != pos.symbol[:-4] or not pos.symbol.endswith("USDT"):
            LOG.warning("paper sell kept, %s base asset is %s", pos.symbol, rule.base_asset or "missing")
            kept.append(pos)
            continue
        sell_atoms = round_base_atoms(pos.base_atoms, step)
        if sell_atoms <= 0 or sell_atoms > pos.base_atoms:
            kept.append(pos)
            continue
        credit, fee = paper_sell(sell_atoms, price, taker_bps)
        gross = notional_micro(sell_atoms, price)
        if credit <= 0 or fee < 0 or credit + fee != gross:
            LOG.warning("paper sell credit refused, position kept: %s", pos.symbol)
            kept.append(pos)
            continue
        if not record_sell_fill(book, pos.symbol, sell_atoms, credit, fee, pos):
            kept.append(pos)
            continue
        if any(item.symbol == pos.symbol for item in book.positions):
            kept.append(pos)
        mark_stop_cooldown(book, reason, cfg.stop_cooldown_sec, pos.symbol, cfg.stop_lock_count, cfg.stop_lock_sec)
        closed += 1
        LOG.info("exit %s %s price=%s", reason, pos.symbol, format_price(price))
        note_event(
            data_dir,
            book=book_name,
            kind="exit",
            symbol=pos.symbol,
            reason=reason,
            price=format_price(price),
        )
    book.positions = kept
    return closed, marks, tuple(unmarked)


def _open_positions(
    cfg: Config,
    client: MexcClient,
    book: Book,
    path: Path,
    book_name: str,
    deadline: float,
) -> tuple[int, int]:
    data_dir = ops_root(path)
    slots = cfg.max_positions - _slots_used(client, book)
    if slots <= 0:
        return 0, 0
    held = {pos.symbol for pos in book.positions}
    if cfg.mode == "liquidity":
        return _open_liquidity(cfg, client, book, held, slots, path, book_name, deadline)
    opened = 0
    skipped = 0
    found: list[tuple[str, int, int, str]] = []
    for symbol in cfg.symbols:
        if time.monotonic() > deadline:
            LOG.warning("cycle deadline, stop scan")
            break
        if symbol in held:
            continue
        try:
            closes = client.klines(symbol)
        except MexcError as exc:
            LOG.warning("klines failed: %s", exc)
            skipped += 1
            continue
        if len(closes) < 2:
            skipped += 1
            continue
        closed = closed_prices(closes)
        if len(closed) >= 2 and not price_ok(closed[-2], closed[-1]):
            LOG.warning("skip %s close jump", symbol)
            skipped += 1
            continue
        signal = entry_signal(symbol, closed, cfg.rsi_buy)
        if signal is None:
            continue
        try:
            _bid, price = client.book_top(symbol)
        except MexcError as exc:
            LOG.warning("book ticker failed: %s", exc)
            skipped += 1
            continue
        quotes = venue_quotes(symbol)
        _log_oracle(symbol, price, quotes, data_dir)
        peers = list(quotes.values())
        if not entry_allowed(price, peers):
            LOG.info("skip %s: MEXC is ahead of the other books or they did not answer", symbol)
            skipped += 1
            continue
        lag = lag_bps(price, peers)
        if lag is None:
            skipped += 1
            continue
        found.append((symbol, lag, price, signal.reason))
    order = {symbol: index for index, symbol in enumerate(cheapest_first([(symbol, lag) for symbol, lag, _price, _reason in found]))}
    found.sort(key=lambda row: order[row[0]])
    for symbol, _lag, price, reason in found:
        if opened >= slots:
            break
        if _try_buy(cfg, client, book, path, book_name, symbol, price, reason, deadline):
            opened += 1
        else:
            skipped += 1
        if book.pending_client_id:
            LOG.warning("pending order, stop entries")
            break
    return opened, skipped


def _open_liquidity(
    cfg: Config,
    client: MexcClient,
    book: Book,
    held: set[str],
    slots: int,
    path: Path,
    book_name: str,
    deadline: float,
) -> tuple[int, int]:
    data_dir = ops_root(path)
    opened = 0
    skipped = 0
    if cfg.symbol_lock:
        symbols = list(cfg.symbols)
    else:
        try:
            symbols = [
            symbol
            for symbol in client.liquid_usdt(200_000 * SATOSHI_MULTIPLIER, 50, 1_200, 8)
            if symbol in cfg.symbols
        ]
        except MexcError as exc:
            LOG.warning("ticker scan failed: %s", exc)
            return 0, 1
    LOG.info("liquidity candidates=%s", ",".join(symbols) if symbols else "none")
    probes: dict[str, tuple[list[tuple[int, int, int, int, int]], int, int, dict[str, int]]] = {}
    wanted = [symbol for symbol in symbols if symbol not in held][:PROBE_CAP]
    for symbol in wanted:
        if time.monotonic() > deadline:
            LOG.warning("cycle deadline, stop scan")
            break
        try:
            probes[symbol] = _probe_lift(client, symbol)
        except MexcRateLimit as exc:
            LOG.warning("rate limit, stop scan: %s", exc)
            break
        except MexcError as exc:
            LOG.warning("lift check failed: %s", exc)
            skipped += 1
    ready: list[tuple[int, int, str, int, str]] = []
    for symbol in symbols:
        if symbol not in probes:
            continue
        rows, bid, ask, quotes = probes[symbol]
        peers = list(quotes.values())
        if len(rows) >= 3 and not price_ok(rows[-3][3], rows[-2][3]):
            LOG.warning("skip %s close jump", symbol)
            skipped += 1
            continue
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
        try:
            _bid, price = client.book_top(symbol)
        except MexcError as exc:
            LOG.warning("book ticker failed: %s", exc)
            skipped += 1
            continue
        _log_oracle(symbol, price, quotes, data_dir)
        if not entry_allowed(price, peers):
            LOG.info("skip %s: MEXC is ahead of the other books or they did not answer", symbol)
            skipped += 1
            continue
        dev = deviation_bps([price, *peers])
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
        lag = lag_bps(price, peers)
        if lag is None:
            skipped += 1
            continue
        reason = f"lift:{signal.volume_ratio_bps}bps"
        ready.append((points, lag, symbol, price, reason))
    ready.sort(key=lambda row: (-row[0], row[1], row[2]))
    for points, _lag, symbol, price, reason in ready:
        if opened >= slots:
            break
        if _try_buy(cfg, client, book, path, book_name, symbol, price, reason, deadline):
            opened += 1
            target = price * (10_000 + _risk(cfg)[1]) // 10_000
            LOG.info(
                "entry lift %s score=%s target=%s",
                symbol,
                points,
                format_price(target),
            )
        else:
            skipped += 1
        if book.pending_client_id:
            LOG.warning("pending order, stop entries")
            break
    return opened, skipped


def _try_buy(
    cfg: Config,
    client: MexcClient,
    book: Book,
    path: Path,
    book_name: str,
    symbol: str,
    price: int,
    reason: str,
    deadline: float,
) -> bool:
    """Buy one symbol. A live order already in flight blocks every other buy."""
    if not cfg.entries:
        LOG.info("skip %s: entries are off", symbol)
        return False
    if book.pending_client_id:
        LOG.warning("pending %s blocks %s", book.pending_symbol, symbol)
        return False
    if price <= 0 or any(pos.symbol == symbol for pos in book.positions):
        LOG.info("skip %s: already on the book or the price is not positive", symbol)
        return False
    if not price_grid_ok(price, _risk(cfg)[0]):
        LOG.info("skip %s: price step is wider than the stop", symbol)
        return False
    if symbol not in cfg.symbols:
        LOG.info("skip %s: not in the configured list", symbol)
        return False
    if pair_locked(book, symbol, int(time.time())):
        LOG.info("skip %s: pair locked after stops", symbol)
        return False
    if time.monotonic() > deadline:
        LOG.warning("cycle deadline, skip %s", symbol)
        return False
    try:
        rule = client.symbol_rule(symbol)
    except MexcError as exc:
        LOG.warning("rules %s: %s", symbol, exc)
        return False
    if not rule.tradable:
        LOG.info("skip %s: %s", symbol, rule.refuse_reason)
        return False
    if not tick_fits(price, rule.price_tick, _risk(cfg)[0]):
        LOG.info("skip %s: exchange price step is wider than the stop", symbol)
        return False
    try:
        _bid, ask = client.book_top(symbol)
    except MexcError as exc:
        LOG.warning("book ticker %s, skip buy: %s", symbol, exc)
        return False
    try:
        spread = top_spread_bps(_bid, ask)
    except ValueError:
        LOG.info("skip %s: book is crossed or empty", symbol)
        return False
    if spread_blocks(spread, cfg.spread_bps):
        LOG.info("skip %s: spread %s bps", symbol, spread)
        return False
    if ask > price:
        LOG.info("skip %s: ask moved above the checked price", symbol)
        return False
    if not tick_fits(ask, rule.price_tick, _risk(cfg)[0]):
        LOG.info("skip %s: ask step is wider than the stop", symbol)
        return False
    spend = round_quote_micro(budget_micro(book.cash_micro, cfg.alloc_bps), rule.quote_step_micro)
    if spend > book.cash_micro:
        return False
    if rule.max_quote_micro > 0:
        spend = min(spend, rule.max_quote_micro)
        spend = round_quote_micro(spend, rule.quote_step_micro)
    if spend < rule.quote_step_micro or spend < cfg.min_notional_micro:
        return False
    if cfg.live:
        try:
            _total, free_usdt, _bases, _free_bases = client.spot_balances()
        except MexcError as exc:
            LOG.warning("balance read failed, skip buy: %s", exc)
            return False
        spend = cap_spend(
            spend,
            free_usdt,
            rule.quote_step_micro,
            cfg.min_notional_micro,
            rule.max_quote_micro,
        )
        if spend <= 0:
            LOG.info("skip %s: free USDT is below the order step", symbol)
            return False
        client_id = new_client_order_id(symbol, "B")
        remember_pending(book, client_id, symbol, "BUY", 0, spend)
        save_book(path, book)
        try:
            fill = client.market_buy_quote(symbol, spend, client_id)
        except MexcError as exc:
            LOG.warning("buy failed, left pending: %s", exc)
            return False
        fee = fill.fee_micro
        if fill.client_order_id != client_id:
            LOG.warning("buy ack client id is not the one we sent, left pending: %s", symbol)
            return False
        if not exchange_order_id_ok(fill.exchange_order_id):
            LOG.warning("buy ack has no order id, left pending: %s", symbol)
            return False
        book.pending_exchange_order_id = fill.exchange_order_id
        book.pending_ack_fee = fill.fee_micro
        book.pending_ack_base_fee = fill.base_fee_atoms
        save_book(path, book)
        got = _order_fees(client, symbol, fill.exchange_order_id, "BUY")
        if got is None:
            LOG.warning("trade fee %s, buy left pending", symbol)
            return False
        fee, base_fee, traded_base, traded_quote = got
        if not fills_match(traded_base, traded_quote, fill.base_atoms, fill.quote_micro):
            LOG.warning("buy trades do not match the fill, left pending: %s", symbol)
            return False
        if not ack_fee_matches(fill.fee_micro, fee) or not ack_fee_matches(fill.base_fee_atoms, base_fee):
            LOG.warning("buy ack fee does not match the trades, left pending: %s", symbol)
            return False
        net_base = fill.base_atoms - base_fee
        if net_base <= 0:
            LOG.warning("buy fee took the fill, left pending: %s", symbol)
            return False
        room = book.cash_micro - fill.quote_micro
        if room < 0:
            LOG.warning("buy quote is above cash, left pending: %s", symbol)
            return False
        if not fee_fits(fee, room):
            LOG.warning("buy fee does not fit cash, left pending: %s", symbol)
            return False
        if not apply_buy_progress(
            book,
            symbol,
            0,
            fill.base_atoms,
            fill.quote_micro,
            fee,
            reason,
            client_id,
            fill.exchange_order_id,
            base_fee,
        ):
            LOG.warning("buy fill was not recorded, left pending: %s", symbol)
            return False
        clear_pending(book)
        save_book(path, book)
        LOG.info(
            "entry %s %s price=%s debit=%s fee=%s",
            reason,
            symbol,
            format_price(book.positions[-1].entry_micro if book.positions else 0),
            format_usdt(fill.quote_micro + fee),
            format_usdt(fee),
        )
        note_event(
            ops_root(path),
            book=book_name,
            kind="entry",
            symbol=symbol,
            reason=reason,
            price=format_price(book.positions[-1].entry_micro if book.positions else 0),
        )
        return True
    planned = plan_paper_buy(spend, ask, rule.base_step_atoms, rule.taker_bps)
    if planned is None:
        return False
    base_atoms, fee, debit = planned
    if any(item.symbol == symbol for item in book.positions):
        return False
    if base_atoms <= 0 or debit <= 0 or debit > book.cash_micro:
        return False
    book.cash_micro -= debit
    book.fees_micro += fee
    book.positions.append(
        Position(
            symbol=symbol,
            entry_micro=ask,
            peak_micro=ask,
            quote_micro=debit,
            base_atoms=base_atoms,
            reason=reason,
        )
    )
    LOG.info(
        "entry %s %s price=%s debit=%s fee_bps=%s",
        reason,
        symbol,
        format_price(ask),
        format_usdt(debit),
        rule.taker_bps,
    )
    note_event(
        ops_root(path),
        book=book_name,
        kind="entry",
        symbol=symbol,
        reason=reason,
        price=format_price(ask),
    )
    return True


def _resolve_pending(client: MexcClient, book: Book, path: Path) -> str | None:
    """Finish a live order that was sent and not yet written into the book."""
    try:
        order = client.order_by_client(book.pending_symbol, book.pending_client_id)
    except MexcError as exc:
        if order_missing(str(exc)):
            book.pending_misses += 1
            has_fill = any(pos.client_order_id == book.pending_client_id for pos in book.positions)
            if pending_gone(
                book.pending_misses,
                book.pending_applied_atoms,
                has_fill,
                bool(book.pending_exchange_order_id),
            ):
                LOG.warning("pending order is absent three times, client id cleared")
                clear_pending(book)
                save_book(path, book)
                return None
            save_book(path, book)
            LOG.warning("pending order is not visible yet, entries stay blocked")
            return str(exc)
        return str(exc)
    book.pending_misses = 0
    if not order_is_ours(order, book.pending_symbol, book.pending_side, book.pending_client_id):
        LOG.warning("pending order response is not %s %s", book.pending_side, book.pending_symbol)
        return "pending order response is not the order we sent"
    if not order_filled(order) and not order_finished(order):
        try:
            got = executed_fill(order)
        except MexcError as exc:
            return str(exc)
        if got is None:
            return f"{book.pending_side} {book.pending_symbol} status {order.get('status')}"
        base_atoms, quote_micro, price_micro = got
        over = _over_request(book, base_atoms, quote_micro)
        if over:
            return over
        if not _apply_progress(client, book, order, base_atoms, quote_micro, price_micro):
            return "pending fill was not recorded"
        save_book(path, book)
        return f"{book.pending_side} {book.pending_symbol} status {order.get('status')}"
    if not order_filled(order):
        try:
            got = executed_fill(order)
        except MexcError as exc:
            return str(exc)
        if got is None:
            if (
                book.pending_applied_atoms
                or book.pending_applied_quote
                or book.pending_applied_fee
                or book.pending_applied_base_fee
            ):
                LOG.warning("finished order reports no fill but the book already has one")
                return "pending fill disappeared"
            clear_pending(book)
            save_book(path, book)
            LOG.info("pending %s %s finished with no fill", book.pending_side, book.pending_symbol)
            return None
        base_atoms, quote_micro, price_micro = got
    else:
        try:
            base_atoms, quote_micro, price_micro = quantities_from_order(order)
        except MexcError as exc:
            return str(exc)
    over = _over_request(book, base_atoms, quote_micro)
    if over:
        return over
    if not _apply_progress(client, book, order, base_atoms, quote_micro, price_micro):
        return "pending fill was not recorded"
    side = book.pending_side
    symbol = book.pending_symbol
    clear_pending(book)
    save_book(path, book)
    LOG.info("recovered %s %s", side, symbol)
    return None


def _over_request(book: Book, base_atoms: int, quote_micro: int) -> str | None:
    """Refuse a fill larger than the order we sent. The client id stays pending."""
    if book.pending_side == "BUY" and book.pending_quote_micro > 0 and quote_micro > book.pending_quote_micro:
        return "pending buy filled more quote than requested"
    if book.pending_side == "SELL" and book.pending_base_atoms > 0 and base_atoms > book.pending_base_atoms:
        return "pending sell filled more base than requested"
    return None


def _apply_progress(
    client: MexcClient,
    book: Book,
    order: dict[str, object],
    base_atoms: int,
    quote_micro: int,
    price_micro: int,
) -> bool:
    order_id = str(order.get("orderId") or "")
    if not exchange_order_id_ok(order_id):
        LOG.warning("pending order has no exchange id")
        return False
    if book.pending_exchange_order_id and order_id != book.pending_exchange_order_id:
        LOG.warning("pending order id does not match the ack")
        return False
    book.pending_exchange_order_id = order_id
    got = _order_fees(client, book.pending_symbol, order_id, book.pending_side)
    if got is None:
        return False
    fee, base_fee, traded_base, traded_quote = got
    if book.pending_ack_fee is not None and not ack_fee_matches(book.pending_ack_fee, fee):
        LOG.warning("stored ack fee does not match the trades")
        return False
    if book.pending_ack_base_fee is not None and not ack_fee_matches(book.pending_ack_base_fee, base_fee):
        LOG.warning("stored ack base fee does not match the trades")
        return False
    if not fills_match(traded_base, traded_quote, base_atoms, quote_micro):
        LOG.warning("recovered trades do not match the order")
        return False
    if book.pending_side == "BUY":
        room = book.cash_micro + book.pending_applied_quote + book.pending_applied_fee
        if quote_micro > room:
            return False
        if not fee_fits(fee, room - quote_micro):
            LOG.warning("recovered buy fee does not fit cash")
            return False
        net_base = base_atoms - base_fee
        if net_base <= 0:
            LOG.warning("recovered buy fee took the fill")
            return False
        try:
            price_micro = implied_price_micro(quote_micro, net_base)
        except MoneyError as exc:
            LOG.warning("recovered buy has no price: %s", exc)
            return False
        return apply_buy_progress(
            book,
            book.pending_symbol,
            price_micro,
            base_atoms,
            quote_micro,
            fee,
            "recovered",
            book.pending_client_id,
            order_id,
            base_fee,
        )
    if book.pending_side == "SELL":
        if base_fee > 0:
            LOG.warning("sell fee is in the coin")
            return False
        if not fee_fits(fee, quote_micro):
            LOG.warning("recovered sell fee is above the fill")
            return False
        return apply_sell_progress(book, book.pending_symbol, base_atoms, quote_micro, fee)
    return False


def _order_fees(
    client: MexcClient, symbol: str, order_id: str, side: str
) -> tuple[int, int, int, int] | None:
    """USDT fee and base-asset fee. None when the fee cannot be priced."""
    if not symbol.endswith("USDT") or len(symbol) <= 4:
        LOG.warning("fee asset unknown for %s", symbol)
        return None
    try:
        trades = client.my_trades(symbol, order_id=order_id)
        return split_commission(trades, order_id, symbol[:-4], side)
    except (MexcError, FeeAssetError) as exc:
        LOG.warning("trade fee %s: %s", symbol, exc)
        return None


def sibling_pending(paths: tuple[Path, ...]) -> str | None:
    """A client id on another book of this account. One exchange order at a time."""
    for path in paths:
        if not path.exists():
            continue
        other = load_book(path, 0)
        if other.pending_client_id:
            return f"{path.stem} pending {other.pending_symbol or 'unknown'}"
    return None


def _sibling_positions(paths: tuple[Path, ...]) -> list[tuple[str, int]]:
    """Open coins in the other books. Those files are the source of truth."""
    rows: list[tuple[str, int]] = []
    for path in paths:
        if not path.exists():
            continue
        other = load_book(path, 0)
        rows.extend((pos.symbol, pos.base_atoms) for pos in other.positions)
    return rows


def _account_conflict(client: MexcClient, book: Book, sibling_paths: tuple[Path, ...] = ()) -> str | None:
    try:
        _usdt, _free, bases, _free_bases = client.spot_balances()
    except MexcError as exc:
        return str(exc)
    positions = [(pos.symbol, pos.base_atoms) for pos in book.positions]
    return inventory_mismatch(positions, bases, _sibling_positions(sibling_paths))


def _exit_fees(client: MexcClient, book: Book) -> dict[str, int] | None:
    """Taker rate for each open coin. None when a rate cannot be read."""
    fees: dict[str, int] = {}
    for pos in book.positions:
        try:
            rule = client.symbol_rule(pos.symbol)
        except MexcError:
            return None
        if rule.taker_bps < 0:
            return None
        fees[pos.symbol] = rule.taker_bps
    return fees


def _lot_step(client: MexcClient, symbol: str) -> int | None:
    try:
        return client.symbol_rule(symbol).base_step_atoms
    except MexcError:
        return None


def _slots_used(client: MexcClient, book: Book) -> int:
    """Positions large enough to sell. An unknown lot still occupies the slot."""
    used = 0
    for pos in book.positions:
        step = _lot_step(client, pos.symbol)
        if step is None or uses_slot(pos.base_atoms, step):
            used += 1
    return used


def _clock_ok(client: MexcClient) -> bool:
    """False when the exchange clock cannot be read or the local clock is too far."""
    try:
        server_ms = client.server_time_ms()
    except MexcError as exc:
        LOG.warning("server time unread, live orders paused: %s", exc)
        return False
    if clock_allows(int(time.time() * 1000), server_ms, CLOCK_SKEW_MS):
        return True
    LOG.warning("clock skew against MEXC, live orders paused")
    return False


def mark_stop_cooldown(
    book: Book,
    reason: str,
    seconds: int,
    symbol: str = "",
    lock_count: int = 3,
    lock_sec: int = 14_400,
) -> None:
    """A stop blocks the next entry. Take-profit and trail do not. Repeated stops lock the pair."""
    if reason != "stop":
        return
    if seconds > 0:
        book.cooldown_until = int(time.time()) + seconds
    if symbol:
        note_pair_stop(book, symbol, int(time.time()), lock_count, lock_sec)


def open_loss_micro(
    positions: list[Position], marks: dict[str, int], taker_bps: dict[str, int] | None = None
) -> int:
    """How far open positions sit below their cost. Gains are not subtracted.

    With taker rates the value is the bid after the sell fee.
    """
    loss = 0
    for pos in positions:
        price = marks.get(pos.symbol, 0)
        if price <= 0 or pos.base_atoms <= 0:
            continue
        gross = notional_micro(pos.base_atoms, price)
        if taker_bps is None:
            value = gross
        else:
            bps = taker_bps.get(pos.symbol)
            if bps is None:
                continue
            credit, fee = paper_sell(pos.base_atoms, price, bps)
            if credit < 0 or fee < 0 or credit + fee != gross:
                continue
            value = credit
        if value < pos.quote_micro:
            loss += pos.quote_micro - value
    return loss


def _roll_guard(book: Book) -> None:
    """Stamp morning cash before today's exits. A later loss still counts against it."""
    today = date.today().isoformat()
    if book.guard_day == today:
        return
    book.guard_day = today
    book.guard_realized_micro = book.realized_micro
    book.guard_cash_micro = book.cash_micro


def _entries_halted(book: Book, daily_loss_bps: int, open_loss: int = 0) -> bool:
    _roll_guard(book)
    if daily_loss_bps <= 0:
        return False
    drop = book.guard_realized_micro - book.realized_micro
    if drop < 0:
        drop = 0
    if open_loss < 0:
        open_loss = 0
    if book.guard_cash_micro <= 0:
        return drop + open_loss > 0
    return drop + open_loss >= book.guard_cash_micro * daily_loss_bps // 10_000


def _probe_lift(
    client: MexcClient, symbol: str
) -> tuple[list[tuple[int, int, int, int, int]], int, int, dict[str, int]]:
    rows = client.ohlcv(symbol, "5m", 20)
    bid, ask = client.depth_notional(symbol)
    return rows, bid, ask, venue_quotes(symbol)


def _risk(cfg: Config) -> tuple[int, int, int, int]:
    if cfg.mode == "liquidity":
        return 150, 250, 120, 80
    return cfg.stop_bps, cfg.take_bps, cfg.trail_arm_bps, cfg.trail_gap_bps


def _log_oracle(symbol: str, mexc_micro: int, quotes: dict[str, int], data_dir: Path | None = None) -> None:
    peers = list(quotes.values())
    lag = lag_bps(mexc_micro, peers)
    width = deviation_bps([mexc_micro, *peers])
    binance = format_price(quotes["binance"]) if "binance" in quotes else "-"
    bybit = format_price(quotes["bybit"]) if "bybit" in quotes else "-"
    okx = format_price(quotes["okx"]) if "okx" in quotes else "-"
    LOG.info(
        "oracle %s mexc=%s binance=%s bybit=%s okx=%s lag_bps=%s width_bps=%s",
        symbol,
        format_price(mexc_micro),
        binance,
        bybit,
        okx,
        "-" if lag is None else lag,
        "-" if width is None else width,
    )
    if data_dir is not None:
        note_quote(data_dir, symbol, format_price(mexc_micro), binance, bybit, okx, lag, width)
