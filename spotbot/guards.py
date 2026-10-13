"""Entry refusals that are not a new signal.

Drawdown is measured from the high-water equity of this book. A pair lock
counts stops on that symbol only. The spread check is one book ticker, not a socket.
"""

from __future__ import annotations

from spotbot.fees import paper_sell
from spotbot.money import notional_micro
from spotbot.state import Book, Position

STOP_LOOKBACK_SEC = 86_400
_MAX_STAMPS = 8


def marked_equity(
    cash_micro: int,
    positions: list[Position],
    marks: dict[str, int],
    taker_bps: dict[str, int] | None = None,
) -> int | None:
    """Cash plus each open coin.

    With taker rates, the coin is the bid after the sell fee. A missing mark
    or a missing rate refuses the number. Without rates the mark is the gross bid.
    """
    equity = cash_micro
    for pos in positions:
        price = marks.get(pos.symbol, 0)
        if price <= 0 or pos.base_atoms <= 0:
            return None
        gross = notional_micro(pos.base_atoms, price)
        if taker_bps is None:
            equity += gross
            continue
        bps = taker_bps.get(pos.symbol)
        if bps is None:
            return None
        credit, fee = paper_sell(pos.base_atoms, price, bps)
        if credit < 0 or fee < 0 or credit + fee != gross:
            return None
        equity += credit
    return equity


def drawdown_blocks(peak_micro: int, equity_micro: int, bps: int) -> bool:
    """True when the drop from the stored peak is at least bps of that peak."""
    if bps <= 0 or peak_micro <= 0 or equity_micro < 0 or equity_micro >= peak_micro:
        return False
    return (peak_micro - equity_micro) * 10_000 >= peak_micro * bps


def note_pair_stop(book: Book, symbol: str, now: int, count: int, lock_sec: int) -> None:
    """Remember one stop. The lock starts only after enough stops inside the lookback."""
    if now < 0 or count < 2 or not symbol.endswith("USDT") or len(symbol) <= 4:
        return
    fresh = [stamp for stamp in (book.pair_stops or {}).get(symbol, []) if now - STOP_LOOKBACK_SEC < stamp <= now]
    fresh.append(now)
    stops = dict(book.pair_stops or {})
    stops[symbol] = fresh[-_MAX_STAMPS:]
    book.pair_stops = stops
    if lock_sec > 0 and len(stops[symbol]) >= count:
        locks = dict(book.pair_lock_until or {})
        locks[symbol] = now + lock_sec
        book.pair_lock_until = locks


def pair_locked(book: Book, symbol: str, now: int) -> bool:
    """True while this symbol's stop lock is still in the future."""
    return (book.pair_lock_until or {}).get(symbol, 0) > now


def top_spread_bps(bid_micro: int, ask_micro: int) -> int:
    """Bid to ask in basis points. A crossed or empty book is refused."""
    if bid_micro <= 0 or ask_micro < bid_micro:
        raise ValueError("book is crossed or empty")
    return (ask_micro - bid_micro) * 10_000 // bid_micro


def spread_blocks(spread_bps: int, limit_bps: int) -> bool:
    """A non-positive limit or a spread wider than the limit refuses the buy."""
    if limit_bps <= 0 or spread_bps < 0:
        return True
    return spread_bps > limit_bps
