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
    notional_micro,
    parse_micro,
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


def parse_symbol_rule(row: dict[str, object]) -> SymbolRule:
    symbol = str(row.get("symbol") or "")
    if not symbol:
        raise RuleError("exchangeInfo row has no symbol")
    taker_bps = _taker_bps(row.get("takerCommission"))
    step = _step_atoms(str(row.get("baseSizePrecision") or "0"))
    quote_step, quote_reason = _quote_step(row.get("quoteAmountPrecisionMarket") or row.get("quoteAmountPrecision"))
    max_quote = _max_quote(row.get("maxQuoteAmountMarket"))
    tick, tick_reason = _price_tick(row.get("quotePrecision"))
    reason = _refuse_reason(row) or quote_reason or tick_reason or _max_quote_reason(row.get("maxQuoteAmountMarket"))
    return SymbolRule(
        symbol, reason == "", reason, taker_bps, step, quote_step, max_quote, str(row.get("baseAsset") or ""), tick
    )


def round_base_atoms(atoms: int, step_atoms: int) -> int:
    if atoms <= 0 or step_atoms <= 0:
        return 0
    return atoms // step_atoms * step_atoms


def uses_slot(base_atoms: int, step_atoms: int) -> bool:
    """Dust below the lot stays on the book and does not block a new entry."""
    return round_base_atoms(base_atoms, step_atoms) > 0


def round_quote_micro(amount_micro: int, step_micro: int) -> int:
    """Floor the quote spend to the market minimum step from exchangeInfo."""
    if amount_micro <= 0 or step_micro <= 0:
        return 0
    return amount_micro // step_micro * step_micro


def budget_micro(cash_micro: int, alloc_bps: int) -> int:
    """Quote the book may spend. An allocation above the whole cash spends nothing."""
    if cash_micro <= 0 or alloc_bps < 1 or alloc_bps > 10_000:
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
    if budget_micro <= 0 or free_micro < 0 or step_micro <= 0 or min_micro < 0:
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
    if spend_micro <= 0 or price_micro <= 0 or step_atoms <= 0 or taker_bps < 0:
        return None
    net = spend_micro - fee_on(spend_micro, taker_bps)
    base = round_base_atoms(base_for_quote(net, price_micro), step_atoms)
    if base <= 0:
        return None
    notional = notional_micro(base, price_micro)
    fee = fee_on(notional, taker_bps)
    debit = notional + fee
    if debit <= 0 or debit > spend_micro:
        return None
    return base, fee, debit


def _refuse_reason(row: dict[str, object]) -> str:
    if str(row.get("status") or "") != "1":
        return "symbol status is not trading"
    if row.get("isSpotTradingAllowed") is not True:
        return "spot trading is off"
    if str(row.get("quoteAsset") or "") != "USDT":
        return "quote is not USDT"
    base = str(row.get("baseAsset") or "")
    symbol = str(row.get("symbol") or "")
    if not base or symbol != f"{base}USDT":
        return "base asset does not match the symbol"
    if row.get("st") is True:
        return "ST tag"
    plates = row.get("conceptPlates")
    if isinstance(plates, list):
        for plate in plates:
            if "assessment" in str(plate).lower():
                return "assessment zone"
    types = row.get("orderTypes")
    names = {str(item).upper() for item in types} if isinstance(types, list) else set()
    if "MARKET" not in names:
        return "market orders are off"
    side = str(row.get("tradeSideType") or "")
    if side != "1":
        return "spot side is not two-way"
    return ""


def _taker_bps(raw: object) -> int:
    if raw is None or str(raw).strip() == "":
        raise RuleError("takerCommission missing")
    try:
        micro = to_satoshi(str(raw))
    except MoneyError as exc:
        raise RuleError("takerCommission is not decimal") from exc
    bps = micro * 10_000 // MICRO
    if bps < 0 or bps > 100:
        raise RuleError(f"takerCommission out of range: {raw}")
    return bps


def _step_atoms(text: str) -> int:
    raw = text.strip()
    if raw in ("0", "0.0"):
        return BASE_ATOMS
    try:
        micro = to_satoshi(raw)
    except MoneyError as exc:
        raise RuleError("baseSizePrecision is not decimal") from exc
    atoms = micro * (BASE_ATOMS // MICRO)
    if atoms <= 0:
        raise RuleError("base step is zero")
    return atoms


def _price_tick(raw: object) -> tuple[int, str]:
    """quotePrecision is the number of decimals in the price, not in the order size."""
    if isinstance(raw, bool) or raw is None or str(raw).strip() == "":
        return 0, "price precision is missing"
    text = str(raw).strip()
    if not text.isdigit():
        return 0, "price precision is not a count of decimals"
    places = int(text)
    if places > 12:
        return 0, "price precision is finer than the price scale"
    tick = PRICE_SCALE // (10 ** places)
    if tick <= 0:
        return 0, "price precision is finer than the price scale"
    return tick, ""


def _quote_step(raw: object) -> tuple[int, str]:
    """Market quote minimum. MEXC also uses this value as the quote step."""
    if raw is None or str(raw).strip() == "":
        return 0, "market min quote missing"
    try:
        return parse_micro(str(raw)), ""
    except MoneyError:
        return 0, "market min quote is not decimal"


def _max_quote(raw: object) -> int:
    if raw is None or str(raw).strip() == "":
        return 0
    try:
        return parse_micro(str(raw))
    except MoneyError:
        return 0


def _max_quote_reason(raw: object) -> str:
    """A present but unreadable cap refuses the pair. An empty cap is unlimited."""
    if raw is None or str(raw).strip() == "":
        return ""
    try:
        parse_micro(str(raw))
    except MoneyError:
        return "max quote is not decimal"
    return ""
