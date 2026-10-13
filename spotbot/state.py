"""Ledger on disk. Paper and live are different files and must not be mixed."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from spotbot.money import MoneyError, implied_price_micro

_CLIENT_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def client_id_ok(value: str) -> bool:
    """MEXC client ids are 1–32 letters, digits, underscores, or hyphens."""
    return _CLIENT_ID.fullmatch(value) is not None


def exchange_order_id_ok(value: str) -> bool:
    """An exchange order id, when the ack has one, is a digit string."""
    return value.isdigit() and 1 <= len(value) <= 32


@dataclass
class Position:
    symbol: str
    entry_micro: int
    peak_micro: int
    quote_micro: int
    base_atoms: int
    reason: str
    client_order_id: str = ""
    exchange_order_id: str = ""

    def to_json(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_json(cls, raw: dict[str, object]) -> "Position":
        if not isinstance(raw, dict):
            raise LedgerError("position is not an object")
        return cls(
            symbol=str(raw["symbol"]),
            entry_micro=_as_int(raw["entry_micro"], "entry_micro"),
            peak_micro=_as_int(raw["peak_micro"], "peak_micro"),
            quote_micro=_as_int(raw["quote_micro"], "quote_micro"),
            base_atoms=_as_int(raw["base_atoms"], "base_atoms"),
            reason=str(raw["reason"]),
            client_order_id=str(raw.get("client_order_id") or ""),
            exchange_order_id=str(raw.get("exchange_order_id") or ""),
        )


@dataclass
class Book:
    cash_micro: int
    positions: list[Position]
    realized_micro: int
    fees_micro: int = 0
    guard_day: str = ""
    guard_realized_micro: int = 0
    guard_cash_micro: int = 0
    pending_client_id: str = ""
    pending_symbol: str = ""
    pending_side: str = ""
    pending_base_atoms: int = 0
    pending_quote_micro: int = 0
    pending_applied_atoms: int = 0
    pending_applied_quote: int = 0
    pending_applied_fee: int = 0
    pending_applied_base_fee: int = 0
    pending_misses: int = 0
    cooldown_until: int = 0
    ledger: str = ""
    credited_main_micro: int | None = None
    pending_ack_fee: int | None = None
    pending_ack_base_fee: int | None = None
    pending_open_base: int = 0
    pending_open_quote: int = 0
    pending_exchange_order_id: str = ""
    equity_peak_micro: int = 0
    pair_stops: dict[str, list[int]] | None = None
    pair_lock_until: dict[str, int] | None = None
    price_scale: int = 0

    def to_json(self) -> dict[str, object]:
        body: dict[str, object] = {
            "cash_micro": self.cash_micro,
            "realized_micro": self.realized_micro,
            "fees_micro": self.fees_micro,
            "guard_day": self.guard_day,
            "guard_realized_micro": self.guard_realized_micro,
            "guard_cash_micro": self.guard_cash_micro,
            "pending_client_id": self.pending_client_id,
            "pending_symbol": self.pending_symbol,
            "pending_side": self.pending_side,
            "pending_base_atoms": self.pending_base_atoms,
            "pending_quote_micro": self.pending_quote_micro,
            "pending_applied_atoms": self.pending_applied_atoms,
            "pending_applied_quote": self.pending_applied_quote,
            "pending_applied_fee": self.pending_applied_fee,
            "pending_applied_base_fee": self.pending_applied_base_fee,
            "pending_misses": self.pending_misses,
            "pending_open_base": self.pending_open_base,
            "pending_open_quote": self.pending_open_quote,
            "pending_exchange_order_id": self.pending_exchange_order_id,
            "cooldown_until": self.cooldown_until,
            "ledger": self.ledger,
            "equity_peak_micro": self.equity_peak_micro,
            "pair_stops": self.pair_stops or {},
            "pair_lock_until": self.pair_lock_until or {},
            "price_scale": self.price_scale or 1_000_000_000_000,
            "positions": [pos.to_json() for pos in self.positions],
        }
        if self.credited_main_micro is not None:
            body["credited_main_micro"] = self.credited_main_micro
        if self.pending_ack_fee is not None:
            body["pending_ack_fee"] = self.pending_ack_fee
        if self.pending_ack_base_fee is not None:
            body["pending_ack_base_fee"] = self.pending_ack_base_fee
        return body


def _as_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LedgerError(f"{label} is not an integer")
    return value


def _pair_stops(raw: object) -> dict[str, list[int]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise LedgerError("pair stops are not an object")
    out: dict[str, list[int]] = {}
    for key, value in raw.items():
        if not isinstance(value, list):
            raise LedgerError("pair stop times are not a list")
        out[str(key)] = [_as_int(item, "pair stop") for item in value]
    return out


def _pair_locks(raw: object) -> dict[str, int]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise LedgerError("pair locks are not an object")
    return {str(key): _as_int(value, "pair lock") for key, value in raw.items()}


def load_book(path: Path, paper_cash_micro: int) -> Book:
    if not path.exists():
        return Book(cash_micro=paper_cash_micro, positions=[], realized_micro=0, fees_micro=0)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise LedgerError("book is not an object")
    rows = raw.get("positions", [])
    if not isinstance(rows, list):
        raise LedgerError("positions are not a list")
    positions = [Position.from_json(item) for item in rows]
    if "price_scale" not in raw:
        for pos in positions:
            pos.entry_micro *= 1_000_000
            pos.peak_micro *= 1_000_000
    elif _as_int(raw.get("price_scale"), "price_scale") != 1_000_000_000_000:
        raise LedgerError("price scale is not the coin price scale")
    book = Book(
        cash_micro=_as_int(raw["cash_micro"], "cash_micro"),
        positions=positions,
        realized_micro=_as_int(raw.get("realized_micro", 0), "realized_micro"),
        fees_micro=_as_int(raw.get("fees_micro", 0), "fees_micro"),
        guard_day=str(raw.get("guard_day") or ""),
        guard_realized_micro=_as_int(raw.get("guard_realized_micro", 0), "guard_realized_micro"),
        guard_cash_micro=_as_int(raw.get("guard_cash_micro", 0), "guard_cash_micro"),
        pending_client_id=str(raw.get("pending_client_id") or ""),
        pending_symbol=str(raw.get("pending_symbol") or ""),
        pending_side=str(raw.get("pending_side") or ""),
        pending_base_atoms=_as_int(raw.get("pending_base_atoms", 0), "pending_base_atoms"),
        pending_quote_micro=_as_int(raw.get("pending_quote_micro", 0), "pending_quote_micro"),
        pending_applied_atoms=_as_int(raw.get("pending_applied_atoms", 0), "pending_applied_atoms"),
        pending_applied_quote=_as_int(raw.get("pending_applied_quote", 0), "pending_applied_quote"),
        pending_applied_fee=_as_int(raw.get("pending_applied_fee", 0), "pending_applied_fee"),
        pending_applied_base_fee=_as_int(raw.get("pending_applied_base_fee", 0), "pending_applied_base_fee"),
        pending_misses=_as_int(raw.get("pending_misses", 0), "pending_misses"),
        pending_open_base=_as_int(raw.get("pending_open_base", 0), "pending_open_base"),
        pending_open_quote=_as_int(raw.get("pending_open_quote", 0), "pending_open_quote"),
        pending_exchange_order_id=str(raw.get("pending_exchange_order_id") or ""),
        cooldown_until=_as_int(raw.get("cooldown_until", 0), "cooldown_until"),
        ledger=str(raw.get("ledger") or ""),
        equity_peak_micro=_as_int(raw.get("equity_peak_micro", 0), "equity_peak_micro"),
        pair_stops=_pair_stops(raw.get("pair_stops")),
        pair_lock_until=_pair_locks(raw.get("pair_lock_until")),
        price_scale=1_000_000_000_000,
        credited_main_micro=_as_int(raw["credited_main_micro"], "credited_main_micro") if "credited_main_micro" in raw else None,
        pending_ack_fee=_as_int(raw["pending_ack_fee"], "pending_ack_fee") if "pending_ack_fee" in raw else None,
        pending_ack_base_fee=_as_int(raw["pending_ack_base_fee"], "pending_ack_base_fee") if "pending_ack_base_fee" in raw else None,
    )
    audit_book(book)
    return book


class LedgerError(RuntimeError):
    """Paper file and live file were about to be used as one book."""


def _sell_remainder_ok(book: Book, symbol: str) -> bool:
    """A partial sell still holds the unsold base. A finished size may have no row."""
    if book.pending_open_base <= 0:
        return True
    left = book.pending_open_base - book.pending_applied_atoms
    rows = [pos for pos in book.positions if pos.symbol == symbol]
    if left < 0:
        return False
    if left == 0:
        return not rows
    return len(rows) == 1 and rows[0].base_atoms == left


def _audit_pair_map(stops: dict[str, list[int]], locks: dict[str, int]) -> None:
    for symbol, stamps in stops.items():
        _audit_pair_symbol(symbol)
        if len(stamps) > 8:
            raise LedgerError("pair stop list is too long")
        for stamp in stamps:
            if stamp < 0 or stamp > 4_102_444_800:
                raise LedgerError("pair stop is not a timestamp")
    for symbol, until in locks.items():
        _audit_pair_symbol(symbol)
        if until < 0 or until > 4_102_444_800:
            raise LedgerError("pair lock is not a timestamp")


def _audit_pair_symbol(symbol: str) -> None:
    if not symbol.endswith("USDT") or len(symbol) <= 4 or not symbol[:-4].isalnum() or not symbol[:-4].isupper():
        raise LedgerError(f"{symbol or 'missing'} is not a USDT pair")


def audit_book(book: Book) -> None:
    """Refuse a file that must not send an order. Realized loss may be negative."""
    if book.cash_micro < 0 or book.fees_micro < 0 or book.guard_cash_micro < 0:
        raise LedgerError("book cash is negative")
    if book.pending_side not in ("", "BUY", "SELL"):
        raise LedgerError("pending side is not buy or sell")
    if book.pending_client_id and (not book.pending_symbol or not book.pending_side):
        raise LedgerError("pending client id has no order")
    if book.pending_client_id and not client_id_ok(book.pending_client_id):
        raise LedgerError("pending client id is not an exchange id")
    if book.pending_exchange_order_id and not exchange_order_id_ok(book.pending_exchange_order_id):
        raise LedgerError("pending exchange order id is not digits")
    if book.pending_client_id and (not book.pending_symbol.endswith("USDT") or len(book.pending_symbol) <= 4):
        raise LedgerError("pending symbol is not a USDT pair")
    if not book.pending_client_id and (
        book.pending_applied_atoms
        or book.pending_applied_quote
        or book.pending_applied_fee
        or book.pending_applied_base_fee
    ):
        raise LedgerError("applied fill has no client id")
    for label, amount in (
        ("pending base", book.pending_base_atoms),
        ("pending quote", book.pending_quote_micro),
        ("applied base", book.pending_applied_atoms),
        ("applied quote", book.pending_applied_quote),
        ("applied fee", book.pending_applied_fee),
        ("applied base fee", book.pending_applied_base_fee),
        ("pending misses", book.pending_misses),
        ("open base", book.pending_open_base),
        ("open quote", book.pending_open_quote),
        ("cooldown", book.cooldown_until),
    ):
        if amount < 0:
            raise LedgerError(f"{label} is negative")
    if book.cooldown_until > 4_102_444_800:
        raise LedgerError("cooldown is not a timestamp")
    if book.equity_peak_micro < 0:
        raise LedgerError("equity peak is negative")
    _audit_pair_map(book.pair_stops or {}, book.pair_lock_until or {})
    if book.credited_main_micro is not None and book.credited_main_micro < 0:
        raise LedgerError("credited main is negative")
    if book.pending_ack_fee is not None and book.pending_ack_fee < 0:
        raise LedgerError("ack fee is negative")
    if book.pending_ack_base_fee is not None and book.pending_ack_base_fee < 0:
        raise LedgerError("ack base fee is negative")
    if book.pending_applied_fee > book.pending_applied_quote:
        raise LedgerError("booked fee is above the fill")
    if book.pending_client_id and book.pending_side == "BUY":
        if book.pending_quote_micro <= 0:
            raise LedgerError("buy has no requested quote")
        if book.pending_applied_quote > book.pending_quote_micro:
            raise LedgerError("buy fill is above the request")
    if book.pending_client_id and book.pending_side == "SELL":
        if book.pending_base_atoms <= 0:
            raise LedgerError("sell has no requested size")
        if book.pending_applied_atoms > book.pending_base_atoms:
            raise LedgerError("sell fill is above the request")
    if book.pending_open_base > 0 and book.pending_side != "SELL":
        raise LedgerError("sell size is stored on a buy")
    seen_symbols: set[str] = set()
    seen_clients: set[str] = set()
    seen_orders: set[str] = set()
    for pos in book.positions:
        if not pos.symbol.endswith("USDT") or len(pos.symbol) <= 4:
            raise LedgerError(f"{pos.symbol or 'missing'} is not a USDT pair")
        if pos.symbol in seen_symbols:
            raise LedgerError(f"{pos.symbol} is on the book twice")
        seen_symbols.add(pos.symbol)
        if pos.base_atoms <= 0 or pos.quote_micro < 0 or pos.entry_micro <= 0 or pos.peak_micro <= 0:
            raise LedgerError(f"{pos.symbol} size or price is not positive")
        if pos.peak_micro < pos.entry_micro:
            raise LedgerError(f"{pos.symbol} peak is below the entry")
        if book.pending_side == "SELL" and book.pending_client_id and pos.client_order_id == book.pending_client_id:
            raise LedgerError("sell client id is already on a position")
        if (
            book.pending_side == "SELL"
            and book.pending_exchange_order_id
            and pos.exchange_order_id == book.pending_exchange_order_id
        ):
            raise LedgerError("sell exchange id is already on a position")
        if pos.client_order_id:
            if not client_id_ok(pos.client_order_id):
                raise LedgerError("client id is not an exchange id")
            if pos.client_order_id in seen_clients:
                raise LedgerError("client id is on the book twice")
            seen_clients.add(pos.client_order_id)
        if pos.exchange_order_id:
            if not exchange_order_id_ok(pos.exchange_order_id):
                raise LedgerError("exchange order id is not digits")
            if pos.exchange_order_id in seen_orders:
                raise LedgerError("exchange order id is on the book twice")
            seen_orders.add(pos.exchange_order_id)
    if book.pending_side == "BUY" and (
        book.pending_applied_atoms or book.pending_applied_quote or book.pending_applied_base_fee
    ):
        if not _buy_fill_held(book, book.pending_client_id, book.pending_symbol):
            raise LedgerError("buy fill is not on the book")
    if book.pending_side == "SELL" and book.pending_open_base > 0:
        if not _sell_remainder_ok(book, book.pending_symbol):
            raise LedgerError("sell remainder is not on the book")


def bind_ledger(book: Book, live: bool) -> None:
    """Stamp the book. A live process refuses a paper book and an unmarked book that already holds a coin."""
    expected = "live" if live else "paper"
    if book.ledger not in ("", expected):
        raise LedgerError(f"book is {book.ledger}, this process is {expected}")
    if live and book.ledger == "" and book.positions:
        raise LedgerError("refusing live orders against an unmarked book that already holds a coin")
    book.ledger = expected


def write_atomic(path: Path, text: str) -> None:
    """Replace the file only after the new bytes are flushed. A crash keeps the previous file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def save_book(path: Path, book: Book) -> None:
    """Write only a book that load would accept. A refused book leaves the previous file."""
    audit_book(book)
    write_atomic(path, json.dumps(book.to_json(), indent=2))


