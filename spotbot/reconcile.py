"""Compare an open book with a spot account snapshot. Does not place orders."""

from __future__ import annotations


def inventory_mismatch(
    positions: list[tuple[str, int]],
    bases_atoms: dict[str, int],
    elsewhere: list[tuple[str, int]] | None = None,
) -> str | None:
    """None when every open base matches the account and the account has no extra coin.

    USDT is not compared: quote fees and open orders move it without a base fill.
    `elsewhere` is other books of this same bot on the same account, such as the
    other sleeves. Their coins are part of the expected total.
    """
    from spotbot.state import usdt_symbol_ok

    if len(positions) > 8 or len(elsewhere or []) > 64:
        return "too many coins"
    held: dict[str, int] = {}
    seen: set[str] = set()
    for symbol, atoms in [*positions, *(elsewhere or [])]:
        if not isinstance(symbol, str):
            return "pair name is not text"
        if len(symbol) > 32:
            return "pair name is too long"
        if symbol in seen:
            return f"{symbol} is listed twice"
        seen.add(symbol)
        if isinstance(atoms, bool) or not isinstance(atoms, int):
            return f"{symbol} base is not an integer"
        if atoms < 0:
            return f"{symbol} base is negative"
        if atoms >= 10**24:
            return f"{symbol} base is too large"
        if not usdt_symbol_ok(symbol):
            return f"{symbol} is not a USDT pair"
        asset = symbol[: -4]
        held[asset] = atoms
    for asset, need in held.items():
        have = bases_atoms.get(asset, 0)
        if isinstance(have, int) and not isinstance(have, bool) and (have < 0 or have >= 10**24):
            return "exchange balance is too large"
        if isinstance(have, bool) or not isinstance(have, int) or have != need:
            return f"{asset} exchange {have} != book {need}"
    for asset, have in bases_atoms.items():
        if not isinstance(asset, str) or len(asset) > 32:
            return "exchange asset is not text"
        if isinstance(have, bool) or not isinstance(have, int):
            return f"exchange {asset} is not an integer"
        if have < 0:
            return "exchange balance is negative"
        if have >= 10**24:
            return "exchange balance is too large"
        if have > 0 and asset not in held:
            return f"exchange holds {asset} and the book does not"
    return None


def base_is_free(free_atoms: int, need_atoms: int) -> bool:
    """A sell needs the whole position free. Locked coins stay on the book."""
    if isinstance(free_atoms, bool) or not isinstance(free_atoms, int) or isinstance(need_atoms, bool) or not isinstance(need_atoms, int):
        return False
    if free_atoms < 0 or free_atoms >= 10**24 or need_atoms <= 0 or need_atoms >= 10**24:
        return False
    return need_atoms > 0 and free_atoms >= need_atoms


def _status_name(body: object) -> str:
    """Order status text. A float is not status 2, and a non-object is not filled."""
    if not isinstance(body, dict):
        return ""
    status = body.get("status")
    if isinstance(status, str):
        return status if len(status) <= 32 else ""
    if isinstance(status, bool) or isinstance(status, float) or not isinstance(status, int):
        return ""
    if status < 0 or status > 9:
        return ""
    return str(status)


def order_filled(body: dict[str, object]) -> bool:
    return _status_name(body) in ("FILLED", "2")


def order_finished(body: dict[str, object]) -> bool:
    """The exchange will not fill this order further. A partial fill may already exist."""
    return _status_name(body) in ("CANCELED", "PARTIALLY_CANCELED", "4", "5")


def _has_code(text: str, code: str) -> bool:
    """True when the code is a whole token. -20110 is not -2011."""
    start = 0
    while True:
        at = text.find(code, start)
        if at < 0:
            return False
        end = at + len(code)
        before = at == 0 or not text[at - 1].isdigit()
        after = end == len(text) or not text[end].isdigit()
        if before and after:
            return True
        start = at + 1


def order_missing(message: str) -> bool:
    """True only for an unknown order. A missing symbol or balance is not that."""
    if not isinstance(message, str) or len(message) > 512:
        return False
    text = message.lower()
    if "order does not exist" in text or "unknown order" in text:
        return True
    return _has_code(text, "-2011") or _has_code(text, "-2013")


def pending_gone(misses: int, applied_atoms: int, has_fill: bool, acked: bool = False) -> bool:
    """Clear a client id only after repeated absences, with no fill and no ack.

    An exchange order id already on the book means the order was accepted.
    "Order does not exist" does not erase that.
    """
    if isinstance(misses, bool) or not isinstance(misses, int) or isinstance(applied_atoms, bool) or not isinstance(applied_atoms, int):
        return False
    if not isinstance(has_fill, bool) or not isinstance(acked, bool):
        return False
    return misses >= 3 and applied_atoms == 0 and not has_fill and not acked


