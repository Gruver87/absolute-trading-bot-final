"""Integer satoshi for quote USDT.

Same scale as experimental ``runtime/amount.py``: ``ABS_DECIMALS = 6``,
``SATOSHI_MULTIPLIER = 1_000_000``. Decimal is used only to read an exchange
string. Float and bool are refused. This package does not import the chain.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_DOWN

SATOSHI_MULTIPLIER = 1_000_000
BASE_ATOMS = 100_000_000
MICRO = SATOSHI_MULTIPLIER


class MoneyError(ValueError):
    """Rejected amount."""


def to_satoshi(amount: object) -> int:
    """Floor a decimal string to integer satoshi. Float and bool are refused."""
    if isinstance(amount, bool) or isinstance(amount, float):
        raise MoneyError("float and bool amounts are refused")
    if isinstance(amount, int):
        return amount
    if not isinstance(amount, str):
        raise MoneyError(f"amount must be a decimal string, got {type(amount).__name__}")
    raw = amount.strip()
    if not raw:
        raise MoneyError("empty amount")
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise MoneyError(f"not a decimal: {amount}") from exc
    if not value.is_finite():
        raise MoneyError("amount must be finite")
    scaled = (value * Decimal(SATOSHI_MULTIPLIER)).to_integral_value(rounding=ROUND_DOWN)
    return int(scaled)


def parse_micro(text: str) -> int:
    """Positive quote amount in satoshi."""
    sat = to_satoshi(text)
    if sat <= 0:
        raise MoneyError(f"amount must be positive: {text}")
    return sat


def parse_micro_nonneg(text: str) -> int:
    sat = to_satoshi(text)
    if sat < 0:
        raise MoneyError(f"amount must be >= 0: {text}")
    return sat


def format_fixed(amount: int, scale: int) -> str:
    """Render an integer scaled amount without binary float."""
    if isinstance(amount, bool) or amount < 0 or scale <= 1:
        raise MoneyError("wire amount must be a non-negative int")
    digits = 0
    rest = scale
    while rest > 1:
        rest //= 10
        digits += 1
    whole, frac = divmod(int(amount), scale)
    text = f"{whole}.{frac:0{digits}d}".rstrip("0").rstrip(".")
    return text if text else "0"


def format_usdt(micro: int) -> str:
    sign = "-" if micro < 0 else ""
    whole, frac = divmod(abs(int(micro)), SATOSHI_MULTIPLIER)
    return f"{sign}{whole}.{frac:06d}"