def clear_pending(book: Book) -> None:
    book.pending_client_id = ""
    book.pending_symbol = ""
    book.pending_side = ""
    book.pending_base_atoms = 0
    book.pending_quote_micro = 0
    book.pending_applied_atoms = 0
    book.pending_applied_quote = 0
    book.pending_applied_fee = 0
    book.pending_applied_base_fee = 0
    book.pending_misses = 0
    book.pending_open_base = 0
    book.pending_open_quote = 0
    book.pending_exchange_order_id = ""
    book.pending_ack_fee = None
    book.pending_ack_base_fee = None


def remember_pending(
    book: Book, client_id: str, symbol: str, side: str, base_atoms: int, quote_micro: int = 0
) -> None:
    """Store a new client id. An id already on the book is left as it was."""
    if (
        book.pending_client_id
        or book.pending_applied_atoms
        or book.pending_applied_quote
        or book.pending_applied_fee
        or book.pending_applied_base_fee
    ):
        raise LedgerError("refusing to replace a live client id")
    if not client_id or not symbol or side not in ("BUY", "SELL"):
        raise LedgerError("pending order needs a client id, symbol, and side")
    if not client_id_ok(client_id):
        raise LedgerError("pending client id is not an exchange id")
    if not symbol.endswith("USDT") or len(symbol) <= 4:
        raise LedgerError("pending symbol is not a USDT pair")
    book.pending_client_id = client_id
    book.pending_symbol = symbol
    book.pending_side = side
    book.pending_base_atoms = base_atoms
    book.pending_quote_micro = quote_micro
    book.pending_applied_atoms = 0
    book.pending_applied_quote = 0
    book.pending_applied_fee = 0
    book.pending_applied_base_fee = 0
    book.pending_misses = 0
    book.pending_open_base = 0
    book.pending_open_quote = 0
    book.pending_exchange_order_id = ""
    book.pending_ack_fee = None
    book.pending_ack_base_fee = None