def fills_match(traded_base: int, traded_quote: int, order_base: int, order_quote: int) -> bool:
    """True when the trade rows add up to the order fill. A short list is not a full fee."""
    nums = (traded_base, traded_quote, order_base, order_quote)
    if any(isinstance(item, bool) or not isinstance(item, int) for item in nums):
        return False
    if any(item >= 10**24 for item in nums):
        return False
    return traded_base == order_base and traded_quote == order_quote and order_base > 0 and order_quote > 0


def ack_fee_matches(ack_fee_micro: int, trade_fee_micro: int) -> bool:
    """A fee named on the order ack must equal the trade rows. Zero means the ack omitted it."""
    if isinstance(ack_fee_micro, bool) or not isinstance(ack_fee_micro, int) or isinstance(trade_fee_micro, bool) or not isinstance(trade_fee_micro, int):
        return False
    if ack_fee_micro < 0 or trade_fee_micro < 0 or ack_fee_micro >= 10**24 or trade_fee_micro >= 10**24:
        return False
    return ack_fee_micro == 0 or ack_fee_micro == trade_fee_micro


def fee_fits(fee_micro: int, room_micro: int) -> bool:
    """A known fee is booked in full. It is not trimmed to fit the cash or the fill."""
    if isinstance(fee_micro, bool) or not isinstance(fee_micro, int) or isinstance(room_micro, bool) or not isinstance(room_micro, int):
        return False
    if fee_micro >= 10**24 or room_micro >= 10**24:
        return False
    return fee_micro >= 0 and room_micro >= fee_micro


def order_is_ours(body: dict[str, object], symbol: str, side: str, client_id: str) -> bool:
    """True only when the ack is the symbol, side, and client id we sent."""
    if not isinstance(body, dict) or not isinstance(symbol, str) or not isinstance(side, str) or not isinstance(client_id, str):
        return False
    if len(symbol) > 32 or len(side) > 8 or len(client_id) > 32:
        return False
    if not symbol or not side or not client_id:
        return False
    ids: list[str] = []
    for key in ("clientOrderId", "origClientOrderId", "newClientOrderId"):
        got = body.get(key)
        if got in (None, ""):
            continue
        if not isinstance(got, str) or len(got) > 32:
            return False
        ids.append(got)
    if not ids or any(item != client_id for item in ids):
        return False
    got_symbol = body.get("symbol")
    got_side = body.get("side")
    got_type = body.get("type")
    if not isinstance(got_symbol, str) or not isinstance(got_side, str) or not isinstance(got_type, str):
        return False
    if len(got_symbol) > 32 or len(got_side) > 8 or len(got_type) > 16:
        return False
    return ids[0] == client_id and got_symbol == symbol and got_side.upper() == side.upper() and got_type.upper() == "MARKET"


class FeeAssetError(ValueError):
    """Commission is in an asset the book cannot turn into USDT or the traded coin."""


