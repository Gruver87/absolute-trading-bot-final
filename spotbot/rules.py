"""Per-symbol rules from MEXC exchangeInfo. No network in this module.

A pair is tradable when spot is enabled, it is not an ST tag, and it is not
on an assessment plate. The taker fee is the symbol's own rate.
"""

from __future__ import annotations

from dataclasses import dataclass

from spotbot.fees import fee_on
from spotbot.money import (
    BASE_ATOMS,
    MICRO,
    PRICE_SCALE,
    MoneyError,
    base_for_quote,
    decimal_text,
    notional_micro,
    parse_micro,
    parse_micro_nonneg,
    to_satoshi,
)


class RuleError(ValueError):
    """exchangeInfo row cannot be used."""


@dataclass(frozen=True)
class SymbolRule:
    symbol: str
    tradable: bool
    refuse_reason: str
    taker_bps: int
    base_step_atoms: int
    quote_step_micro: int
    max_quote_micro: int
    base_asset: str = ""
    price_tick: int = 1


def _nested_wide(value: object, depth: int = 0) -> bool:
    """A filter inside the pair row is a small object. A nested bomb is not a rule."""
    if depth > 6:
        return True
    if isinstance(value, dict):
        return len(value) > 32 or any(_nested_wide(item, depth + 1) for item in value.values())
    if isinstance(value, list):
        return len(value) > 64 or any(_nested_wide(item, depth + 1) for item in value)
    return False


def parse_symbol_rule(row: dict[str, object]) -> SymbolRule:
    if not isinstance(row, dict):
        raise RuleError("exchangeInfo row is not an object")
    if len(row) > 128:
        raise RuleError("exchangeInfo row is too wide")
    if any(isinstance(value, list) and len(value) > 64 for value in row.values()):
        raise RuleError("exchangeInfo list is too long")
    if any(_nested_wide(value) for value in row.values()):
        raise RuleError("exchangeInfo value is too wide")
    symbol = row.get("symbol")
    if not isinstance(symbol, str) or not symbol:
        raise RuleError("exchangeInfo row has no symbol")
    taker_bps = _taker_bps(row.get("takerCommission"))
    step, step_reason = _step_atoms(row.get("baseSizePrecision"))
    market_quote = row.get("quoteAmountPrecisionMarket")
    if market_quote not in (None, ""):
        quote_step, quote_reason = _quote_step(market_quote)
    else:
        quote_step, quote_reason = _quote_step(row.get("quoteAmountPrecision"))
    max_quote = _max_quote(row.get("maxQuoteAmountMarket"))
    tick, tick_reason = _price_tick(row.get("quotePrecision"))
    reason = (
        _refuse_reason(row)
        or step_reason
        or quote_reason
        or tick_reason
        or _max_quote_reason(row.get("maxQuoteAmountMarket"))
    )
    base = row.get("baseAsset")
    return SymbolRule(
        symbol, reason == "", reason, taker_bps, step, quote_step, max_quote, base if isinstance(base, str) else "", tick
    )


def round_base_atoms(atoms: int, step_atoms: int) -> int:
    if isinstance(atoms, bool) or isinstance(step_atoms, bool) or not isinstance(atoms, int) or not isinstance(step_atoms, int) or atoms <= 0 or step_atoms <= 0:
        return 0
    if atoms >= 10**24 or step_atoms >= 10**24:
        return 0
    return atoms // step_atoms * step_atoms


def uses_slot(base_atoms: int, step_atoms: int) -> bool:
    """Dust below the lot stays on the book and does not block a new entry."""
    if isinstance(base_atoms, bool) or isinstance(step_atoms, bool) or not isinstance(base_atoms, int) or not isinstance(step_atoms, int):
        return True
    if base_atoms >= 10**24 or step_atoms >= 10**24:
        return True
    return round_base_atoms(base_atoms, step_atoms) > 0


def round_quote_micro(amount_micro: int, step_micro: int) -> int:
    """Floor the quote spend to the market minimum step from exchangeInfo."""
    if isinstance(amount_micro, bool) or isinstance(step_micro, bool) or not isinstance(amount_micro, int) or not isinstance(step_micro, int) or amount_micro <= 0 or step_micro <= 0:
        return 0
    if amount_micro >= 10**24 or step_micro >= 10**24:
        return 0
    return amount_micro // step_micro * step_micro


def budget_micro(cash_micro: int, alloc_bps: int) -> int:
    """Quote the book may spend. An allocation above the whole cash spends nothing."""
    if isinstance(cash_micro, bool) or isinstance(alloc_bps, bool) or not isinstance(cash_micro, int) or not isinstance(alloc_bps, int) or cash_micro <= 0 or alloc_bps < 1 or alloc_bps > 10_000:
        return 0
    if cash_micro >= 10**24:
        return 0
    return cash_micro * alloc_bps // 10_000


def cap_spend(
    budget_micro: int,
    free_micro: int,
    step_micro: int,
    min_micro: int,
    max_micro: int,
) -> int:
    """Spend the smaller of the book budget and free quote. Locked quote is not free."""
    nums = (budget_micro, free_micro, step_micro, min_micro, max_micro)
    if any(isinstance(item, bool) or not isinstance(item, int) for item in nums) or budget_micro <= 0 or free_micro < 0 or step_micro <= 0 or min_micro < 0:
        return 0
    if budget_micro >= 10**24 or free_micro >= 10**24 or step_micro >= 10**24 or min_micro >= 10**24 or max_micro >= 10**24:
        return 0
    spend = budget_micro if budget_micro < free_micro else free_micro
    if max_micro > 0 and spend > max_micro:
        spend = max_micro
    spend = round_quote_micro(spend, step_micro)
    if spend < step_micro or spend < min_micro:
        return 0
    return spend