def _buy_fill_held(book: Book, client_order_id: str, symbol: str) -> bool:
    """True when the one row for this client id still holds the net coins already booked."""
    rows = [
        pos
        for pos in book.positions
        if pos.client_order_id == client_order_id and pos.symbol == symbol
    ]
    if len(rows) != 1:
        return False
    net = book.pending_applied_atoms - book.pending_applied_base_fee
    cost = book.pending_applied_quote + book.pending_applied_fee
    if net <= 0 or rows[0].base_atoms != net or rows[0].quote_micro != cost:
        return False
    try:
        price = implied_price_micro(book.pending_applied_quote, net)
    except MoneyError:
        return False
    if book.pending_exchange_order_id and rows[0].exchange_order_id != book.pending_exchange_order_id:
        return False
    return rows[0].entry_micro == price and rows[0].peak_micro >= rows[0].entry_micro


def record_buy(
    book: Book,
    symbol: str,
    price_micro: int,
    base_atoms: int,
    quote_micro: int,
    fee_micro: int,
    reason: str,
    client_order_id: str,
    exchange_order_id: str,
) -> bool:
    """Debit quote and fee once. A repeated client id or a second row of the same pair does not debit again."""
    if not client_id_ok(client_order_id) or not exchange_order_id_ok(exchange_order_id):
        return False
    if not symbol.endswith("USDT") or len(symbol) <= 4:
        return False
    if any(pos.client_order_id == client_order_id for pos in book.positions):
        return False
    if any(pos.symbol == symbol for pos in book.positions):
        return False
    debit = quote_micro + fee_micro
    if debit <= 0 or base_atoms <= 0 or debit > book.cash_micro:
        return False
    book.cash_micro -= debit
    book.fees_micro += fee_micro
    book.positions.append(
        Position(
            symbol=symbol,
            entry_micro=price_micro,
            peak_micro=price_micro,
            quote_micro=debit,
            base_atoms=base_atoms,
            reason=reason,
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
        )
    )
    return True


