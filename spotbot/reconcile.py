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
    held: dict[str, int] = {}
    for symbol, atoms in [*positions, *(elsewhere or [])]:
        if atoms < 0:
            return f"{symbol} base is negative"
        if not symbol.endswith("USDT") or len(symbol) <= 4:
            return f"{symbol} is not a USDT pair"
        asset = symbol[: -4]
        held[asset] = held.get(asset, 0) + atoms
    for asset, need in held.items():
        have = bases_atoms.get(asset, 0)
        if have != need:
            return f"{asset} exchange {have} != book {need}"
    for asset, have in bases_atoms.items():
        if have > 0 and asset not in held:
            return f"exchange holds {asset} and the book does not"
    return None


def base_is_free(free_atoms: int, need_atoms: int) -> bool:
    """A sell needs the whole position free. Locked coins stay on the book."""
    return need_atoms > 0 and free_atoms >= need_atoms


def order_filled(body: dict[str, object]) -> bool:
    return str(body.get("status") or "") in ("FILLED", "2")


def order_finished(body: dict[str, object]) -> bool:
    """The exchange will not fill this order further. A partial fill may already exist."""
    return str(body.get("status") or "") in ("CANCELED", "PARTIALLY_CANCELED", "4", "5")


def order_missing(message: str) -> bool:
    text = message.lower()
    return "not exist" in text or "-2013" in text or "unknown order" in text


def pending_gone(misses: int, applied_atoms: int, has_fill: bool) -> bool:
    """Clear a client id only after repeated absences and no recorded fill."""
    return misses >= 3 and applied_atoms == 0 and not has_fill


def fills_match(traded_base: int, traded_quote: int, order_base: int, order_quote: int) -> bool:
    """True when the trade rows add up to the order fill. A short list is not a full fee."""
    return traded_base == order_base and traded_quote == order_quote and order_base > 0 and order_quote > 0


def ack_fee_matches(ack_fee_micro: int, trade_fee_micro: int) -> bool:
    """A fee named on the order ack must equal the trade rows. Zero means the ack omitted it."""
    if ack_fee_micro < 0 or trade_fee_micro < 0:
        return False
    return ack_fee_micro == 0 or ack_fee_micro == trade_fee_micro


def fee_fits(fee_micro: int, room_micro: int) -> bool:
    """A known fee is booked in full. It is not trimmed to fit the cash or the fill."""
    return fee_micro >= 0 and room_micro >= fee_micro


def order_is_ours(body: dict[str, object], symbol: str, side: str, client_id: str) -> bool:
    """True only when the ack is the symbol, side, and client id we sent."""
    if not symbol or not side or not client_id:
        return False
    got_client = str(
        body.get("clientOrderId") or body.get("origClientOrderId") or body.get("newClientOrderId") or ""
    )
    got_symbol = str(body.get("symbol") or "")
    got_side = str(body.get("side") or "").upper()
    got_type = str(body.get("type") or "").upper()
    return got_client == client_id and got_symbol == symbol and got_side == side.upper() and got_type == "MARKET"


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
    if not order_id or not base_asset or side not in ("BUY", "SELL"):
        raise FeeAssetError("commission needs an order, a base asset, and a side")
    if not order_id.isdigit() or len(order_id) > 32:
        raise FeeAssetError("trade order id is not digits")
    from spotbot.money import BASE_ATOMS, MICRO, MoneyError, parse_micro, parse_micro_nonneg, to_satoshi

    want_buyer = side == "BUY"
    usdt = 0
    base = 0
    traded_base = 0
    traded_quote = 0
    seen = False
    seen_ids: set[str] = set()
    for row in trades:
        if not isinstance(row, dict) or str(row.get("orderId") or "") != order_id:
            continue
        seen = True
        got_symbol = str(row.get("symbol") or "")
        if got_symbol and got_symbol != f"{base_asset}USDT":
            raise FeeAssetError("trade symbol is not the order symbol")
        trade_id = str(row.get("id") or "")
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
            row_base = to_satoshi(str(qty)) * (BASE_ATOMS // MICRO)
            row_quote = parse_micro(str(quote))
        except MoneyError as exc:
            raise FeeAssetError("trade qty is not decimal") from exc
        if row_base <= 0 or row_quote <= 0:
            raise FeeAssetError("trade qty is zero")
        price_raw = row.get("price")
        if price_raw in (None, ""):
            raise FeeAssetError("trade row has no price")
        try:
            row_price = parse_micro(str(price_raw))
        except MoneyError as exc:
            raise FeeAssetError("trade price is not decimal") from exc
        if row_price <= 0:
            raise FeeAssetError("trade price is zero")
        priced = row_price * row_base // BASE_ATOMS
        if abs(priced - row_quote) > 1:
            raise FeeAssetError("trade price does not match qty")
        traded_base += row_base
        traded_quote += row_quote
        asset = str(row.get("commissionAsset") or "").upper()
        raw = str(row.get("commission") or "0")
        if raw.strip() in ("", "0", "0.0", "0.00"):
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
    return usdt, base, traded_base, traded_quote


def usdt_commission(trades: list[object], order_id: str) -> int:
    """Sum USDT commission rows for one exchange order. Other assets are ignored."""
    if not order_id:
        return 0
    from spotbot.money import parse_micro_nonneg

    total = 0
    for row in trades:
        if not isinstance(row, dict) or str(row.get("orderId") or "") != order_id:
            continue
        if str(row.get("commissionAsset") or "").upper() != "USDT":
            continue
        total += parse_micro_nonneg(str(row.get("commission") or "0"))
    return total
