"""Taker fee in integer satoshi. Standard MEXC spot taker is 5 bps per side.

Paper fills use this. A live fill is whatever the exchange reports; this module
does not add a second fee on top of an exchange debit.
"""

from __future__ import annotations

from spotbot.money import MoneyError, _MAX_AMOUNT, base_for_quote, notional_micro

STANDARD_TAKER_BPS = 5


def fee_on(notional_micro: int, taker_bps: int) -> int:
    if (
        isinstance(notional_micro, bool)
        or isinstance(taker_bps, bool)
        or not isinstance(notional_micro, int)
        or not isinstance(taker_bps, int)
    ):
        raise ValueError("notional and fee must be integers")
    if notional_micro < 0 or notional_micro >= _MAX_AMOUNT or taker_bps < 0 or taker_bps > 100:
        raise ValueError("notional and fee must be >= 0")
    return notional_micro * taker_bps // 10_000


def paper_buy(spend_micro: int, price_micro: int, taker_bps: int) -> tuple[int, int]:
    """Spend quote. Return base atoms bought and the fee taken from quote."""
    if (
        isinstance(spend_micro, bool)
        or isinstance(price_micro, bool)
        or isinstance(taker_bps, bool)
        or not isinstance(spend_micro, int)
        or not isinstance(price_micro, int)
        or not isinstance(taker_bps, int)
    ):
        return 0, 0
    if price_micro <= 0 or spend_micro <= 0 or price_micro >= _MAX_AMOUNT or spend_micro >= _MAX_AMOUNT or taker_bps > 100:
        return 0, 0
    fee = fee_on(spend_micro, taker_bps)
    net = spend_micro - fee
    if net <= 0:
        return 0, fee
    return base_for_quote(net, price_micro), fee


def paper_sell(base_atoms: int, price_micro: int, taker_bps: int) -> tuple[int, int]:
    """Return quote credited after fee, and the fee."""
    if (
        isinstance(base_atoms, bool)
        or isinstance(price_micro, bool)
        or isinstance(taker_bps, bool)
        or not isinstance(base_atoms, int)
        or not isinstance(price_micro, int)
        or not isinstance(taker_bps, int)
    ):
        return 0, 0
    if base_atoms <= 0 or price_micro <= 0 or base_atoms >= _MAX_AMOUNT or price_micro >= _MAX_AMOUNT or taker_bps > 100:
        return 0, 0
    try:
        gross = notional_micro(base_atoms, price_micro)
    except MoneyError:
        return 0, 0
    fee = fee_on(gross, taker_bps)
    return gross - fee, fee