def apply_buy_progress(
    book: Book,
    symbol: str,
    price_micro: int,
    base_atoms: int,
    quote_micro: int,
    fee_micro: int,
    reason: str,
    client_order_id: str,
    exchange_order_id: str,
    base_fee_atoms: int = 0,
) -> bool:
    """Move the book forward to the latest buy fill. Base commission is not kept as coins."""
    if (
        book.pending_side != "BUY"
        or book.pending_client_id != client_order_id
        or book.pending_symbol != symbol
        or not client_id_ok(client_order_id)
        or not exchange_order_id_ok(exchange_order_id)
        or (book.pending_exchange_order_id != "" and book.pending_exchange_order_id != exchange_order_id)
    ):
        return False
    if book.pending_quote_micro <= 0 or quote_micro > book.pending_quote_micro or fee_micro > quote_micro:
        return False
    if (
        base_atoms < book.pending_applied_atoms
        or quote_micro < book.pending_applied_quote
        or fee_micro < book.pending_applied_fee
        or base_fee_atoms < book.pending_applied_base_fee
    ):
        return False
    net_base = base_atoms - base_fee_atoms
    same = (
        base_atoms == book.pending_applied_atoms
        and quote_micro == book.pending_applied_quote
        and fee_micro == book.pending_applied_fee
        and base_fee_atoms == book.pending_applied_base_fee
    )
    if same:
        if book.pending_applied_atoms or book.pending_applied_quote or book.pending_applied_base_fee:
            return _buy_fill_held(book, client_order_id, symbol)
        return True
    if net_base <= 0:
        return False
    try:
        price_micro = implied_price_micro(quote_micro, net_base)
    except MoneyError:
        return False
    delta_quote = quote_micro - book.pending_applied_quote
    delta_fee = fee_micro - book.pending_applied_fee
    delta_net = (base_atoms - book.pending_applied_atoms) - (base_fee_atoms - book.pending_applied_base_fee)
    rows = [pos for pos in book.positions if pos.client_order_id == client_order_id]
    if len(rows) > 1:
        return False
    existing = rows[0] if rows else None
    if existing is not None and (existing.symbol != symbol or existing.exchange_order_id not in ("", exchange_order_id)):
        return False
    if existing is None:
        if book.pending_applied_atoms or book.pending_applied_quote or book.pending_applied_base_fee:
            return False
        if delta_net <= 0 or not record_buy(
            book, symbol, price_micro, net_base, quote_micro, fee_micro, reason, client_order_id, exchange_order_id
        ):
            return False
    else:
        debit = delta_quote + delta_fee
        already = book.pending_applied_atoms - book.pending_applied_base_fee
        booked = book.pending_applied_quote + book.pending_applied_fee
        if (
            existing.base_atoms != already
            or existing.quote_micro != booked
            or debit > book.cash_micro
            or existing.base_atoms + delta_net <= 0
        ):
            return False
        book.cash_micro -= debit
        book.fees_micro += delta_fee
        existing.base_atoms += delta_net
        existing.quote_micro += debit
        old_entry = existing.entry_micro
        existing.entry_micro = price_micro
        if existing.peak_micro <= old_entry or price_micro > existing.peak_micro:
            existing.peak_micro = price_micro
    book.pending_applied_atoms = base_atoms
    book.pending_applied_quote = quote_micro
    book.pending_applied_fee = fee_micro
    book.pending_applied_base_fee = base_fee_atoms
    return True