def split_commission(
    trades: list[object], order_id: str, base_asset: str, side: str
) -> tuple[int, int, int, int]:
    """USDT fee, base fee, and the base and quote those rows actually traded.

    Each row needs its own id, a positive quantity, a positive price, and the
    same side as the order. Price times qty must land within one micro-USDT of
    quoteQty. A repeated id is not a second fill. The caller must match the
    totals to the order before booking the fee.
    """
    if not isinstance(order_id, str) or not isinstance(base_asset, str) or not isinstance(side, str):
        raise FeeAssetError("commission needs an order, a base asset, and a side")
    if not order_id or not base_asset or side not in ("BUY", "SELL"):
        raise FeeAssetError("commission needs an order, a base asset, and a side")
    if not order_id.isdigit() or len(order_id) > 32:
        raise FeeAssetError("trade order id is not digits")
    if len(base_asset) > 10 or not base_asset.isalnum() or not base_asset.isupper():
        raise FeeAssetError("commission base asset is not a coin name")
    if len(trades) > 5_000:
        raise FeeAssetError("trade list is too large")
    from spotbot.money import (
        BASE_ATOMS,
        MICRO,
        MoneyError,
        decimal_text,
        decimal_zero,
        notional_micro,
        parse_micro,
        parse_micro_nonneg,
        parse_price,
        to_satoshi,
    )

    want_buyer = side == "BUY"
    usdt = 0
    base = 0
    traded_base = 0
    traded_quote = 0
    seen = False
    seen_ids: set[str] = set()
    for row in trades:
        if not isinstance(row, dict):
            continue
        order_raw = row.get("orderId")
        if order_raw in (None, ""):
            continue
        if not isinstance(order_raw, str):
            raise FeeAssetError("trade order id is not digits")
        if order_raw != order_id:
            continue
        seen = True
        got_symbol = row.get("symbol")
        if not isinstance(got_symbol, str) or got_symbol != f"{base_asset}USDT":
            raise FeeAssetError("trade symbol is not the order symbol")
        trade_raw = row.get("id")
        if not isinstance(trade_raw, str):
            raise FeeAssetError("trade id is not digits")
        trade_id = trade_raw
        if not trade_id.isdigit() or len(trade_id) > 32:
            raise FeeAssetError("trade id is not digits")
        if trade_id in seen_ids:
            raise FeeAssetError("trade id is repeated")
        seen_ids.add(trade_id)
        if row.get("isBuyer") is not want_buyer:
            raise FeeAssetError("trade side is not the order side")
        qty = row.get("qty")
        quote = row.get("quoteQty")
        if qty in (None, "") or quote in (None, ""):
            raise FeeAssetError("trade row has no qty")
        try:
            row_base = to_satoshi(decimal_text(qty)) * (BASE_ATOMS // MICRO)
            row_quote = parse_micro(decimal_text(quote))
        except MoneyError as exc:
            raise FeeAssetError("trade qty is not decimal") from exc
        if row_base <= 0 or row_quote <= 0:
            raise FeeAssetError("trade qty is zero")
        price_raw = row.get("price")
        if price_raw in (None, ""):
            raise FeeAssetError("trade row has no price")
        try:
            row_price = parse_price(decimal_text(price_raw))
        except MoneyError as exc:
            raise FeeAssetError("trade price is not decimal") from exc
        if row_price <= 0:
            raise FeeAssetError("trade price is zero")
        priced = notional_micro(row_base, row_price)
        if abs(priced - row_quote) > 1:
            raise FeeAssetError("trade price does not match qty")
        traded_base += row_base
        traded_quote += row_quote
        if traded_base >= 10**24 or traded_quote >= 10**24 or usdt >= 10**24 or base >= 10**24:
            raise FeeAssetError("trade total is too large")
        commission = row.get("commission")
        if commission in (None, ""):
            continue
        asset_raw = row.get("commissionAsset")
        if not isinstance(asset_raw, str) or not asset_raw:
            raise FeeAssetError("commission asset is missing")
        asset = asset_raw.upper()
        try:
            raw = decimal_text(commission)
        except MoneyError as exc:
            raise FeeAssetError("commission is not decimal") from exc
        if raw in ("", "0", "0.0", "0.00") or decimal_zero(raw):
            continue
        if asset == "USDT":
            try:
                got_fee = parse_micro_nonneg(raw)
            except MoneyError as exc:
                raise FeeAssetError("USDT commission is not decimal") from exc
            if got_fee <= 0:
                raise FeeAssetError("USDT commission rounds to zero")
            usdt += got_fee
            continue
        if asset == base_asset:
            try:
                atoms = to_satoshi(raw) * (BASE_ATOMS // MICRO)
            except MoneyError as exc:
                raise FeeAssetError(f"{base_asset} commission is not decimal") from exc
            if atoms <= 0:
                raise FeeAssetError(f"{base_asset} commission rounds to zero")
            base += atoms
            continue
        raise FeeAssetError(f"commission asset {asset or 'missing'}")
    if not seen:
        raise FeeAssetError("order has no trade row")
    if traded_base <= 0 or traded_quote <= 0:
        raise FeeAssetError("trade qty is zero")
    if traded_base >= 10**24 or traded_quote >= 10**24 or usdt >= 10**24 or base >= 10**24:
        raise FeeAssetError("trade total is too large")
    return usdt, base, traded_base, traded_quote


def usdt_commission(trades: list[object], order_id: str) -> int:
    """Sum USDT commission rows for one exchange order. Other assets are ignored."""
    if not isinstance(order_id, str) or not order_id or len(order_id) > 32:
        return 0
    if len(trades) > 5_000:
        raise FeeAssetError("trade list is too large")
    from spotbot.money import MoneyError, decimal_text, parse_micro_nonneg

    total = 0
    for row in trades:
        if not isinstance(row, dict):
            continue
        order_raw = row.get("orderId")
        if not isinstance(order_raw, str) or order_raw != order_id:
            continue
        asset_raw = row.get("commissionAsset")
        if not isinstance(asset_raw, str) or asset_raw.upper() != "USDT":
            continue
        commission = row.get("commission")
        if commission in (None, ""):
            continue
        total += parse_micro_nonneg(decimal_text(commission))
        if total >= 10**24:
            raise FeeAssetError("trade total is too large")
    return total
