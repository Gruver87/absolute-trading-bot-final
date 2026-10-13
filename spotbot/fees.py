"""Taker fee in integer satoshi. Standard MEXC spot taker is 5 bps per side.

Paper fills use this. A live fill is whatever the exchange reports; this module
does not add a second fee on top of an exchange debit.
"""

from __future__ import annotations

from spotbot.money import base_for_quote, notional_micro

STANDARD_TAKER_BPS = 5


def fee_on(notional_micro: int, taker_bps: int) -> int:
    if isinstance(notional_micro, bool) or isinstance(taker_bps, bool):
        raise ValueError("notional and fee must be integers")
    if notional_micro < 0 or taker_bps < 0:
        raise ValueError("notional and fee must be >= 0")
    return notional_micro * taker_bps // 10_000


def paper_buy(spend_micro: int, price_micro: int, taker_bps: int) -> tuple[int, int]:
    """Spend quote. Return base atoms bought and the fee taken from quote."""
    if price_micro <= 0 or spend_micro <= 0:
        return 0, 0
    fee = fee_on(spend_micro, taker_bps)
    net = spend_micro - fee
    if net <= 0:
        return 0, fee
    return base_for_quote(net, price_micro), fee


def paper_sell(base_atoms: int, price_micro: int, taker_bps: int) -> tuple[int, int]:
    """Return quote credited after fee, and the fee."""
    if base_atoms <= 0 or price_micro <= 0:
        return 0, 0
    gross = notional_micro(base_atoms, price_micro)
    fee = fee_on(gross, taker_bps)
    return gross - fee, fee
