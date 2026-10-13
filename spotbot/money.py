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
# One coin's price. 1e-12 USDT. Cash stays at 1e-6. A SHIB tick fits inside a 3.5% stop.
PRICE_SCALE = 1_000_000_000_000
_PRICE_PER_MICRO = PRICE_SCALE // SATOSHI_MULTIPLIER


class MoneyError(ValueError):
    """Rejected amount."""


def decimal_text(raw: object) -> str:
    """A decimal the exchange sent as text. A JSON float is binary and is refused.

    An int is exact, so it is accepted. A bool is not an int here. An exponent
    is not a decimal: ``1e-7`` is not a price.
    """
    if isinstance(raw, bool) or isinstance(raw, float):
        raise MoneyError("float and bool amounts are refused")
    if isinstance(raw, int):
        return str(raw)
    if not isinstance(raw, str):
        raise MoneyError(f"amount must be a decimal string, got {type(raw).__name__}")
    return _plain_decimal(raw)


def _plain_decimal(text: str) -> str:
    raw = text.strip()
    if not raw:
        raise MoneyError("empty amount")
    if any(ch in raw for ch in "eE"):
        raise MoneyError("exponent is not a decimal")
    return raw


def to_satoshi(amount: object) -> int:
    """Floor a decimal string to integer satoshi. Float and bool are refused."""
    if isinstance(amount, bool) or isinstance(amount, float):
        raise MoneyError("float and bool amounts are refused")
    if isinstance(amount, int):
        return amount
    if not isinstance(amount, str):
        raise MoneyError(f"amount must be a decimal string, got {type(amount).__name__}")
    raw = _plain_decimal(amount)
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
    if isinstance(amount, bool) or isinstance(scale, bool) or not isinstance(amount, int) or not isinstance(scale, int) or amount < 0 or scale <= 1:
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
    if isinstance(micro, bool) or not isinstance(micro, int):
        raise MoneyError("usdt amount must be an integer")
    sign = "-" if micro < 0 else ""
    whole, frac = divmod(abs(int(micro)), SATOSHI_MULTIPLIER)
    return f"{sign}{whole}.{frac:06d}"


def parse_price(text: str) -> int:
    """Price of one coin in 1e-12 USDT. Floors. Float and bool are refused."""
    if isinstance(text, bool) or isinstance(text, float) or not isinstance(text, str):
        raise MoneyError("price must be a decimal string")
    raw = _plain_decimal(text)
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise MoneyError(f"not a decimal: {text}") from exc
    if not value.is_finite() or value <= 0:
        raise MoneyError(f"price must be positive: {text}")
    scaled = (value * Decimal(PRICE_SCALE)).to_integral_value(rounding=ROUND_DOWN)
    if scaled <= 0:
        raise MoneyError(f"price rounds to zero: {text}")
    return int(scaled)


def decimal_zero(text: str) -> bool:
    """True when the text is a decimal zero. A non-decimal is not zero."""
    if not isinstance(text, str):
        return False
    raw = text.strip()
    if not raw or any(ch in raw for ch in "eE"):
        return False
    try:
        return Decimal(raw) == 0
    except InvalidOperation:
        return False


def format_price(price: int) -> str:
    """Render a coin price. This is not a cash balance."""
    if isinstance(price, bool) or not isinstance(price, int) or price < 0:
        raise MoneyError("price must be a non-negative int")
    return format_fixed(price, PRICE_SCALE)


def notional_micro(base_atoms: int, price: int) -> int:
    """Quote cash for a coin amount at this price. Both must be integers."""
    if isinstance(base_atoms, bool) or isinstance(price, bool) or not isinstance(base_atoms, int) or not isinstance(price, int):
        raise MoneyError("notional refuses a bool")
    if base_atoms < 0 or price <= 0:
        raise MoneyError("notional needs a positive price and a base that is not negative")
    return base_atoms * price // (BASE_ATOMS * _PRICE_PER_MICRO)


def base_for_quote(quote_micro: int, price: int) -> int:
    """Base atoms bought by quote_micro at this price, before the lot step."""
    if isinstance(quote_micro, bool) or isinstance(price, bool) or not isinstance(quote_micro, int) or not isinstance(price, int) or quote_micro <= 0 or price <= 0:
        return 0
    return quote_micro * _PRICE_PER_MICRO * BASE_ATOMS // price


def implied_price_micro(quote_micro: int, base_atoms: int) -> int:
    """Average fill in the price scale. Not the ticker before the order."""
    if isinstance(quote_micro, bool) or isinstance(base_atoms, bool) or not isinstance(quote_micro, int) or not isinstance(base_atoms, int) or quote_micro <= 0 or base_atoms <= 0:
        raise MoneyError("fill price needs a positive quote and base")
    return quote_micro * _PRICE_PER_MICRO * BASE_ATOMS // base_atoms