def plan_paper_buy(
    spend_micro: int,
    price_micro: int,
    step_atoms: int,
    taker_bps: int,
) -> tuple[int, int, int] | None:
    """Return base atoms, fee, and cash debit. Fee comes out of the spend."""
    nums = (spend_micro, price_micro, step_atoms, taker_bps)
    if any(isinstance(item, bool) or not isinstance(item, int) for item in nums) or spend_micro <= 0 or price_micro <= 0 or step_atoms <= 0 or taker_bps < 0 or taker_bps > 100:
        return None
    if spend_micro >= 10**24 or price_micro >= 10**24:
        return None
    try:
        net = spend_micro - fee_on(spend_micro, taker_bps)
        base = round_base_atoms(base_for_quote(net, price_micro), step_atoms)
        if base <= 0:
            return None
        notional = notional_micro(base, price_micro)
        fee = fee_on(notional, taker_bps)
    except (ValueError, MoneyError):
        return None
    debit = notional + fee
    if debit <= 0 or debit > spend_micro:
        return None
    return base, fee, debit


def _refuse_reason(row: dict[str, object]) -> str:
    if row.get("status") != "1":
        return "symbol status is not trading"
    if row.get("isSpotTradingAllowed") is not True:
        return "spot trading is off"
    if row.get("quoteAsset") != "USDT":
        return "quote is not USDT"
    base = row.get("baseAsset")
    symbol = row.get("symbol")
    if not isinstance(base, str) or not isinstance(symbol, str) or not base or symbol != f"{base}USDT":
        return "base asset does not match the symbol"
    from spotbot.state import usdt_symbol_ok

    if not usdt_symbol_ok(symbol):
        return "symbol is not a USDT pair"
    st = row.get("st")
    if st is True or st == 1 or (isinstance(st, str) and st.strip().lower() == "true"):
        return "ST tag"
    plates = row.get("conceptPlates")
    if isinstance(plates, list):
        if len(plates) > 32:
            return "plates are too many"
        for plate in plates:
            if plate is None:
                continue
            if not isinstance(plate, str):
                return "plate name is not text"
            if len(plate) > 64:
                return "plate name is too long"
            if "assessment" in plate.lower():
                return "assessment zone"
    types = row.get("orderTypes")
    if isinstance(types, list) and len(types) > 32:
        return "order types are too many"
    if isinstance(types, list) and any(isinstance(item, str) and len(item) > 32 for item in types):
        return "order type is too long"
    names = {item.upper() for item in types if isinstance(item, str)} if isinstance(types, list) else set()
    if "MARKET" not in names:
        return "market orders are off"
    if row.get("tradeSideType") != "1":
        return "spot side is not two-way"
    return ""


def _as_decimal(raw: object) -> str:
    """Exchange decimal text. A JSON float is not a lot, a fee, or a cap."""
    return decimal_text(raw)


def _taker_bps(raw: object) -> int:
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        raise RuleError("takerCommission missing")
    try:
        micro = to_satoshi(_as_decimal(raw))
    except MoneyError as exc:
        raise RuleError("takerCommission is not decimal") from exc
    bps = (micro * 10_000 + MICRO - 1) // MICRO
    if bps < 0 or bps > 100:
        raise RuleError("takerCommission out of range")
    return bps


def _step_atoms(raw: object) -> tuple[int, str]:
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return 0, "base step is missing"
    try:
        text = _as_decimal(raw)
    except MoneyError:
        return 0, "base step is not decimal"
    if text in ("0", "0.0", "0.00"):
        return 0, "base step is missing"
    try:
        micro = to_satoshi(text)
    except MoneyError:
        return 0, "base step is not decimal"
    atoms = micro * (BASE_ATOMS // MICRO)
    if atoms <= 0:
        return 0, "base step is missing"
    if atoms >= 10**24:
        return 0, "base step is too large"
    return atoms, ""


def _price_tick(raw: object) -> tuple[int, str]:
    """quotePrecision is the number of decimals in the price, not in the order size."""
    if isinstance(raw, bool) or isinstance(raw, float):
        return 0, "price precision is not a count of decimals"
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return 0, "price precision is missing"
    if isinstance(raw, int):
        places = raw
    elif isinstance(raw, str):
        text = raw.strip()
        if len(text) > 2 or not text.isdigit():
            return 0, "price precision is not a count of decimals"
        places = int(text)
    else:
        return 0, "price precision is not a count of decimals"
    if places < 0 or places > 12:
        return 0, "price precision is finer than the price scale"
    tick = PRICE_SCALE // (10 ** places)
    if tick <= 0:
        return 0, "price precision is finer than the price scale"
    return tick, ""


def _quote_step(raw: object) -> tuple[int, str]:
    """Market quote minimum. MEXC also uses this value as the quote step."""
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return 0, "market min quote missing"
    try:
        step = parse_micro_nonneg(_as_decimal(raw))
    except MoneyError:
        return 0, "market min quote is not decimal"
    if step <= 0:
        return 0, "market min quote is not positive"
    return step, ""


def _max_quote(raw: object) -> int:
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return 0
    try:
        return parse_micro(_as_decimal(raw))
    except MoneyError:
        return 0


def _max_quote_reason(raw: object) -> str:
    """A present but unreadable or non-positive cap refuses the pair. An empty cap is unlimited."""
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return ""
    try:
        cap = parse_micro_nonneg(_as_decimal(raw))
    except MoneyError:
        return "max quote is not decimal"
    if cap <= 0:
        return "max quote is not positive"
    return ""