def apply_sell_progress(
    book: Book,
    symbol: str,
    sold_atoms: int,
    quote_micro: int,
    fee_micro: int,
) -> bool:
    """Move the book forward to the latest sell fill. Only the new part is credited."""
    if book.pending_side != "SELL" or book.pending_symbol != symbol:
        return False
    if quote_micro <= 0 or book.pending_base_atoms <= 0 or sold_atoms > book.pending_base_atoms or fee_micro > quote_micro:
        return False
    for pos in book.positions:
        if pos.symbol != symbol:
            continue
        if pos.client_order_id and pos.client_order_id == book.pending_client_id:
            return False
        if book.pending_exchange_order_id and pos.exchange_order_id == book.pending_exchange_order_id:
            return False
    if (
        sold_atoms < book.pending_applied_atoms
        or quote_micro < book.pending_applied_quote
        or fee_micro < book.pending_applied_fee
    ):
        return False
    if book.pending_open_base > 0 and not _sell_remainder_ok(book, symbol):
        return False
    if (
        sold_atoms == book.pending_applied_atoms
        and quote_micro == book.pending_applied_quote
        and fee_micro == book.pending_applied_fee
    ):
        return True
    delta_base = sold_atoms - book.pending_applied_atoms
    delta_quote = quote_micro - book.pending_applied_quote
    delta_fee = fee_micro - book.pending_applied_fee
    if delta_base == 0 and delta_quote == 0:
        if delta_fee > book.cash_micro:
            return False
        book.cash_micro -= delta_fee
        book.fees_micro += delta_fee
        book.realized_micro -= delta_fee
        book.pending_applied_fee = fee_micro
        return True
    credit = delta_quote - delta_fee
    if credit < 0 or not record_sell_fill(book, symbol, delta_base, credit, delta_fee):
        return False
    book.pending_applied_atoms = sold_atoms
    book.pending_applied_quote = quote_micro
    book.pending_applied_fee = fee_micro
    return True


def record_sell(book: Book, symbol: str, credit_micro: int, fee_micro: int) -> bool:
    """Credit the quote fill and drop the whole position. Fee is already outside the credit."""
    for pos in book.positions:
        if pos.symbol == symbol:
            return record_sell_fill(book, symbol, pos.base_atoms, credit_micro, fee_micro)
    return False


def record_sell_fill(
    book: Book,
    symbol: str,
    sold_atoms: int,
    credit_micro: int,
    fee_micro: int,
    hold: Position | None = None,
) -> bool:
    """Credit a sell. A partial fill keeps the unsold base on the position.

    Two rows of the same pair are not guessed. Pass the row that was sent.
    """
    if sold_atoms <= 0 or credit_micro < 0 or fee_micro < 0:
        return False
    matches = [pos for pos in book.positions if pos.symbol == symbol]
    if hold is not None:
        if not any(pos is hold for pos in matches):
            return False
        pos = hold
    elif len(matches) != 1:
        return False
    else:
        pos = matches[0]
    if sold_atoms > pos.base_atoms:
        return False
    released = pos.quote_micro if sold_atoms == pos.base_atoms else pos.quote_micro * sold_atoms // pos.base_atoms
    book.cash_micro += credit_micro
    book.fees_micro += fee_micro
    book.realized_micro += credit_micro - released
    if sold_atoms == pos.base_atoms:
        book.positions = [item for item in book.positions if item is not pos]
    else:
        pos.base_atoms -= sold_atoms
        pos.quote_micro -= released
    return True
