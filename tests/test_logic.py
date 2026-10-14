import json
import threading
import time
import urllib.request

from spotbot.analyzer import _score_python
from spotbot.fees import paper_buy, paper_sell
from spotbot.replay import replay_closes
from spotbot.sanity import price_ok
from spotbot.sleeves import SleeveError, apply_funding, ledger_dir, split_equal
from spotbot.state import Position, load_book, save_book
from spotbot.liquidity import ask_wall_exit, lift_signal, volume_ratio_bps
from spotbot.oracle import ahead_exit, deviation_bps, entry_allowed, lag_bps
from spotbot.money import format_fixed, format_usdt, parse_micro, to_satoshi, MoneyError
from spotbot.signals import entry_signal, macd_cross, rsi


def test_live_entry_price_is_the_fill() -> None:
    from spotbot.money import implied_price_micro

    paid = implied_price_micro(8_500_000, 100_000_000)
    assert paid == 8_500_000_000_000
    dust = implied_price_micro(10_000_000, 10_000)
    assert dust == 100_000_000_000_000_000
    try:
        implied_price_micro(0, 1)
    except MoneyError:
        pass
    else:
        raise AssertionError("a zero quote is not a fill price")


def test_parse_micro_rounds_down() -> None:
    assert parse_micro("3") == 3_000_000
    assert parse_micro("1.0000009") == 1_000_000
    from spotbot.money import parse_price
    from spotbot.sanity import price_grid_ok

    shib = parse_price("0.00000812")
    assert shib == 8_120_000
    assert price_grid_ok(shib, 350) is True
    assert format_usdt(3_500_000) == "3.500000"
    assert format_fixed(3_500_000, 1_000_000) == "3.5"
    assert format_fixed(150_000_000, 100_000_000) == "1.5"
    try:
        to_satoshi(1.5)
    except MoneyError:
        pass
    else:
        raise AssertionError("float must be refused")


def test_exchange_tick_and_spread_haircut() -> None:
    from spotbot.money import parse_price
    from spotbot.replay import _open_mark
    from spotbot.sanity import slip_price, tick_fits

    cheap = parse_price("0.05")
    coarse = parse_price("0.01")
    assert tick_fits(cheap, coarse, 350) is False
    assert slip_price(1_000_000_000_000, 30, True) == 1_003_000_000_000
    assert slip_price(1_000_000_000_000, 30, False) == 997_000_000_000
    missing, known = _open_mark(1_000_000_000_000, 1_000_000_000_000, 100_000_000, 1_000_000, 0, 5, 0)
    assert missing == 0 and known is False
    flat, flat_known = _open_mark(0, 0, 0, 0, 1_000_000_000_000, 5, 0)
    assert flat == 0 and flat_known is True


def test_paper_fill_uses_the_book_side(tmp_path, monkeypatch) -> None:
    from spotbot.config import Config
    from spotbot.engine import _close_positions, _try_buy
    from spotbot.fees import paper_sell
    from spotbot.rules import SymbolRule
    from spotbot.state import Book, Position

    monkeypatch.setattr("spotbot.engine.venue_quotes", lambda _symbol: {})
    ask = 100_300_000_000_000
    bid = 100_000_000_000_000

    class _Ask:
        def symbol_rule(self, symbol: str) -> SymbolRule:
            return SymbolRule(symbol, True, "", 5, 1, 1_000_000, 0, "BTC")

        def book_top(self, _symbol: str) -> tuple[int, int]:
            return bid, ask

        def depth_notional(self, _symbol: str) -> tuple[int, int]:
            return 2, 1

    cfg = Config(
        symbols=("BTCUSDT",),
        paper_cash_micro=20_000_000,
        interval_sec=60,
        max_positions=1,
        alloc_bps=10_000,
        min_notional_micro=1_000_000,
        rsi_buy=35,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        live=False,
        mode="rsi",
        taker_bps=5,
        daily_loss_bps=500,
        stop_cooldown_sec=900,
        symbol_lock=True,
        api_key="",
        api_secret="",
    )
    book = Book(cash_micro=20_000_000, positions=[], realized_micro=0)
    assert _try_buy(cfg, object(), book, tmp_path / "off-buy.json", "book", "BTCUSDT", ask, "test", 10**12) is False
    assert book.positions == []
    from dataclasses import replace

    assert _try_buy(replace(cfg, entries=True), _Ask(), book, tmp_path / "ask.json", "book", "BTCUSDT", ask, "test", 10**12)
    assert book.positions[0].entry_micro == ask
    assert book.positions[0].peak_micro == ask

    class _AskHeavy(_Ask):
        def depth_notional(self, _symbol: str) -> tuple[int, int]:
            return 1, 2

    heavy = Book(cash_micro=20_000_000, positions=[], realized_micro=0)
    assert _try_buy(replace(cfg, entries=True), _AskHeavy(), heavy, tmp_path / "heavy.json", "book", "BTCUSDT", ask, "test", 10**12) is False
    assert heavy.positions == []

    class _Moved(_Ask):
        def book_top(self, _symbol: str) -> tuple[int, int]:
            return ask, ask + 1

    moved = Book(cash_micro=20_000_000, positions=[], realized_micro=0)
    assert _try_buy(replace(cfg, entries=True), _Moved(), moved, tmp_path / "moved.json", "book", "BTCUSDT", ask, "test", 10**12) is False
    assert moved.positions == []

    class _Dropped(_Ask):
        def book_top(self, _symbol: str) -> tuple[int, int]:
            return bid, ask * 8_000 // 10_000

    dropped = Book(cash_micro=20_000_000, positions=[], realized_micro=0)
    assert _try_buy(
        replace(cfg, entries=True), _Dropped(), dropped, tmp_path / "dropped.json", "book", "BTCUSDT", ask, "test", 10**12
    ) is False
    assert dropped.positions == []

    sell_bid = 90_000_000_000_000

    class _Bid:
        def symbol_rule(self, symbol: str) -> SymbolRule:
            return SymbolRule(symbol, True, "", 5, 1, 1, 0, "BTC")

        def book_top(self, _symbol: str) -> tuple[int, int]:
            return sell_bid, ask

    held = Book(
        cash_micro=0,
        positions=[Position("BTCUSDT", 100_000_000_000_000, 100_000_000_000_000, 10_000_000, 100_000_000, "test")],
        realized_micro=0,
    )
    closed, _marks, unmarked = _close_positions(cfg, _Bid(), held, tmp_path / "bid.json", "book", True)
    credit, _fee = paper_sell(100_000_000, sell_bid, 5)
    assert closed == 1
    assert unmarked == ()
    assert held.cash_micro == credit
    assert held.positions == []

    class _Healed(_Bid):
        def __init__(self) -> None:
            self.calls = 0

        def book_top(self, _symbol: str) -> tuple[int, int]:
            self.calls += 1
            if self.calls == 1:
                return sell_bid, ask
            return 100_000_000_000_000, ask

    healed = Book(
        cash_micro=0,
        positions=[Position("BTCUSDT", 100_000_000_000_000, 100_000_000_000_000, 10_000_000, 100_000_000, "test")],
        realized_micro=0,
    )
    closed, _marks, unmarked = _close_positions(cfg, _Healed(), healed, tmp_path / "healed.json", "book", True)
    assert closed == 0
    assert unmarked == ()
    assert healed.positions[0].symbol == "BTCUSDT"
    assert healed.cash_micro == 0


def test_dust_stays_in_the_equity_mark(tmp_path, monkeypatch) -> None:
    from spotbot.config import Config
    from spotbot.engine import _clock_ok, _close_positions
    from spotbot.guards import marked_equity
    from spotbot.mexc import MexcError
    from spotbot.rules import SymbolRule
    from spotbot.state import Book, Position

    monkeypatch.setattr("spotbot.engine.venue_quotes", lambda _symbol: {})

    class _NoClock:
        def server_time_ms(self) -> int:
            raise MexcError("time unread")

    assert _clock_ok(_NoClock()) is False

    class _Dust:
        def symbol_rule(self, symbol: str) -> SymbolRule:
            return SymbolRule(symbol, True, "", 5, 100_000_000, 1, 0, "BTC")

        def book_top(self, _symbol: str) -> tuple[int, int]:
            return 90_000_000_000_000, 90_100_000_000_000

        def market_sell_base(self, *_args: object) -> None:
            raise AssertionError("dust below the lot must not be sold")

    cfg = Config(
        symbols=("BTCUSDT",),
        paper_cash_micro=1_000_000,
        interval_sec=60,
        max_positions=1,
        alloc_bps=10_000,
        min_notional_micro=1_000_000,
        rsi_buy=35,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        live=False,
        mode="rsi",
        taker_bps=5,
        daily_loss_bps=500,
        stop_cooldown_sec=900,
        symbol_lock=True,
        api_key="",
        api_secret="",
    )
    book = Book(
        cash_micro=1_000_000,
        positions=[Position("BTCUSDT", 100_000_000_000_000, 100_000_000_000_000, 50_000_000, 50_000_000, "test")],
        realized_micro=0,
    )
    closed, marks, unmarked = _close_positions(cfg, _Dust(), book, tmp_path / "dust-mark.json", "book", True)
    assert closed == 0
    assert unmarked == ()
    assert marks["BTCUSDT"] == 90_000_000_000_000
    assert len(book.positions) == 1
    assert marked_equity(book.cash_micro, book.positions, marks) is not None
    gross_book = Book(
        cash_micro=0,
        positions=[Position("BTCUSDT", 90_000_000_000_000, 90_000_000_000_000, 90_000_000, 100_000_000, "test")],
        realized_micro=0,
    )
    gross_marks = {"BTCUSDT": 90_000_000_000_000}
    gross = marked_equity(0, gross_book.positions, gross_marks)
    net = marked_equity(0, gross_book.positions, gross_marks, {"BTCUSDT": 5})
    assert gross is not None and net is not None and net < gross
    assert marked_equity(0, gross_book.positions, gross_marks, {}) is None
    from spotbot.engine import open_loss_micro

    assert open_loss_micro(gross_book.positions, gross_marks) == 0
    assert open_loss_micro(gross_book.positions, gross_marks, {"BTCUSDT": 5}) == gross - net


def test_rsi_oversold_on_drop() -> None:
    prices = [100 + i for i in range(20)]
    prices += [110 - i * 3 for i in range(10)]
    value = rsi(prices, 14)
    assert value is not None and value < 35


def test_entry_needs_confirmation() -> None:
    flat = [100] * 40
    assert entry_signal("BTCUSDT", flat, 35) is None
    climb = list(range(100, 160))
    assert macd_cross(climb) in (None, "buy", "sell")


def test_stop_take_and_trail() -> None:
    from spotbot.exits import exit_reason, pnl_bps

    assert exit_reason(100_000, 96_000, 100_000, 350, 700, 300, 200) == "stop"
    assert exit_reason(100_000, 108_000, 108_000, 350, 700, 300, 200) == "take_profit"
    assert exit_reason(100_000, 102_000, 104_000, 350, 700, 300, 200) == "trail"
    assert pnl_bps(100_000, 103_500) == 350
    assert exit_reason(100_000, 101_000, 101_000, 350, 700, 300, 200) is None
    try:
        exit_reason(100_000, 100_000, 100_000, 0, 700, 300, 200)
    except ValueError:
        pass
    else:
        raise AssertionError("a zero stop must not treat a flat price as an exit")


def test_a_dark_stretch_does_not_sell_a_loss(tmp_path, monkeypatch) -> None:
    from spotbot.config import Config
    from spotbot.engine import _close_positions, _now_sec
    from spotbot.rules import SymbolRule
    from spotbot.state import Book, Position

    monkeypatch.setattr("spotbot.engine.venue_quotes", lambda _symbol: {})
    entry = 100_000_000_000_000
    down = 90_000_000_000_000
    back = 101_000_000_000_000
    cost = 100_000_000

    class _Book:
        def __init__(self, bid: int) -> None:
            self.bid = bid

        def symbol_rule(self, symbol: str) -> SymbolRule:
            return SymbolRule(symbol, True, "", 5, 1, 1, 0, "BTC")

        def book_top(self, _symbol: str) -> tuple[int, int]:
            return self.bid, self.bid + 1

    cfg = Config(
        symbols=("BTCUSDT",),
        paper_cash_micro=0,
        interval_sec=60,
        max_positions=1,
        alloc_bps=10_000,
        min_notional_micro=1_000_000,
        rsi_buy=35,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        live=False,
        mode="rsi",
        taker_bps=5,
        daily_loss_bps=500,
        stop_cooldown_sec=900,
        symbol_lock=True,
        api_key="",
        api_secret="",
    )

    def held(seen: int, bid: int, flat: bool = False) -> tuple[Book, int]:
        book = Book(
            cash_micro=0,
            positions=[Position("BTCUSDT", entry, entry, cost, 100_000_000, "test", hold_flat=flat)],
            realized_micro=0,
            seen_at=seen,
        )
        closed, _marks, unmarked = _close_positions(cfg, _Book(bid), book, tmp_path / "gap.json", "book", True)
        assert unmarked == ()
        return book, closed

    dark, closed = held(_now_sec() - 1_000, down)
    assert closed == 0 and dark.cash_micro == 0 and dark.positions[0].hold_flat is True
    still, closed = held(_now_sec(), down, flat=True)
    assert closed == 0 and still.positions[0].hold_flat is True
    clear, closed = held(_now_sec(), back, flat=True)
    assert closed == 0 and clear.positions[0].hold_flat is False
    online, closed = held(_now_sec(), down)
    assert closed == 1 and online.positions == [] and online.cash_micro > 0
    future, closed = held(_now_sec() + 60, down)
    assert closed == 0 and future.positions[0].hold_flat is True
    green, closed = held(_now_sec() - 1_000, 110_000_000_000_000)
    assert closed == 0 and green.cash_micro == 0
    assert green.positions[0].hold_flat is True and green.positions[0].peak_micro == entry

    class _Slide:
        def __init__(self) -> None:
            self.calls = 0

        def symbol_rule(self, symbol: str) -> SymbolRule:
            return SymbolRule(symbol, True, "", 5, 1, 1, 0, "BTC")

        def book_top(self, _symbol: str) -> tuple[int, int]:
            self.calls += 1
            bid = 108_000_000_000_000 if self.calls == 1 else down
            return bid, bid + 1

    rebound = Book(
        cash_micro=0,
        positions=[Position("BTCUSDT", entry, entry, cost, 100_000_000, "test", hold_flat=True)],
        realized_micro=0,
        seen_at=_now_sec(),
    )
    closed, _marks, unmarked = _close_positions(cfg, _Slide(), rebound, tmp_path / "gap.json", "book", True)
    assert unmarked == () and closed == 0 and rebound.positions[0].hold_flat is True
    assert rebound.positions[0].peak_micro == entry

    import requests

    from spotbot.mexc import MexcClient
    import spotbot.oracle as oracle

    assert MexcClient("", "", 5)._session().trust_env is False
    oracle._LOCAL.session = None

    def _down(*_args: object, **_kwargs: object) -> None:
        raise requests.ConnectionError("link down")

    monkeypatch.setattr("requests.Session.get", _down)
    assert oracle.venue_quotes("BTCUSDT") == {}
    assert oracle._LOCAL.session is not None and oracle._LOCAL.session.trust_env is False


def test_a_json_float_is_not_a_price() -> None:
    from spotbot.mexc import (
        MexcError,
        ack_commission,
        book_prices,
        depth_notionals,
        parse_account,
        parse_klines,
        rank_liquid,
        ticker_price,
    )
    from spotbot.money import parse_price
    from spotbot.ops_http import _PAGE
    from spotbot.reconcile import FeeAssetError, split_commission

    try:
        parse_price("1e-2")
    except MoneyError as exc:
        assert "exponent" in str(exc)
    else:
        raise AssertionError("an exponent is not a price")
    try:
        to_satoshi("1e-2")
    except MoneyError as exc:
        assert "exponent" in str(exc)
    else:
        raise AssertionError("an exponent is not an amount")
    try:
        book_prices(
            {"symbol": "BTCUSDT", "bidPrice": 1.25, "askPrice": "1.26", "bidQty": "1", "askQty": "1"},
            "BTCUSDT",
        )
    except MexcError as exc:
        assert "book" in str(exc)
    else:
        raise AssertionError("a JSON float is not a book price")
    try:
        ticker_price({"symbol": "BTCUSDT", "price": 1.25}, "BTCUSDT")
    except MexcError:
        pass
    else:
        raise AssertionError("a JSON float is not a last price")
    try:
        depth_notionals(
            {"bids": [[1.25, "1"]], "asks": [["1.26", "1"]], "lastUpdateId": 1},
            "BTCUSDT",
        )
    except MexcError:
        pass
    else:
        raise AssertionError("a JSON float is not a depth level")
    candle = [1_700_000_000_000, "1", "1", "1", "1", "1", 1_700_000_299_999, "1"]
    floated = [1_700_000_000_000, 1.25, "1", "1", "1", "1", 1_700_000_299_999, "1"]
    try:
        parse_klines("BTCUSDT", [floated, candle])
    except MexcError:
        pass
    else:
        raise AssertionError("a JSON float is not a candle")
    ranked = rank_liquid(
        [{"symbol": "BTCUSDT", "quoteVolume": 10.5, "priceChangePercent": "1"}],
        1,
        0,
        10_000,
        5,
    )
    assert ranked == []
    try:
        parse_account({"balances": [{"asset": "USDT", "free": 1.5, "locked": "0"}]})
    except MexcError as exc:
        assert "decimal" in str(exc)
    else:
        raise AssertionError("a JSON float is not a balance")
    try:
        ack_commission({"commission": 0.01, "commissionAsset": "USDT"}, "BTC")
    except MexcError:
        pass
    else:
        raise AssertionError("a JSON float is not a commission")
    try:
        split_commission(
            [{"id": "1", "orderId": "9", "symbol": "BTCUSDT", "isBuyer": True, "qty": 0.1, "quoteQty": "1", "price": "1"}],
            "9",
            "BTC",
            "BUY",
        )
    except FeeAssetError:
        pass
    else:
        raise AssertionError("a JSON float is not a trade")
    assert "function esc(" in _PAGE


def test_exchange_filters_refuse_a_json_float() -> None:
    from spotbot.mexc import MexcError, _filled_base_text, _order_id_text
    from spotbot.oracle import _binance_price, _bybit_price, _okx_price
    from spotbot.reconcile import FeeAssetError, split_commission
    from spotbot.rules import RuleError, parse_symbol_rule

    row = {
        "symbol": "BTCUSDT",
        "status": "1",
        "isSpotTradingAllowed": True,
        "quoteAsset": "USDT",
        "st": False,
        "baseAsset": "BTC",
        "quotePrecision": "2",
        "orderTypes": ["MARKET"],
        "tradeSideType": "1",
        "takerCommission": "0.0005",
        "baseSizePrecision": "0.000001",
        "quoteAmountPrecisionMarket": "1",
        "maxQuoteAmountMarket": "200000",
    }
    assert parse_symbol_rule(row).tradable is True
    floated = dict(row)
    floated["takerCommission"] = 0.0005
    try:
        parse_symbol_rule(floated)
    except RuleError as exc:
        assert "decimal" in str(exc)
    else:
        raise AssertionError("a JSON float is not a taker fee")
    for key, reason in (
        ("baseSizePrecision", "base step"),
        ("quoteAmountPrecisionMarket", "min quote"),
        ("maxQuoteAmountMarket", "max quote"),
    ):
        bad = dict(row)
        bad[key] = 1.5
        rule = parse_symbol_rule(bad)
        assert rule.tradable is False and reason.split()[0] in rule.refuse_reason
    tick = dict(row)
    tick["quotePrecision"] = 2.0
    assert "decimal" in parse_symbol_rule(tick).refuse_reason or "count" in parse_symbol_rule(tick).refuse_reason
    assert _binance_price({"symbol": "BTCUSDT", "price": 1.25}, "BTCUSDT") is None
    assert _bybit_price({"result": {"list": [{"symbol": "BTCUSDT", "lastPrice": 1.25}]}}, "BTCUSDT") is None
    assert _okx_price({"data": [{"instId": "BTC-USDT", "last": 1.25}]}, "BTC-USDT") is None
    try:
        _filled_base_text({"executedQty": 0.1}, "buy")
    except MexcError as exc:
        assert "decimal" in str(exc)
    else:
        raise AssertionError("a JSON float is not a fill")
    try:
        _order_id_text(12.0)
    except MexcError as exc:
        assert "digits" in str(exc)
    else:
        raise AssertionError("a JSON float is not an order id")
    assert _order_id_text(12) == "12"
    try:
        split_commission(
            [{
                "id": 1.0,
                "orderId": "9",
                "symbol": "BTCUSDT",
                "isBuyer": True,
                "qty": "0.1",
                "quoteQty": "1",
                "price": "10",
            }],
            "9",
            "BTC",
            "BUY",
        )
    except FeeAssetError as exc:
        assert "digits" in str(exc)
    else:
        raise AssertionError("a JSON float is not a trade id")


def test_a_bad_sibling_does_not_stop_the_sell(tmp_path, monkeypatch) -> None:
    from spotbot.config import Config
    from spotbot.engine import _now_ms, run_cycle, sibling_pending
    from spotbot.mexc import MexcClient, MexcError, _json_body, parse_klines
    from spotbot.money import MoneyError, base_for_quote, decimal_zero, implied_price_micro
    from spotbot.rules import SymbolRule
    from spotbot.sanity import jump_bps
    from spotbot.state import Book, Position, save_book

    monkeypatch.setattr("spotbot.engine.venue_quotes", lambda _symbol: {})
    assert decimal_zero("0E-8") is False
    assert base_for_quote(True, 1) == 0
    try:
        implied_price_micro(True, 1)
    except MoneyError:
        pass
    else:
        raise AssertionError("a bool is not a fill price")
    try:
        jump_bps(True, 1)
    except ValueError:
        pass
    else:
        raise AssertionError("a bool is not a price")
    quiet = [1_000, "1", "1.1", "0.9", "1", "0", 2_000, "10"]
    loud = [3_000, "1", "1.1", "0.9", "1", "1", 4_000, "10"]
    try:
        parse_klines("BTCUSDT", [quiet, loud])
    except MexcError as exc:
        assert "volume" in str(exc)
    else:
        raise AssertionError("a candle with no base volume must be refused")
    client = MexcClient("", "", 5)
    client._session().cookies.set_cookie(object())
    assert len(client._session().cookies) == 0
    huge = type("R", (), {"content": b"x" * (8_000_001)})()
    try:
        _json_body(huge, "ticker")
    except MexcError as exc:
        assert "large" in str(exc)
    else:
        raise AssertionError("a huge response must be refused")

    sibling = tmp_path / "sleeve_major.json"
    sibling.write_text("{", encoding="utf-8")
    assert "unreadable" in (sibling_pending((sibling,)) or "")

    path = tmp_path / "sleeve_alt.json"
    entry = 100_000_000_000_000
    save_book(
        path,
        Book(
            cash_micro=0,
            positions=[Position("BTCUSDT", entry, entry, 1, 100_000_000, "test")],
            realized_micro=0,
            ledger="live",
        ),
    )
    sent: list[str] = []

    class _Client:
        def forget_rules(self) -> None:
            return None

        def symbol_rule(self, symbol: str) -> SymbolRule:
            return SymbolRule(symbol, True, "", 5, 1, 1, 0, "BTC")

        def server_time_ms(self) -> int:
            return _now_ms()

        def book_top(self, _symbol: str) -> tuple[int, int]:
            return 90_000_000_000_000, 90_000_000_000_001

        def spot_balances(self) -> tuple[int, int, dict[str, int], dict[str, int]]:
            return 0, 0, {"BTC": 100_000_000}, {"BTC": 100_000_000}

        def market_sell_base(self, symbol: str, _base: int, _client: str):
            sent.append(symbol)
            raise MexcError("stop before the wire")

        def order_by_client(self, _symbol: str, _client: str) -> dict[str, str]:
            raise MexcError("order is not on the wire")

    cfg = Config(
        symbols=("BTCUSDT",),
        paper_cash_micro=0,
        interval_sec=60,
        max_positions=1,
        alloc_bps=10_000,
        min_notional_micro=1_000_000,
        rsi_buy=35,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        live=True,
        mode="rsi",
        taker_bps=5,
        daily_loss_bps=500,
        stop_cooldown_sec=900,
        symbol_lock=True,
        api_key="k",
        api_secret="s",
        entries=False,
    )
    run_cycle(cfg, _Client(), path, "alt", (sibling,))
    assert sent == ["BTCUSDT"]


def test_a_bool_is_not_a_price_and_a_huge_book_stays(tmp_path) -> None:
    from spotbot.exits import exit_reason, pnl_bps
    from spotbot.guards import drawdown_blocks, marked_equity, spread_blocks, top_spread_bps
    from spotbot.journal import note_event
    from spotbot.state import LedgerError, load_book

    try:
        pnl_bps(True, 1)
    except ValueError:
        pass
    else:
        raise AssertionError("a bool is not a profit")
    try:
        exit_reason(1, 1, 1, True, 1, 1, 1)
    except ValueError:
        pass
    else:
        raise AssertionError("a bool is not an exit percent")
    try:
        top_spread_bps(True, True)
    except ValueError as exc:
        assert "crossed" in str(exc) or "empty" in str(exc)
    else:
        raise AssertionError("a bool is not a spread")
    assert spread_blocks(True, 30) is True
    assert drawdown_blocks(True, 1, 1_000) is True
    assert marked_equity(True, [], {}, None) is None

    huge = tmp_path / "book.json"
    with huge.open("wb") as handle:
        handle.seek(1_000_001)
        handle.write(b" ")
    try:
        load_book(huge, 0)
    except LedgerError as exc:
        assert "large" in str(exc)
    else:
        raise AssertionError("a huge book must stay unopened")
    assert huge.stat().st_size > 1_000_000

    events = tmp_path / "ops_events.jsonl"
    events.write_bytes(b"x" * 300_000 + b'\n{"kind":"old"}\n')
    note_event(tmp_path, book="book", kind="exit", symbol="BTCUSDT")
    text = events.read_text(encoding="utf-8")
    assert "BTCUSDT" in text
    assert len(text) < 300_000


def test_a_bool_is_not_a_peer_or_a_client_id(tmp_path) -> None:
    from spotbot.mexc import MexcClient, MexcError, clock_allows
    from spotbot.oracle import ahead_exit, deviation_bps, lag_bps
    from spotbot.guards import pair_locked
    from spotbot.rules import budget_micro, cap_spend, plan_paper_buy
    from spotbot.signals import entry_signal
    from spotbot.state import Book, client_id_ok, exchange_order_id_ok
    from spotbot.ops_http import snapshot

    assert clock_allows(True, True) is False
    try:
        MexcClient("", "", True)
    except MexcError:
        pass
    else:
        raise AssertionError("a bool is not a timeout")
    assert deviation_bps([100_000_000_000_000, True]) is None
    assert lag_bps(100_000_000_000_000, [True]) is None
    assert ahead_exit(100_000_000_000_000, [True], 100) is False
    assert budget_micro(True, 10_000) == 0
    assert cap_spend(True, 1_000_000, 1, 1, 0) == 0
    assert plan_paper_buy(True, 1, 1, 5) is None
    assert pair_locked(Book(cash_micro=0, positions=[], realized_micro=0), "BTCUSDT", True) is True
    assert entry_signal("BTCUSDT", [True] * 40, 35) is None
    assert client_id_ok(True) is False
    assert exchange_order_id_ok(True) is False
    folder = tmp_path / "paper"
    folder.mkdir()
    huge = folder / "book.json"
    with huge.open("wb") as handle:
        handle.seek(1_000_001)
        handle.write(b" ")
    view = snapshot(tmp_path, 19280)
    assert view["books"]["paper/book"]["error"] == "book file is too large"


def test_a_bool_is_not_a_candle_or_a_config_number() -> None:
    from dataclasses import replace

    from spotbot.config import Config, ConfigError, require_cycle_config
    from spotbot.engine import open_loss_micro
    from spotbot.liquidity import ask_wall_exit, close_position_bps, lift_signal, volume_ratio_bps
    from spotbot.reconcile import base_is_free, inventory_mismatch
    from spotbot.sanity import mark_ok
    from spotbot.state import Position

    volumes = [100] * 12 + [400, 100]
    assert volume_ratio_bps([True] * 14) is None
    assert close_position_bps(True, 1, 100) is None
    assert lift_signal("BTCUSDT", volumes, 110, 100, 108, True, 0) is None
    assert ask_wall_exit(True, 2, 100) is False
    assert mark_ok(True, True) is False
    assert paper_buy(True, 1, 5) == (0, 0)
    assert paper_sell(True, 1, 5) == (0, 0)
    pos = Position("BTCUSDT", 100, 100, 100, 100_000_000, "test")
    assert open_loss_micro([pos], {"BTCUSDT": True}) == 0
    assert inventory_mismatch([("BTCUSDT", True)], {}) == "BTCUSDT base is not an integer"
    assert base_is_free(True, True) is False
    cfg = Config(
        symbols=("BTCUSDT",),
        paper_cash_micro=20_000_000,
        interval_sec=60,
        max_positions=1,
        alloc_bps=10_000,
        min_notional_micro=1_000_000,
        rsi_buy=35,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        live=False,
        mode="rsi",
        taker_bps=5,
        daily_loss_bps=500,
        stop_cooldown_sec=900,
        symbol_lock=True,
        api_key="",
        api_secret="",
    )
    try:
        require_cycle_config(replace(cfg, stop_bps=True))
    except ConfigError as exc:
        assert "integer" in str(exc)
    else:
        raise AssertionError("a bool stop is not a config")


def test_a_bool_does_not_clear_an_order_or_move_cash() -> None:
    from spotbot.analyzer import score
    from spotbot.engine import _entries_halted
    from spotbot.liquidity import candle_lift
    from spotbot.oracle import cheapest_first
    from spotbot.reconcile import ack_fee_matches, fee_fits, fills_match, pending_gone
    from spotbot.sanity import price_ok
    from spotbot.state import Book, Position, apply_sell_progress, record_buy, record_sell_fill

    assert pending_gone(3, False, False) is False
    assert fills_match(True, True, True, True) is False
    assert ack_fee_matches(True, True) is False
    assert fee_fits(True, True) is False
    book = Book(cash_micro=5_000_000, positions=[], realized_micro=0)
    assert record_buy(book, "BTCUSDT", 100, True, 1_000_000, 0, "test", "buy1", "1") is False
    assert book.cash_micro == 5_000_000
    pos = Position("BTCUSDT", 100, 100, 1_000_000, 100_000_000, "test")
    book.positions.append(pos)
    assert record_sell_fill(book, "BTCUSDT", True, 1_000_000, 0) is False
    assert book.cash_micro == 5_000_000
    book.pending_side = "SELL"
    book.pending_symbol = "BTCUSDT"
    book.pending_base_atoms = 100_000_000
    assert apply_sell_progress(book, "BTCUSDT", True, 1_000_000, 0) is False
    assert book.cash_micro == 5_000_000
    volumes = [100] * 12 + [400, 100]
    assert candle_lift("BTCUSDT", volumes, 110, 100, 108, True, 6_500) is None
    assert _entries_halted(book, True, 0) is True
    assert score(True, 6_500, 10, 30, 2_000, 1_000) == 0
    assert price_ok(100, 100, True) is False
    assert cheapest_first([("BTCUSDT", True), ("ETHUSDT", -4)]) == ["ETHUSDT"]


def test_a_fraction_is_not_a_fee_and_a_bool_book_is_not_saved() -> None:
    from spotbot.engine import mark_stop_cooldown, open_loss_micro
    from spotbot.fees import fee_on
    from spotbot.rules import uses_slot
    from spotbot.sanity import tick_fits
    from spotbot.signals import below_lower_band, macd_cross, rsi
    from spotbot.state import Book, LedgerError, Position, audit_book

    book = Book(cash_micro=True, positions=[], realized_micro=0)
    try:
        audit_book(book)
    except LedgerError as exc:
        assert "integer" in str(exc)
    else:
        raise AssertionError("a bool cash balance must not pass the book check")
    held = Position("BTCUSDT", 100, 100, True, 100_000_000, "test")
    assert open_loss_micro([held], {"BTCUSDT": 100}) >= 2**62
    assert uses_slot(True, 1) is True
    try:
        fee_on(1.5, 5)
    except ValueError:
        pass
    else:
        raise AssertionError("a fraction is not a fee")
    assert paper_buy(1.5, 100, 5) == (0, 0)
    try:
        format_usdt(True)
    except MoneyError:
        pass
    else:
        raise AssertionError("a bool is not a usdt amount")
    assert rsi([1.5] * 20) is None
    assert macd_cross([1.5] * 40) is None
    assert below_lower_band([100] * 20, True) is False
    assert tick_fits(100.5, 1, 350) is False
    fresh = Book(cash_micro=1_000_000, positions=[], realized_micro=0)
    mark_stop_cooldown(fresh, "stop", True)
    assert fresh.cooldown_until > time.time() + 80_000


def test_a_fraction_does_not_match_an_integer_fill() -> None:
    from spotbot.exits import exit_reason
    from spotbot.guards import spread_blocks, top_spread_bps
    from spotbot.money import base_for_quote, notional_micro
    from spotbot.reconcile import ack_fee_matches, base_is_free, fee_fits, fills_match, pending_gone
    from spotbot.rules import budget_micro, plan_paper_buy
    from spotbot.sanity import mark_ok
    from spotbot.state import Book, record_buy

    assert pending_gone(3.0, 0, False) is False
    assert fills_match(1.0, 1.0, 1, 1) is False
    assert ack_fee_matches(0.0, 5) is False
    assert fee_fits(1.5, 2) is False
    assert base_is_free(100.0, 50) is False
    assert base_for_quote(1.5, 100) == 0
    assert budget_micro(1.5, 10_000) == 0
    assert plan_paper_buy(1.5, 100, 1, 5) is None
    assert mark_ok(100.0, 100.0) is False
    assert spread_blocks(1.5, 30) is True
    try:
        notional_micro(1.5, 100)
    except MoneyError:
        pass
    else:
        raise AssertionError("a fraction is not a notional")
    try:
        exit_reason(100.0, 90.0, 100.0, 350, 700, 300, 200)
    except ValueError:
        pass
    else:
        raise AssertionError("a fraction is not an exit price")
    try:
        top_spread_bps(100.0, 101.0)
    except ValueError:
        pass
    else:
        raise AssertionError("a fraction is not a book")
    book = Book(cash_micro=5_000_000, positions=[], realized_micro=0)
    assert record_buy(book, "BTCUSDT", 100, 100_000_000, 1.5, 0, "test", "buy1", "1") is False
    assert book.cash_micro == 5_000_000


def test_a_fraction_is_not_sent_or_remembered() -> None:
    from spotbot.engine import _over_request
    from spotbot.guards import drawdown_blocks, marked_equity, pair_locked
    from spotbot.mexc import rank_liquid
    from spotbot.money import format_fixed, implied_price_micro
    from spotbot.sanity import slip_price
    from spotbot.signals import entry_signal
    from spotbot.state import Book, LedgerError, remember_pending

    try:
        format_fixed(1.9, 1_000_000)
    except MoneyError:
        pass
    else:
        raise AssertionError("a fraction must not be formatted onto the wire")
    try:
        implied_price_micro(1.5, 100)
    except MoneyError:
        pass
    else:
        raise AssertionError("a fraction is not a fill price")
    fresh = Book(cash_micro=5_000_000, positions=[], realized_micro=0)
    try:
        remember_pending(fresh, "buy1", "BTCUSDT", "BUY", 1.5, 1_000_000)
    except LedgerError as exc:
        assert "integer" in str(exc)
    else:
        raise AssertionError("a fraction must not be stored as an order")
    assert fresh.pending_client_id == ""
    assert marked_equity(1.5, [], {}) is None
    assert drawdown_blocks(1_000, 1.5, 100) is True
    assert slip_price(1.5, 30, True) == 0
    assert _over_request(fresh, 1.5, 1_000_000) == "fill is not an integer"
    assert rank_liquid([], 1, -10_000, 10_000, 1.5) == []
    fresh.pair_lock_until = {"BTCUSDT": 1.5}
    assert pair_locked(fresh, "BTCUSDT", 10) is True
    assert entry_signal("BTCUSDT", [1.5] * 40, 35) is None


def test_a_fraction_is_not_a_clock_or_a_candle_limit() -> None:
    from spotbot.analyzer import _score_python
    from spotbot.engine import _entries_halted, _try_buy, _unseen
    from spotbot.mexc import MexcClient, MexcError, MexcRateLimit, clock_allows, parse_account, parse_klines
    from spotbot.reconcile import order_is_ours
    from spotbot.state import Book

    assert clock_allows(1_000.0, 1_000.0) is False
    assert MexcRateLimit("limited", 1.5).retry_after_sec is None
    book = Book(cash_micro=1_000_000, positions=[], realized_micro=0)
    assert _entries_halted(book, 1.5, 0) is True
    book.seen_at = 1.5
    assert _unseen(book, 10_000, 60) is True
    assert _score_python(20_000.0, 6_500, 10, 30, 2_000, 1_000) == 0
    try:
        MexcClient("", "").klines("BTCUSDT", "5m", 1.5)
    except MexcError as exc:
        assert "integer" in str(exc)
    else:
        raise AssertionError("a fraction must not be sent as a kline limit")
    try:
        parse_klines("BTCUSDT", [], 300_000.0)
    except MexcError as exc:
        assert "interval" in str(exc)
    else:
        raise AssertionError("a fraction is not a candle span")
    ack = {"clientOrderId": 1, "symbol": "BTCUSDT", "side": "BUY", "type": "MARKET"}
    assert order_is_ours(ack, "BTCUSDT", "BUY", "1") is False
    try:
        parse_account([])
    except MexcError:
        pass
    else:
        raise AssertionError("an account list is not balances")
    from spotbot.config import Config

    cfg = Config(
        symbols=("BTCUSDT",),
        paper_cash_micro=20_000_000,
        interval_sec=60,
        max_positions=1,
        alloc_bps=10_000,
        min_notional_micro=1_000_000,
        rsi_buy=35,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        live=False,
        mode="rsi",
        taker_bps=5,
        daily_loss_bps=500,
        stop_cooldown_sec=900,
        symbol_lock=True,
        api_key="",
        api_secret="",
        entries=True,
    )
    assert _try_buy(cfg, object(), Book(cash_micro=1_000_000, positions=[], realized_micro=0), book_path := __import__("pathlib").Path("off.json"), "book", "BTCUSDT", 1.5, "test", 10**12) is False


def test_a_fraction_is_not_a_successful_exchange_code() -> None:
    from dataclasses import replace

    from spotbot.config import ConfigError, require_cycle_config
    from spotbot.engine import open_loss_micro
    from spotbot.mexc import MexcError, _reject_exchange_code, book_prices, depth_notionals, rank_liquid, ticker_price
    from spotbot.reconcile import inventory_mismatch
    from spotbot.rules import uses_slot
    from spotbot.state import Book, LedgerError, Position, load_book

    try:
        _reject_exchange_code({"code": 0.0})
    except MexcError as exc:
        assert "refused" in str(exc)
    else:
        raise AssertionError("a fractional exchange code is not success")
    assert inventory_mismatch([("BTCUSDT", 100)], {"BTC": 100.0}) == "BTC exchange 100.0 != book 100"
    assert uses_slot(1.5, 1) is True
    pos = Position("BTCUSDT", 100, 100, 1_000_000, 100_000_000, "test")
    assert open_loss_micro([pos], {"BTCUSDT": 1.5}) >= 2**62
    try:
        load_book(__import__("pathlib").Path("missing-book.json"), 1.5)
    except LedgerError as exc:
        assert "integer" in str(exc)
    else:
        raise AssertionError("fractional paper cash must not open a book")
    try:
        ticker_price({"symbol": 1, "price": "1"}, "BTCUSDT")
    except MexcError:
        pass
    else:
        raise AssertionError("a numeric ticker name is not the pair")
    try:
        book_prices({"symbol": 1, "bidPrice": "1", "askPrice": "1.01", "bidQty": "1", "askQty": "1"}, "BTCUSDT")
    except MexcError:
        pass
    else:
        raise AssertionError("a numeric book name is not the pair")
    try:
        depth_notionals({"symbol": 1, "bids": [["1", "1"]], "asks": [["2", "1"]], "lastUpdateId": 1}, "BTCUSDT")
    except MexcError:
        pass
    else:
        raise AssertionError("a numeric depth name is not the pair")
    assert rank_liquid([{"symbol": 1, "quoteVolume": "10", "priceChangePercent": "1"}], 1, -10_000, 10_000, 8) == []
    from spotbot.config import Config

    cfg = Config(
        symbols=("BTCUSDT",),
        paper_cash_micro=20_000_000,
        interval_sec=60,
        max_positions=1,
        alloc_bps=10_000,
        min_notional_micro=1_000_000,
        rsi_buy=35,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        live=False,
        mode="rsi",
        taker_bps=5,
        daily_loss_bps=500,
        stop_cooldown_sec=900,
        symbol_lock=True,
        api_key="",
        api_secret="",
    )
    try:
        require_cycle_config(replace(cfg, entries="yes"))
    except ConfigError as exc:
        assert "on or off" in str(exc)
    else:
        raise AssertionError("entries must be a bool")


def test_a_numeric_trade_id_is_not_our_order() -> None:
    from spotbot.oracle import ahead_exit
    from spotbot.reconcile import FeeAssetError, order_filled, order_missing, split_commission, usdt_commission
    from spotbot.state import Book, LedgerError, bind_ledger

    row = {
        "id": "7",
        "orderId": 1,
        "symbol": "BTCUSDT",
        "qty": "0.5",
        "quoteQty": "6",
        "price": "12",
        "commission": "0",
        "commissionAsset": "USDT",
        "isBuyer": True,
    }
    try:
        split_commission([row], "1", "BTC", "BUY")
    except FeeAssetError as exc:
        assert "digits" in str(exc)
    else:
        raise AssertionError("a numeric trade order id must not match")
    named = dict(row)
    named["orderId"] = "1"
    named["id"] = 7
    try:
        split_commission([named], "1", "BTC", "BUY")
    except FeeAssetError as exc:
        assert "digits" in str(exc)
    else:
        raise AssertionError("a numeric trade id must not match")
    paid = dict(named)
    paid["id"] = "7"
    paid["commission"] = "0.01"
    paid["commissionAsset"] = 1
    try:
        split_commission([paid], "1", "BTC", "BUY")
    except FeeAssetError as exc:
        assert "asset" in str(exc)
    else:
        raise AssertionError("a numeric commission asset must not be booked")
    assert usdt_commission([row], "1") == 0
    assert order_filled({"status": 2}) is True
    assert order_filled({"status": 2.0}) is False
    assert order_filled([]) is False
    assert order_missing(None) is False
    assert ahead_exit(100, [100], 30.0) is False
    try:
        bind_ledger(Book(cash_micro=0, positions=[], realized_micro=0), "yes")
    except LedgerError as exc:
        assert "on or off" in str(exc)
    else:
        raise AssertionError("a text flag must not stamp the book live")


def test_a_nearby_code_is_not_an_unknown_order() -> None:
    from spotbot.mexc import MexcClient, MexcError
    from spotbot.oracle import venue_quotes
    from spotbot.reconcile import order_missing
    from spotbot.rules import parse_symbol_rule

    assert order_missing("exchange code -2011: rejected") is True
    assert order_missing("exchange code -20110: other") is False
    assert venue_quotes(1) == {}
    assert venue_quotes("BTCUSDT", 1.5) == {}
    try:
        MexcClient("", "").symbol_rule(1)
    except MexcError as exc:
        assert "text" in str(exc)
    else:
        raise AssertionError("a numeric pair must not be requested")
    row = {
        "symbol": "BTCUSDT",
        "status": "1",
        "isSpotTradingAllowed": True,
        "quoteAsset": "USDT",
        "st": False,
        "baseAsset": "BTC",
        "quotePrecision": "2",
        "orderTypes": ["MARKET"],
        "tradeSideType": "1",
        "takerCommission": "0.0005",
        "baseSizePrecision": "0.000001",
        "quoteAmountPrecisionMarket": "1",
    }
    assert parse_symbol_rule(row).tradable is True
    numbered = dict(row)
    numbered["status"] = 1
    assert parse_symbol_rule(numbered).tradable is False
    tagged = dict(row)
    tagged["st"] = 1
    assert parse_symbol_rule(tagged).tradable is False
    typed = dict(row)
    typed["orderTypes"] = [1]
    assert parse_symbol_rule(typed).tradable is False
    sided = dict(row)
    sided["tradeSideType"] = 1
    assert parse_symbol_rule(sided).tradable is True
    sided["tradeSideType"] = True
    assert parse_symbol_rule(sided).tradable is False
    sided["tradeSideType"] = 1.0
    assert parse_symbol_rule(sided).tradable is False


def test_a_zero_quote_step_is_not_replaced() -> None:
    from spotbot.oracle import _binance_price, _okx_inst
    from spotbot.rules import RuleError, parse_symbol_rule
    from spotbot.state import Book, LedgerError, audit_book, usdt_symbol_ok

    row = {
        "symbol": "BTCUSDT",
        "status": "1",
        "isSpotTradingAllowed": True,
        "quoteAsset": "USDT",
        "st": False,
        "baseAsset": "BTC",
        "quotePrecision": "2",
        "orderTypes": ["MARKET"],
        "tradeSideType": "1",
        "takerCommission": "0.0005",
        "baseSizePrecision": "0.000001",
        "quoteAmountPrecision": "1",
        "quoteAmountPrecisionMarket": 0,
    }
    assert parse_symbol_rule(row).tradable is False
    try:
        parse_symbol_rule([])
    except RuleError as exc:
        assert "object" in str(exc)
    else:
        raise AssertionError("a list is not an exchangeInfo row")
    try:
        parse_symbol_rule({"symbol": 1})
    except RuleError as exc:
        assert "symbol" in str(exc)
    else:
        raise AssertionError("a numeric symbol is not a pair name")
    assert usdt_symbol_ok(1) is False
    assert _okx_inst(1) is None
    assert _binance_price({"symbol": 1, "price": "1"}, "1") is None
    book = Book(cash_micro=0, positions=[], realized_micro=0)
    book.pair_stops = {"BTCUSDT": [True]}
    try:
        audit_book(book)
    except LedgerError as exc:
        assert "timestamp" in str(exc)
    else:
        raise AssertionError("a bool stop time must not open the book")
    book.pair_stops = {}
    book.guard_day = 1
    try:
        audit_book(book)
    except LedgerError as exc:
        assert "date" in str(exc)
    else:
        raise AssertionError("a numeric guard day must not open the book")


def test_a_numeric_id_in_the_book_is_not_text(tmp_path) -> None:
    from spotbot.state import LedgerError, _pair_stops, load_book

    path = tmp_path / "book.json"
    path.write_text(json.dumps({"cash_micro": 0, "pending_client_id": 1}), encoding="utf-8")
    try:
        load_book(path, 0)
    except LedgerError as exc:
        assert "text" in str(exc)
    else:
        raise AssertionError("a numeric client id must not load")
    path.write_text(
        json.dumps({
            "cash_micro": 0,
            "positions": [{
                "symbol": "BTCUSDT",
                "entry_micro": 1,
                "peak_micro": 1,
                "quote_micro": 1,
                "base_atoms": 1,
                "reason": 1,
            }],
        }),
        encoding="utf-8",
    )
    try:
        load_book(path, 0)
    except LedgerError as exc:
        assert "text" in str(exc)
    else:
        raise AssertionError("a numeric reason must not load")
    path.write_text(json.dumps({"cash_micro": 0, "ledger": 0}), encoding="utf-8")
    try:
        load_book(path, 0)
    except LedgerError as exc:
        assert "text" in str(exc)
    else:
        raise AssertionError("a numeric ledger must not become blank")
    path.write_text(json.dumps({"cash_micro": 0, "pending_exchange_order_id": 99}), encoding="utf-8")
    try:
        load_book(path, 0)
    except LedgerError as exc:
        assert "text" in str(exc)
    else:
        raise AssertionError("a numeric exchange id must not load")
    try:
        _pair_stops({1: []})
    except LedgerError as exc:
        assert "text" in str(exc)
    else:
        raise AssertionError("a numeric pair name must not load")


def test_a_zero_fill_quote_is_not_replaced() -> None:
    from spotbot.engine import _apply_progress
    from spotbot.mexc import MexcClient, MexcError, ack_commission, executed_fill, parse_account
    from spotbot.reconcile import inventory_mismatch
    from spotbot.state import Book

    try:
        executed_fill({"executedQty": "1", "cummulativeQuoteQty": 0, "cumulativeQuoteQty": "5"})
    except MexcError:
        pass
    else:
        raise AssertionError("a present zero quote must not use the other field")
    try:
        ack_commission({"commission": "0.01", "commissionAsset": 1}, "BTC")
    except MexcError as exc:
        assert "text" in str(exc)
    else:
        raise AssertionError("a numeric commission asset must not be booked")
    try:
        parse_account({"balances": [{"asset": 1, "free": "1", "locked": "0"}]})
    except MexcError as exc:
        assert "text" in str(exc)
    else:
        raise AssertionError("a numeric balance asset must not be stored")
    assert inventory_mismatch([(1, 100)], {}) == "pair name is not text"
    client = MexcClient("", "")
    for call in (
        lambda: client.ohlcv(1),
        lambda: client.book_top(1),
        lambda: client.price(1),
        lambda: client.depth_notional(1),
        lambda: client.my_trades("BTCUSDT", order_id=1),
        lambda: client.order_by_client(1, "abc"),
    ):
        try:
            call()
        except MexcError as exc:
            assert "text" in str(exc) or "pair" in str(exc) or "client" in str(exc)
        else:
            raise AssertionError("a numeric name must not be requested")
    book = Book(cash_micro=0, positions=[], realized_micro=0)
    assert _apply_progress(None, book, {"orderId": ["9"]}, 1, 1, 1) is False
    assert _apply_progress(None, book, {"orderId": 0}, 1, 1, 1) is False


def test_a_text_flag_does_not_open_the_live_book(tmp_path) -> None:
    from spotbot.engine import _order_fees
    from spotbot.guards import note_pair_stop, pair_locked
    from spotbot.mexc import MexcClient, MexcError, _base_asset
    from spotbot.sleeves import SleeveError, ledger_dir
    from spotbot.state import Book, LedgerError, record_buy, remember_pending

    try:
        ledger_dir(tmp_path, "no")
    except SleeveError as exc:
        assert "on or off" in str(exc)
    else:
        raise AssertionError("a text flag must not choose the live book")
    book = Book(cash_micro=1_000_000, positions=[], realized_micro=0)
    try:
        remember_pending(book, "a" * 8, 1, "BUY", 0, 1)
    except LedgerError as exc:
        assert "USDT" in str(exc)
    else:
        raise AssertionError("a numeric pair must not be remembered")
    assert record_buy(book, 1, 1, 1, 1, 0, "test", "a" * 8, "1") is False
    note_pair_stop(book, 1, 1_700_000_000, 3, 60)
    assert book.pair_stops in (None, {})
    assert pair_locked(book, 1, 1_700_000_000) is True
    assert _order_fees(None, 1, "1", "BUY") is None
    try:
        _base_asset(1)
    except MexcError as exc:
        assert "USDT" in str(exc)
    else:
        raise AssertionError("a numeric base must not be read")
    client = MexcClient("", "")
    assert client.liquid_usdt(True, 0, 1, 1) == []
    for call in (lambda: client.ohlcv("btc"), lambda: client.symbol_rule("btc"), lambda: client.my_trades("btc")):
        try:
            call()
        except MexcError as exc:
            assert "USDT" in str(exc)
        else:
            raise AssertionError("a pair that is not USDT must not be requested")


def test_a_text_live_flag_does_not_trade(monkeypatch) -> None:
    from spotbot.config import ConfigError, load_config
    from spotbot.mexc import MexcClient, MexcError
    from spotbot.state import Book, LedgerError, Position, audit_book, record_buy, record_sell_fill

    try:
        load_config("no")
    except ConfigError as exc:
        assert "on or off" in str(exc)
    else:
        raise AssertionError("a text flag must not turn trading on")
    try:
        load_config(False, 1)
    except ConfigError as exc:
        assert "rsi" in str(exc)
    else:
        raise AssertionError("a numeric mode must not load")
    for name, value in {
        "SPOT_SYMBOLS": "BTCUSDT",
        "SPOT_INTERVAL_SEC": "60",
        "SPOT_LIVE": "0",
        "SPOT_MODE": "rsi",
        "SPOT_TAKER_BPS": "5",
        "SPOT_DAILY_LOSS_BPS": "500",
        "SPOT_STOP_COOLDOWN_SEC": "900",
        "SPOT_DRAWDOWN_BPS": "1000",
        "SPOT_STOP_LOCK_COUNT": "3",
        "SPOT_STOP_LOCK_SEC": "14400",
        "SPOT_SPREAD_BPS": "30",
        "SPOT_ENTRIES": "0",
        "SPOT_PAPER_CASH_USDT": "1000",
        "SPOT_MIN_USDT": "3",
        "SPOT_MAX_POSITIONS": "1",
        "SPOT_ALLOC_BPS": "2000",
        "SPOT_RSI_BUY": "35",
        "MEXC_API_KEY": "line\nkey",
        "MEXC_API_SECRET": "secret",
    }.items():
        monkeypatch.setenv(name, value)
    try:
        load_config(False)
    except ConfigError as exc:
        assert "single line" in str(exc)
    else:
        raise AssertionError("a broken API key must not load")
    try:
        MexcClient("line\nkey", "secret")
    except MexcError as exc:
        assert "single line" in str(exc)
    else:
        raise AssertionError("a broken API key must not sign")
    book = Book(cash_micro=1_000_000, positions=[], realized_micro=0)
    assert record_buy(book, "BTCUSDT", 1, 1, 1, 0, 1, "a" * 8, "1") is False
    assert book.cash_micro == 1_000_000
    held = Book(
        cash_micro=0,
        positions=[Position("BTCUSDT", 1, 1, 1, 1, "test")],
        realized_micro=0,
        fees_micro=True,
    )
    assert record_sell_fill(held, "BTCUSDT", 1, 1, 0) is False
    assert held.cash_micro == 0
    held.fees_micro = 0
    held.positions[0].reason = 1
    try:
        audit_book(held)
    except LedgerError as exc:
        assert "text" in str(exc)
    else:
        raise AssertionError("a numeric reason must not be saved")


def test_a_signed_request_stays_on_the_api_path(tmp_path) -> None:
    from datetime import datetime

    from spotbot.config import Config, ConfigError, require_cycle_config
    from spotbot.journal import note_event
    from spotbot.mexc import MexcClient, MexcError, _retry_after_sec, new_client_order_id
    from spotbot.ops_http import _heartbeat

    client = MexcClient("key", "secret")
    for call in (
        lambda: client._signed("DELETE", "/api/v3/order", {}),
        lambda: client._signed("GET", "https://evil.example/api", {}),
        lambda: client._signed("GET", "/api/v3/account", {"symbol": 1}),
        lambda: client._public("/api/v3/time", {"limit": True}),
        lambda: new_client_order_id(1, "B"),
        lambda: new_client_order_id("BTCUSDT", "BUY"),
    ):
        try:
            call()
        except MexcError as exc:
            assert "refused" in str(exc) or "text" in str(exc) or "USDT" in str(exc)
        else:
            raise AssertionError("a bad request must not be signed")
    assert _retry_after_sec(1) is None
    assert _retry_after_sec("9" * 20) is None
    cfg = Config(
        symbols=("BTCUSDT",),
        paper_cash_micro=20_000_000,
        interval_sec=60,
        max_positions=1,
        alloc_bps=10_000,
        min_notional_micro=1_000_000,
        rsi_buy=35,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        live=False,
        mode="rsi",
        taker_bps=5,
        daily_loss_bps=500,
        stop_cooldown_sec=900,
        symbol_lock=False,
        api_key="line\nkey",
        api_secret="secret",
    )
    try:
        require_cycle_config(cfg)
    except ConfigError as exc:
        assert "single line" in str(exc)
    else:
        raise AssertionError("a broken key must not pass the cycle check")
    note_event(tmp_path, kind=object())
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    (tmp_path / "ops_heartbeat.json").write_text(
        '{"at": "%s", "book": 1}' % stamp,
        encoding="utf-8",
    )
    beat = _heartbeat(tmp_path)
    assert beat is not None and beat["book"] == ""


def test_a_long_digit_string_is_not_a_setting(monkeypatch, tmp_path) -> None:
    from spotbot.config import ConfigError, _env_int, load_config
    from spotbot.money import MoneyError, parse_micro
    from spotbot.ops_http import OpsError, _heartbeat, _public, _show_book, parse_ops_port
    from spotbot.ops_main import main as ops_main
    from spotbot.state import Book, LedgerError, audit_book

    try:
        parse_ops_port(19280)
    except OpsError as exc:
        assert "integer" in str(exc)
    else:
        raise AssertionError("a numeric port must not be parsed")
    try:
        parse_ops_port("9" * 20)
    except OpsError as exc:
        assert "integer" in str(exc)
    else:
        raise AssertionError("a huge port must not be parsed")
    assert ops_main(["--port", "18180"]) == 2
    monkeypatch.setenv("SPOT_INTERVAL_SEC", "9" * 20)
    try:
        _env_int("SPOT_INTERVAL_SEC", "60", 15, 86_400)
    except ConfigError as exc:
        assert "integer" in str(exc)
    else:
        raise AssertionError("a huge interval must not load")
    monkeypatch.setenv("SPOT_SYMBOLS", "BTCUSDT," * 80)
    try:
        load_config(False)
    except ConfigError as exc:
        assert "SPOT_SYMBOLS" in str(exc)
    else:
        raise AssertionError("a huge symbol list must not load")
    try:
        parse_micro("1" * 81)
    except MoneyError as exc:
        assert "long" in str(exc)
    else:
        raise AssertionError("a huge decimal must not be read")
    book = Book(cash_micro=0, positions=[], realized_micro=0)
    book.ledger = 1
    try:
        audit_book(book)
    except LedgerError as exc:
        assert "paper" in str(exc)
    else:
        raise AssertionError("a numeric ledger must not be saved")
    shown = _show_book({"positions": [{"entry_micro": 10**25, "peak_micro": 1}], "price_scale": 1_000_000_000_000})
    assert shown["positions"][0]["entry_micro"] == "unreadable"
    assert _public({1: "hidden-by-type"}) == {}
    (tmp_path / "ops_heartbeat.json").write_bytes(b"{" + b"0" * 1_000_001)
    assert _heartbeat(tmp_path) is None


def test_an_amount_above_the_ceiling_is_not_money() -> None:
    from spotbot.config import Config, ConfigError, load_config, require_cycle_config
    from spotbot.mexc import MexcClient, MexcError
    from spotbot.money import MoneyError, decimal_text, format_usdt, notional_micro, to_satoshi
    from spotbot.state import Book, LedgerError, Position, audit_book, load_book

    try:
        decimal_text(10**80)
    except MoneyError as exc:
        assert "long" in str(exc)
    else:
        raise AssertionError("a huge integer must not become decimal text")
    try:
        to_satoshi(10**24)
    except MoneyError as exc:
        assert "long" in str(exc)
    else:
        raise AssertionError("a huge integer must not become satoshi")
    try:
        notional_micro(10**20, 10**20)
    except MoneyError as exc:
        assert "long" in str(exc)
    else:
        raise AssertionError("a huge notional must not be booked")
    try:
        format_usdt(10**24)
    except MoneyError as exc:
        assert "integer" in str(exc)
    else:
        raise AssertionError("a huge balance must not be printed")
    book = Book(cash_micro=10**24, positions=[], realized_micro=0)
    try:
        audit_book(book)
    except LedgerError as exc:
        assert "large" in str(exc)
    else:
        raise AssertionError("a huge cash balance must not be saved")
    try:
        load_book(__import__("pathlib").Path("missing-ceiling.json"), 10**24)
    except LedgerError as exc:
        assert "integer" in str(exc)
    else:
        raise AssertionError("huge paper cash must not open a book")
    held = Book(
        cash_micro=0,
        positions=[Position("BTCUSDT", 10**24, 10**24, 1, 1, "test")],
        realized_micro=0,
    )
    try:
        audit_book(held)
    except LedgerError as exc:
        assert "large" in str(exc)
    else:
        raise AssertionError("a huge entry must not be saved")
    try:
        MexcClient("k" * 257, "secret")
    except MexcError as exc:
        assert "single line" in str(exc)
    else:
        raise AssertionError("a huge API key must not be kept")
    cfg = Config(
        symbols=("BTCUSDT",),
        paper_cash_micro=1_000_000,
        interval_sec=60,
        max_positions=1,
        alloc_bps=10_000,
        min_notional_micro=1_000_000,
        rsi_buy=35,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        live=False,
        mode="rsi",
        taker_bps=5,
        daily_loss_bps=500,
        stop_cooldown_sec=900,
        symbol_lock=False,
        api_key="k" * 257,
        api_secret="secret",
    )
    try:
        require_cycle_config(cfg)
    except ConfigError as exc:
        assert "single line" in str(exc)
    else:
        raise AssertionError("a huge API key must not pass the cycle check")
    try:
        load_config(False, "r" * 40)
    except ConfigError as exc:
        assert "rsi" in str(exc)
    else:
        raise AssertionError("a huge mode name must not load")
    client = MexcClient("key", "secret")
    try:
        client._signed("GET", "/api/v3/account", {"symbol": "X" * 81})
    except MexcError as exc:
        assert "text" in str(exc)
    else:
        raise AssertionError("a huge query value must not be signed")


def test_a_product_above_the_ceiling_is_not_a_fill() -> None:
    from spotbot.exits import pnl_bps
    from spotbot.fees import fee_on, paper_buy, paper_sell
    from spotbot.mexc import MexcError, _base_atoms, depth_notionals
    from spotbot.money import MoneyError, base_for_quote, implied_price_micro
    from spotbot.rules import plan_paper_buy
    from spotbot.sanity import mark_ok, price_ok, slip_price

    assert base_for_quote(10**20, 1) == 0
    try:
        implied_price_micro(10**20, 1)
    except MoneyError as exc:
        assert "long" in str(exc) or "positive" in str(exc)
    else:
        raise AssertionError("a huge fill price must not be booked")
    try:
        fee_on(1_000_000, 101)
    except ValueError as exc:
        assert "fee" in str(exc)
    else:
        raise AssertionError("a fee above 100 bps must not be charged")
    assert paper_buy(1_000_000, 1_000_000_000_000, 101) == (0, 0)
    assert paper_sell(10**20, 10**20, 5) == (0, 0)
    assert plan_paper_buy(1_000_000, 1_000_000_000_000, 100, 101) is None
    assert slip_price(10**23, 10_001, True) == 0
    assert price_ok(10**24, 10**24) is False
    assert mark_ok(10**24, 1) is False
    try:
        pnl_bps(10**24, 1)
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("a price at the ceiling must not be a profit")
    try:
        _base_atoms("10000000000000000")
    except MexcError as exc:
        assert "large" in str(exc)
    else:
        raise AssertionError("a huge fill must not become atoms")
    qty = "600000000000000000"
    try:
        depth_notionals(
            {
                "bids": [["1", qty], ["1.1", qty]],
                "asks": [["2", "1"]],
                "lastUpdateId": 1,
            },
            "BTCUSDT",
        )
    except MexcError as exc:
        assert "large" in str(exc)
    else:
        raise AssertionError("a huge depth sum must not be a wall")


def test_a_fraction_is_not_a_volume_signal() -> None:
    from spotbot.liquidity import candle_lift, close_position_bps, lift_signal
    from spotbot.mexc import MexcError, _depth_side, parse_account, parse_klines, positive_int
    from spotbot.money import format_price

    volumes = [1] * 12 + [4, 1]
    assert volume_ratio_bps(volumes[:-1] + [1.5]) is None
    assert close_position_bps(1.5, 1, 1) is None
    assert candle_lift(1, volumes, 110, 100, 108) is None
    assert lift_signal("BTCUSDT", volumes, 110, 100, 108, 1.5, 1.0) is None
    assert ask_wall_exit(1.5, 2.0, 40) is False
    assert ask_wall_exit(1_000, 2_000, 40) is True
    price = 10**24 - 1
    target = price * (10_000 + 700) // 10_000
    shown = format_price(target) if isinstance(target, int) and 0 < target < 10**24 else "unreadable"
    assert shown == "unreadable"
    try:
        positive_int("1" * 25, "time")
        raise AssertionError("a long time must not be read")
    except MexcError as exc:
        assert "integer" in str(exc) or "large" in str(exc)
    try:
        parse_klines("BTCUSDT", [[]] * 1_001)
        raise AssertionError("too many candles must not be parsed")
    except MexcError as exc:
        assert "many" in str(exc)
    try:
        _depth_side([["1", "1"]] * 5_001)
        raise AssertionError("too many levels must not be parsed")
    except MexcError as exc:
        assert "large" in str(exc)
    try:
        parse_account({"balances": [{}] * 5_001})
        raise AssertionError("too many balances must not be parsed")
    except MexcError as exc:
        assert "many" in str(exc)


def test_a_ceiling_price_is_not_a_peer_or_a_score() -> None:
    from spotbot.analyzer import score
    from spotbot.guards import drawdown_blocks, marked_equity, note_pair_stop, top_spread_bps
    from spotbot.mexc import MexcError, _public_limit, rank_liquid
    from spotbot.oracle import deviation_bps, entry_allowed, lag_bps, venue_quotes
    from spotbot.signals import entry_signal
    from spotbot.state import Book, Position

    ceiling = 10**24
    assert lag_bps(ceiling, [100]) is None
    assert deviation_bps([ceiling, 100]) is None
    assert entry_allowed(ceiling, [100]) is False
    assert venue_quotes("BTCETH") == {}
    assert score(40_000, 8_000, 10, 30, 2**63, 1) == 0
    assert score(40_000, 8_000, 10, 30, 2_000, 1_000) > 0
    assert entry_signal(1, [100] * 20, 35) is None
    assert marked_equity(1, [Position("BTCUSDT", 1, 1, 1, ceiling, "")], {"BTCUSDT": ceiling}, None) is None
    assert drawdown_blocks(ceiling, 1, 1_000) is True
    try:
        top_spread_bps(ceiling, ceiling)
        raise AssertionError("a ceiling book must not be a spread")
    except ValueError:
        pass
    try:
        rank_liquid([{}] * 20_001, 1, -10_000, 10_000, 8)
        raise AssertionError("a huge ticker must not be ranked")
    except MexcError as exc:
        assert "large" in str(exc)
    try:
        _public_limit(5_001, "depth")
        raise AssertionError("a huge limit must not be sent")
    except MexcError as exc:
        assert "large" in str(exc)
    book = Book(cash_micro=1, positions=[], realized_micro=0)
    book.pair_stops = {"BTCUSDT": ["nope"]}
    note_pair_stop(book, "BTCUSDT", 1_700_000_000, 3, 60)
    assert book.pair_stops["BTCUSDT"] == [1_700_000_000]


def test_a_long_book_is_not_opened_and_a_list_is_not_one_price(tmp_path) -> None:
    from spotbot.mexc import MexcError, _reject_exchange_code, _require_filled, clock_allows, signed_payload
    from spotbot.oracle import _bybit_price, _okx_price
    from spotbot.reconcile import FeeAssetError, split_commission
    from spotbot.rules import parse_symbol_rule
    from spotbot.sleeves import SleeveError, apply_funding
    from spotbot.state import LedgerError, load_book

    assert clock_allows(10**15, 10**15) is False
    assert clock_allows(1_700_000_000_000, 1_700_000_000_100) is True
    assert _bybit_price({"result": {"list": [{"symbol": "BTCUSDT", "lastPrice": "1"}, {"symbol": "BTCUSDT", "lastPrice": "2"}]}}, "BTCUSDT") is None
    assert _okx_price({"data": [{"instId": "BTC-USDT", "last": "1"}, {"instId": "BTC-USDT", "last": "2"}]}, "BTC-USDT") is None
    try:
        _require_filled({"status": {"not": "text"}}, "fill")
        raise AssertionError("a status object must not be filled")
    except MexcError as exc:
        assert "filled" in str(exc)
    assert _require_filled({"status": 2}, "fill") is None
    try:
        signed_payload([{}] * 5_001, True)
        raise AssertionError("a huge trade list must not be read")
    except MexcError as exc:
        assert "large" in str(exc)
    try:
        _reject_exchange_code({"code": {"bad": True}, "msg": {"bad": True}})
        raise AssertionError("a code object must not be success")
    except MexcError as exc:
        assert "refused" in str(exc)
    try:
        split_commission([{}] * 5_001, "1", "BTC", "BUY")
        raise AssertionError("a huge trade list must not be a fee")
    except FeeAssetError as exc:
        assert "large" in str(exc)
    rule = parse_symbol_rule(
        {
            "symbol": "BTCUSDT",
            "status": "1",
            "isSpotTradingAllowed": True,
            "quoteAsset": "USDT",
            "baseAsset": "BTC",
            "st": False,
            "conceptPlates": ["x"] * 33,
            "orderTypes": ["MARKET"],
            "tradeSideType": "1",
            "takerCommission": "0.0005",
            "baseSizePrecision": "0.000001",
            "quoteAmountPrecisionMarket": "1",
            "quotePrecision": "2",
            "maxQuoteAmountMarket": "100000",
        }
    )
    assert rule.tradable is False
    path = tmp_path / "wide.json"
    path.write_text('{"cash_micro": 1, "positions": [' + ",".join(['{"symbol":"BTCUSDT","entry_micro":1,"peak_micro":1,"quote_micro":1,"base_atoms":1,"reason":""}'] * 9) + "]}", encoding="utf-8")
    try:
        load_book(path, 0)
        raise AssertionError("nine positions must not open")
    except LedgerError as exc:
        assert "many" in str(exc)
    try:
        apply_funding(tmp_path / "fund", 10**24)
        raise AssertionError("a ceiling deposit must not fund sleeves")
    except SleeveError as exc:
        assert "integer" in str(exc)


def test_an_order_at_the_ceiling_is_not_sent(tmp_path) -> None:
    from spotbot.config import ConfigError, require_cycle_config
    from spotbot.journal import note_quote
    from spotbot.mexc import MexcError, _interval_ms, _order_request
    from spotbot.oracle import deviation_bps, lag_bps
    from spotbot.reconcile import FeeAssetError, base_is_free, inventory_mismatch, order_missing, usdt_commission
    from spotbot.sleeves import SleeveError, split_equal
    from spotbot.state import LedgerError, _pair_stops

    try:
        _order_request("BTCUSDT", "abc", 10**24)
        raise AssertionError("a ceiling order must not be sent")
    except MexcError as exc:
        assert "size" in str(exc) or "positive" in str(exc)
    try:
        _interval_ms(1)
        raise AssertionError("a numeric interval must not be used")
    except MexcError as exc:
        assert "interval" in str(exc)
    assert lag_bps(100, [100] * 9) is None
    assert deviation_bps([100] * 9) is None
    assert base_is_free(10**24, 1) is False
    assert inventory_mismatch([], {1: 1}) == "exchange asset is not text"
    assert order_missing("x" * 513) is False
    try:
        usdt_commission([{}] * 5_001, "1")
        raise AssertionError("a huge fee list must not be summed")
    except FeeAssetError as exc:
        assert "large" in str(exc)
    try:
        split_equal(1, 9)
        raise AssertionError("a split into nine parts must be refused")
    except SleeveError:
        pass
    try:
        _pair_stops({f"A{i}USDT": [1] for i in range(15)})
        raise AssertionError("fifteen stop maps must not load")
    except LedgerError as exc:
        assert "many" in str(exc)
    note_quote(tmp_path, 1, "1", "1", "1", "1", 0, 0)
    assert not (tmp_path / "ops_quotes.json").exists()
    try:
        from spotbot.config import Config

        built = Config(
            symbols=tuple(f"A{i}USDT" for i in range(15)),
            paper_cash_micro=1,
            interval_sec=60,
            max_positions=1,
            alloc_bps=10_000,
            min_notional_micro=1,
            rsi_buy=35,
            stop_bps=350,
            take_bps=700,
            trail_arm_bps=300,
            trail_gap_bps=200,
            live=False,
            mode="rsi",
            taker_bps=5,
            daily_loss_bps=500,
            stop_cooldown_sec=900,
            symbol_lock=False,
            api_key="",
            api_secret="",
        )
        require_cycle_config(built)
        raise AssertionError("fifteen symbols must not enter a cycle")
    except ConfigError as exc:
        assert "symbol" in str(exc).lower() or "repeated" in str(exc)
    built = Config(
        symbols=("BTCUSDT",),
        paper_cash_micro=1,
        interval_sec=60,
        max_positions=1,
        alloc_bps=10_000,
        min_notional_micro=1,
        rsi_buy=35,
        stop_bps=10_001,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        live=False,
        mode="rsi",
        taker_bps=5,
        daily_loss_bps=500,
        stop_cooldown_sec=900,
        symbol_lock=False,
        api_key="",
        api_secret="",
    )
    try:
        require_cycle_config(built)
        raise AssertionError("an exit wider than the whole price must not run")
    except ConfigError as exc:
        assert "range" in str(exc)


def test_a_long_reason_does_not_debit() -> None:
    from spotbot.engine import sibling_pending
    from spotbot.mexc import MexcClient, MexcError
    from spotbot.oracle import venue_quotes
    from spotbot.reconcile import fee_fits, fills_match, order_is_ours
    from spotbot.state import Book, LedgerError, remember_pending, record_buy

    book = Book(cash_micro=1_000_000, positions=[], realized_micro=0)
    assert record_buy(book, "BTCUSDT", 1, 1, 1, 0, "x" * 81, "a" * 8, "1") is False
    assert book.cash_micro == 1_000_000
    try:
        remember_pending(book, "a" * 8, "BTCUSDT", "BUY", 10**24, 1)
        raise AssertionError("a ceiling pending size must not be stored")
    except LedgerError as exc:
        assert "integer" in str(exc) or "large" in str(exc) or "size" in str(exc)
    assert fills_match(10**24, 1, 10**24, 1) is False
    assert fee_fits(10**24, 10**24) is False
    assert order_is_ours({"clientOrderId": "a" * 8, "symbol": "BTCUSDT", "side": "BUY", "type": "MARKET"}, "BTCUSDT", "BUY", "a" * 40) is False
    assert venue_quotes("BTCUSDT", 31) == {}
    try:
        MexcClient("", "", 31)
        raise AssertionError("a long timeout must not be kept")
    except MexcError as exc:
        assert "timeout" in str(exc)
    assert sibling_pending(tuple(__import__("pathlib").Path(f"missing-{i}.json") for i in range(9))) == "too many sibling books"


def test_a_sell_does_not_push_cash_over_the_ceiling() -> None:
    from spotbot.engine import mark_stop_cooldown, open_loss_micro
    from spotbot.guards import note_pair_stop
    from spotbot.mexc import DecimalChange, MexcError, parse_account
    from spotbot.oracle import cheapest_first
    from spotbot.state import Book, Position, record_buy, record_sell_fill

    book = Book(cash_micro=10**24 - 5, positions=[Position("BTCUSDT", 10, 10, 10, 10, "held")], realized_micro=0)
    assert record_sell_fill(book, "BTCUSDT", 10, 10, 0) is False
    assert book.cash_micro == 10**24 - 5
    assert book.positions[0].base_atoms == 10
    fresh = Book(cash_micro=1_000_000, positions=[], realized_micro=0)
    assert record_buy(fresh, "BTCUSDT", 10**24, 1, 1, 0, "held", "a" * 8, "1") is False
    assert fresh.cash_micro == 1_000_000
    mark_stop_cooldown(fresh, "stop", 10**12)
    assert fresh.cooldown_until <= __import__("time").time() + 86_401
    locked = Book(cash_micro=1, positions=[], realized_micro=0)
    note_pair_stop(locked, "BTCUSDT", 1_700_000_000, 3, 10**12)
    note_pair_stop(locked, "BTCUSDT", 1_700_000_001, 3, 10**12)
    note_pair_stop(locked, "BTCUSDT", 1_700_000_002, 3, 10**12)
    assert locked.pair_lock_until["BTCUSDT"] == 1_700_000_002 + 86_400
    try:
        DecimalChange("10000000000")
        raise AssertionError("a huge percent must not be a change")
    except ValueError as exc:
        assert "large" in str(exc)
    try:
        parse_account(
            {
                "balances": [
                    {"asset": "USDT", "free": "999999999999999999", "locked": "999999999999999999"},
                ]
            }
        )
        raise AssertionError("two huge balances must not be a balance")
    except MexcError as exc:
        assert "large" in str(exc)
    assert cheapest_first([("BTCUSDT", 1)] * 33) == []
    rich = Position("BTCUSDT", 1, 1, 10**24, 1, "held")
    assert open_loss_micro([rich], {"BTCUSDT": 1}) == 2**62


def test_a_ceiling_price_is_not_a_log_crash(tmp_path) -> None:
    from spotbot.engine import _note_miss, _shown_price
    from spotbot.ops_http import _heartbeat, _quotes, _show_book
    from spotbot.state import Book, Position, apply_buy_progress

    assert _shown_price(10**24) == "unreadable"
    assert _shown_price(1_000_000_000_000) == "1"
    view = _show_book({"positions": [{"symbol": "BTCUSDT", "entry_micro": 10**24, "peak_micro": 1}], "price_scale": 1_000_000_000_000})
    assert view["positions"][0]["entry_micro"] == "unreadable"
    wide = _show_book({"positions": [{}] * 9, "price_scale": 1_000_000_000_000})
    assert wide["positions"] == "unreadable"
    (tmp_path / "ops_heartbeat.json").write_text('{"at": "%s", "book": "major"}' % ("x" * 41), encoding="utf-8")
    assert _heartbeat(tmp_path) is None
    quotes = {f"A{i}USDT": {"mexc": "1"} for i in range(33)}
    (tmp_path / "ops_quotes.json").write_text(__import__("json").dumps(quotes), encoding="utf-8")
    assert _quotes(tmp_path) == {}
    book = Book(cash_micro=1_000, positions=[], realized_micro=0)
    book.pending_misses = 1_000
    _note_miss(book)
    assert book.pending_misses == 1_000
    held = Book(
        cash_micro=1_000,
        positions=[Position("BTCUSDT", 1, 1, 0, 0, "held", "abcdefgh")],
        realized_micro=0,
    )
    held.pending_side = "BUY"
    held.pending_client_id = "abcdefgh"
    held.pending_symbol = "BTCUSDT"
    held.pending_quote_micro = 1
    assert apply_buy_progress(held, "BTCUSDT", 1, 10**24, 1, 0, "held", "abcdefgh", "1") is False
    assert held.cash_micro == 1_000


def test_an_open_split_is_finished_once(tmp_path) -> None:
    import json

    from spotbot.__main__ import CYCLE_HOLDS
    from spotbot.money import MoneyError
    from spotbot.sleeves import SleeveError, apply_funding, split_equal
    from spotbot.state import load_book, save_book, usdt_symbol_ok

    assert usdt_symbol_ok("BTCUSDT") is True
    assert usdt_symbol_ok("ABCDEFGHIJKUSDT") is False
    assert isinstance(MoneyError("cash"), CYCLE_HOLDS)
    assert isinstance(ValueError("price"), CYCLE_HOLDS)
    assert isinstance(SleeveError("stop"), CYCLE_HOLDS) is False
    apply_funding(tmp_path, 90_000_000)
    root = tmp_path / "paper"
    major = load_book(root / "sleeve_major.json", 0)
    alt = load_book(root / "sleeve_alt.json", 0)
    meme = load_book(root / "sleeve_meme.json", 0)
    delta = split_equal(30_000_000, 3)
    major.cash_micro += delta[0]
    major.credited_main_micro = 120_000_000
    save_book(root / "sleeve_major.json", major)
    (root / "treasury.json").write_text(
        json.dumps(
            {
                "funded_micro": 90_000_000,
                "sleeves": ["major", "alt", "meme"],
                "pending": {"target_micro": 120_000_000, "parts": list(delta)},
            }
        ),
        encoding="utf-8",
    )
    major_cash = major.cash_micro
    alt_cash = alt.cash_micro
    meme_cash = meme.cash_micro
    try:
        apply_funding(tmp_path, 150_000_000)
        raise AssertionError("a different main must not retarget an open split")
    except SleeveError as exc:
        assert "open" in str(exc)
    assert load_book(root / "sleeve_major.json", 0).cash_micro == major_cash
    assert apply_funding(tmp_path, 120_000_000) == (0, delta[1], delta[2])
    assert load_book(root / "sleeve_major.json", 0).cash_micro == major_cash
    assert load_book(root / "sleeve_alt.json", 0).cash_micro == alt_cash + delta[1]
    assert load_book(root / "sleeve_meme.json", 0).cash_micro == meme_cash + delta[2]
    sealed = json.loads((root / "treasury.json").read_text(encoding="utf-8"))
    assert sealed["funded_micro"] == 120_000_000
    assert "pending" not in sealed
    assert apply_funding(tmp_path, 120_000_000) == (0, 0, 0)
    assert load_book(root / "sleeve_major.json", 0).cash_micro == major_cash


def test_a_value_error_keeps_the_peak_already_moved(tmp_path, monkeypatch) -> None:
    from spotbot.config import Config
    from spotbot.engine import run_cycle
    from spotbot.rules import SymbolRule
    from spotbot.state import Book, Position, load_book, save_book

    monkeypatch.setattr("spotbot.engine.venue_quotes", lambda _symbol: {})
    entry = 100_000_000_000_000
    higher = 100_100_000_000_000

    class _SecondBreaks:
        def forget_rules(self) -> None:
            return None

        def symbol_rule(self, symbol: str) -> SymbolRule:
            return SymbolRule(symbol, True, "", 5, 1, 1, 0, symbol.replace("USDT", ""))

        def book_top(self, symbol: str) -> tuple[int, int]:
            if symbol == "ETHUSDT":
                raise ValueError("bid is not a price")
            return higher, higher + 1

    cfg = Config(
        symbols=("BTCUSDT", "ETHUSDT"),
        paper_cash_micro=1_000_000,
        interval_sec=60,
        max_positions=2,
        alloc_bps=10_000,
        min_notional_micro=1,
        rsi_buy=35,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=10_000,
        trail_gap_bps=10_000,
        live=False,
        mode="rsi",
        taker_bps=5,
        daily_loss_bps=500,
        stop_cooldown_sec=0,
        symbol_lock=True,
        api_key="",
        api_secret="",
    )
    path = tmp_path / "kept.json"
    save_book(
        path,
        Book(
            cash_micro=1_000_000,
            positions=[
                Position("BTCUSDT", entry, entry, 10_000_000, 100_000_000, "test"),
                Position("ETHUSDT", entry, entry, 10_000_000, 100_000_000, "test"),
            ],
            realized_micro=0,
        ),
    )
    try:
        run_cycle(cfg, _SecondBreaks(), path)
    except ValueError as exc:
        assert "price" in str(exc)
    else:
        raise AssertionError("a bad bid must leave the cycle after the book is saved")
    saved = load_book(path, 0)
    peaks = {pos.symbol: pos.peak_micro for pos in saved.positions}
    assert peaks["BTCUSDT"] == higher
    assert peaks["ETHUSDT"] == entry


def test_a_clock_limit_still_saves_the_morning_stamp(tmp_path) -> None:
    from spotbot.config import Config
    from spotbot.engine import run_cycle, trading_day
    from spotbot.mexc import MexcRateLimit
    from spotbot.state import Book, load_book, save_book

    class _ClockLimited:
        def forget_rules(self) -> None:
            return None

        def server_time_ms(self) -> int:
            raise MexcRateLimit("429")

        def book_top(self, _symbol: str) -> tuple[int, int]:
            raise AssertionError("a clock limit must not read the book")

    cfg = Config(
        symbols=("BTCUSDT",),
        paper_cash_micro=1_000_000,
        interval_sec=60,
        max_positions=1,
        alloc_bps=10_000,
        min_notional_micro=1,
        rsi_buy=35,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        live=True,
        mode="rsi",
        taker_bps=5,
        daily_loss_bps=500,
        stop_cooldown_sec=0,
        symbol_lock=True,
        api_key="",
        api_secret="",
    )
    path = tmp_path / "clock.json"
    save_book(path, Book(cash_micro=1_000_000, positions=[], realized_micro=0))
    book = load_book(path, 0)
    book.guard_day = "2000-01-01"
    book.guard_cash_micro = 1
    save_book(path, book)
    try:
        run_cycle(cfg, _ClockLimited(), path)
    except MexcRateLimit as exc:
        assert "429" in str(exc)
    else:
        raise AssertionError("a clock limit must leave the cycle after the book is saved")
    saved = load_book(path, 0)
    assert saved.guard_day == trading_day()
    assert saved.guard_cash_micro == 1_000_000
    assert saved.ledger == "live"


def test_a_second_holder_does_not_open_the_same_ledger(tmp_path) -> None:
    from spotbot.state import LedgerError, hold_ledger

    with hold_ledger(tmp_path):
        try:
            with hold_ledger(tmp_path):
                raise AssertionError("two holders must not share a ledger")
        except LedgerError as exc:
            assert "holds" in str(exc)
    with hold_ledger(tmp_path):
        pass


def test_an_accepted_order_keeps_its_exchange_id(tmp_path) -> None:
    from spotbot.engine import _keep_exchange_ack
    from spotbot.mexc import MexcClient, MexcError, MexcOrderAccepted
    from spotbot.reconcile import pending_gone
    from spotbot.state import load_book, remember_pending, save_book

    client_id = "a" * 32

    class _Partial(MexcClient):
        def _signed(self, _method: str, _path: str, _query: dict[str, str]) -> dict[str, object]:
            return {
                "symbol": "BTCUSDT",
                "side": "BUY",
                "type": "MARKET",
                "clientOrderId": client_id,
                "orderId": "42",
                "status": "PARTIALLY_FILLED",
            }

    try:
        _Partial("", "").market_buy_quote("BTCUSDT", 1_000_000, client_id)
        raise AssertionError("a partial ack must not be booked as a full fill")
    except MexcOrderAccepted as exc:
        assert exc.exchange_order_id == "42"
        assert "filled" in str(exc)
    except MexcError as exc:
        raise AssertionError(f"a partial ack must keep the exchange id: {exc}") from exc
    path = tmp_path / "ack.json"
    book = load_book(path, 1_000_000)
    remember_pending(book, client_id, "BTCUSDT", "BUY", 0, 1_000_000)
    save_book(path, book)
    _keep_exchange_ack(book, path, MexcOrderAccepted("buy status is not filled", "42"))
    saved = load_book(path, 0)
    assert saved.pending_client_id == client_id
    assert saved.pending_exchange_order_id == "42"
    assert pending_gone(3, 0, False, bool(saved.pending_exchange_order_id)) is False


def test_a_ceiling_size_is_not_an_order_and_a_far_candle_is_not_a_time(tmp_path) -> None:
    from spotbot.journal import note_heartbeat
    from spotbot.mexc import MexcError, parse_klines
    from spotbot.ops_http import _heartbeat
    from spotbot.rules import budget_micro, cap_spend, round_base_atoms, round_quote_micro, uses_slot
    from spotbot.signals import closed_prices
    from spotbot.state import Book, LedgerError, save_book

    assert round_base_atoms(10**24, 1) == 0
    assert uses_slot(10**24, 1) is True
    assert round_quote_micro(10**24, 1) == 0
    assert budget_micro(10**24, 10_000) == 0
    assert cap_spend(10**24, 10, 1, 1, 0) == 0
    assert closed_prices("1234") == []
    assert closed_prices([10, 20, 30]) == [10, 20]
    far = [10**15, "1", "1.1", "0.9", "1", "1", 10**15 + 1_000, "10"]
    nxt = [10**15 + 2_000, "1", "1.1", "0.9", "1", "1", 10**15 + 3_000, "10"]
    try:
        parse_klines("BTCUSDT", [far, nxt])
        raise AssertionError("a candle time past the clock ceiling must not be read")
    except MexcError as exc:
        assert "time" in str(exc)
    book = Book(cash_micro=1_000, positions=[], realized_micro=0)
    book.pending_misses = 1_001
    try:
        save_book(tmp_path / "misses.json", book)
        raise AssertionError("more than 1000 misses must not be saved")
    except LedgerError as exc:
        assert "miss" in str(exc)
    note_heartbeat(tmp_path, "x" * 33)
    assert _heartbeat(tmp_path)["book"] == ""
    note_heartbeat(tmp_path, "major")
    assert _heartbeat(tmp_path)["book"] == "major"


def test_a_wide_row_is_not_a_candle_and_a_deep_page_is_not_unfolded() -> None:
    from spotbot.mexc import MexcError, _base_asset, _depth_side, ack_commission, parse_klines
    from spotbot.ops_http import _public

    assert _base_asset("BTCUSDT") == "BTC"
    try:
        _base_asset("ABCDEFGHIJKUSDT")
        raise AssertionError("a base longer than 10 characters must not be a pair")
    except MexcError as exc:
        assert "USDT" in str(exc)
    try:
        ack_commission({"commission": "1", "commissionAsset": "not coin"}, "BTC")
        raise AssertionError("a commission name with a space must not be a fee")
    except MexcError as exc:
        assert "text" in str(exc)
    try:
        ack_commission({"commission": "10000000000000000", "commissionAsset": "BTC"}, "BTC")
        raise AssertionError("a base commission at the ceiling must not be booked")
    except MexcError as exc:
        assert "large" in str(exc) or "decimal" in str(exc)
    wide_level = ["1", "1", "0", "0", "0", "0", "0", "0", "0"]
    try:
        _depth_side([wide_level])
        raise AssertionError("a depth level wider than eight fields must not be read")
    except MexcError as exc:
        assert "wide" in str(exc)
    candle = [1_000, "1", "1.1", "0.9", "1", "1", 2_000, "10"] + [0] * 9
    later = [3_000, "1", "1.1", "0.9", "1", "1", 4_000, "10"]
    try:
        parse_klines("BTCUSDT", [candle, later])
        raise AssertionError("a kline row wider than sixteen fields must not be read")
    except MexcError as exc:
        assert "row" in str(exc)
    nested: object = "x"
    for _ in range(12):
        nested = [nested]
    shown = _public(nested)
    steps = 0
    while isinstance(shown, list):
        shown = shown[0]
        steps += 1
    assert shown == "unreadable"
    assert steps <= 8
    assert _public({"k": "y" * 200})["k"] == "y" * 180
    assert _public({str(i): 1 for i in range(65)}) == "unreadable"


def test_a_huge_lot_step_does_not_open_the_pair(tmp_path) -> None:
    from spotbot.guards import note_pair_stop, pair_locked
    from spotbot.ops_http import _events, _log_tail
    from spotbot.rules import _price_tick, parse_symbol_rule
    from spotbot.state import Book

    row = {
        "symbol": "BTCUSDT",
        "status": "1",
        "isSpotTradingAllowed": True,
        "quoteAsset": "USDT",
        "st": False,
        "baseAsset": "BTC",
        "quotePrecision": "2",
        "orderTypes": ["MARKET"],
        "tradeSideType": "1",
        "takerCommission": "0.0005",
        "baseSizePrecision": "10000000000000000",
        "quoteAmountPrecisionMarket": "1",
    }
    wide = parse_symbol_rule(row)
    assert wide.tradable is False
    assert "large" in wide.refuse_reason
    assert _price_tick(10**20)[0] == 0
    assert _price_tick({"places": 2})[0] == 0
    long_name = dict(row)
    long_name["symbol"] = "ABCDEFGHIJKUSDT"
    long_name["baseAsset"] = "ABCDEFGHIJK"
    long_name["baseSizePrecision"] = "0.000001"
    assert parse_symbol_rule(long_name).tradable is False
    plate = dict(row)
    plate["baseSizePrecision"] = "0.000001"
    plate["conceptPlates"] = ["x" * 65]
    assert "long" in parse_symbol_rule(plate).refuse_reason
    kind = dict(row)
    kind["baseSizePrecision"] = "0.000001"
    kind["orderTypes"] = ["MARKET", "Y" * 33]
    assert parse_symbol_rule(kind).tradable is False
    book = Book(cash_micro=1_000, positions=[], realized_micro=0)
    note_pair_stop(book, "ABCDEFGHIJKUSDT", 1_700_000_000, 3, 60)
    assert book.pair_stops in (None, {})
    assert pair_locked(book, "ABCDEFGHIJKUSDT", 1_700_000_000) is True
    (tmp_path / "ops.log").write_text(("z" * 300) + "\n", encoding="utf-8")
    assert len(_log_tail(tmp_path / "ops.log")[0]) == 240
    (tmp_path / "ops_events.jsonl").write_text(
        __import__("json").dumps({str(i): 1 for i in range(65)}) + "\n",
        encoding="utf-8",
    )
    assert _events(tmp_path) == []


def test_a_ceiling_balance_is_not_a_match(tmp_path) -> None:
    from pathlib import Path

    from spotbot.engine import _order_fees, _sibling_positions
    from spotbot.journal import note_event
    from spotbot.mexc import _net_text
    from spotbot.oracle import _okx_inst
    from spotbot.reconcile import (
        FeeAssetError,
        ack_fee_matches,
        inventory_mismatch,
        order_filled,
        order_is_ours,
        split_commission,
    )
    from spotbot.state import LedgerError

    assert "not a USDT pair" in (inventory_mismatch([("ABCDEFGHIJKUSDT", 1)], {}) or "")
    assert "too large" in (inventory_mismatch([("BTCUSDT", 10**24)], {}) or "")
    assert inventory_mismatch([], {"BTC": 10**24}) == "exchange balance is too large"
    assert inventory_mismatch([("BTCUSDT", 1)] * 9, {}) == "too many coins"
    try:
        _sibling_positions(tuple(Path(f"missing-{i}.json") for i in range(9)))
    except LedgerError as exc:
        assert "too many" in str(exc)
    else:
        raise AssertionError("nine sibling books must not be read")
    assert _order_fees(None, "ABCDEFGHIJKUSDT", "1", "BUY") is None
    assert _okx_inst("ABCDEFGHIJKUSDT") is None
    assert order_filled({"status": "F" * 33}) is False
    assert order_filled({"status": 10**20}) is False
    assert order_filled({"status": 2}) is True
    ack = {"clientOrderId": "abc", "symbol": "BTCUSDT", "side": "BUY", "type": "M" * 40}
    assert order_is_ours(ack, "BTCUSDT", "BUY", "abc") is False
    assert ack_fee_matches(10**24, 10**24) is False
    try:
        split_commission([], "1", "ABCDEFGHIJK", "BUY")
    except FeeAssetError as exc:
        assert "coin" in str(exc)
    else:
        raise AssertionError("a long base name must not be a fee")
    assert len(_net_text(Exception("z" * 400))) == 180
    note_event(tmp_path, kind="exit", amount=10**24, blob=["no"])
    saved = (tmp_path / "ops_events.jsonl").read_text(encoding="utf-8")
    assert "amount" not in saved and "blob" not in saved and "exit" in saved


def test_a_long_order_id_is_not_read(monkeypatch, tmp_path) -> None:
    from spotbot.config import ConfigError, load_config
    from spotbot.engine import _base_matches, _short
    from spotbot.journal import note_quote
    from spotbot.liquidity import volume_ratio_bps
    from spotbot.mexc import MexcError, _base_atoms, _order_id_text, positive_int, ticker_price
    from spotbot.ops_http import _quotes

    monkeypatch.delenv("SPOT_LIVE", raising=False)
    monkeypatch.delenv("SPOT_ENTRIES", raising=False)
    monkeypatch.setenv("SPOT_SYMBOLS", "2USDT")
    try:
        load_config(False)
    except ConfigError as exc:
        assert "USDT pair" in str(exc)
        assert "2USDT" not in str(exc)
    else:
        raise AssertionError("a digit-only pair must not load")
    try:
        _order_id_text(10**40)
    except MexcError as exc:
        assert "1" + "0" * 40 not in str(exc)
    else:
        raise AssertionError("a huge order id must not be read")
    try:
        _base_atoms("z" * 200)
    except MexcError as exc:
        assert "z" * 200 not in str(exc)
    else:
        raise AssertionError("a long quantity must not be copied into the error")
    assert _base_matches("BTCUSDT", "BTC") is True
    assert _base_matches("BTCUSDT", "X" * 40) is False
    assert _base_matches("2USDT", "2") is False
    try:
        ticker_price({}, "Z" * 80)
    except MexcError as exc:
        assert "Z" * 80 not in str(exc)
    else:
        raise AssertionError("a long pair name must not be copied into the error")
    assert len(_short("a" * 400)) == 180
    assert volume_ratio_bps(None) is None
    try:
        positive_int(True, "q" * 90)
    except MexcError as exc:
        assert "value" in str(exc)
        assert "q" * 90 not in str(exc)
    else:
        raise AssertionError("a long label must not be copied into the error")
    note_quote(tmp_path, "BTCUSDT", "z" * 200, "-", "-", "-", 10**12, None)
    saved = (tmp_path / "ops_quotes.json").read_text(encoding="utf-8")
    assert "unreadable" in saved and "z" * 200 not in saved
    (tmp_path / "ops_quotes.json").write_text(
        '{"BTCUSDT": {"mexc": "%s"}}' % ("m" * 300),
        encoding="utf-8",
    )
    shown = _quotes(tmp_path)["BTCUSDT"]["mexc"]
    assert len(shown) == 180


def test_a_full_disk_is_not_another_process() -> None:
    import errno

    from spotbot.mexc import DecimalChange, MexcClient, MexcError, rank_liquid
    from spotbot.ops_http import _ops_path
    from spotbot.signals import band_reclaim, entry_signal, rsi
    from spotbot.state import _lock_held_by_other

    assert _lock_held_by_other(OSError(errno.EACCES, "busy")) is True
    assert _lock_held_by_other(OSError(errno.ENOSPC, "full")) is False
    assert _ops_path("/api/status") == "/api/status"
    assert _ops_path("z" * 300) is None
    client = MexcClient("", "")
    try:
        client.my_trades("BTCUSDT", order_id="1" * 40)
    except MexcError as exc:
        assert "digits" in str(exc)
        assert "1" * 40 not in str(exc)
    else:
        raise AssertionError("a long trade id must not be requested")
    try:
        DecimalChange("9" * 90)
    except ValueError as exc:
        assert "9" * 90 not in str(exc)
    else:
        raise AssertionError("a long percent must not be parsed")
    row = {"symbol": "BTCUSDT", "quoteVolume": "10", "priceChangePercent": "1"}
    assert rank_liquid([row], 1, -10_000, 10_000, 40) == []
    assert client.liquid_usdt(1, -10, 10, 40) == []
    assert client.liquid_usdt(10**24, -10, 10, 8) == []
    assert rsi(None) is None
    assert rsi([10**24] * 20) is None
    assert rsi([100] * 20, 600) is None
    assert entry_signal("R" * 40, [100] * 30, 101) is None
    assert entry_signal("BTCUSDT", [100] * 30, 101) is None
    assert entry_signal("REPLAY", [100] * 30, 101) is None
    reclaim = [100] * 40 + [70, 99]
    assert entry_signal("BTCUSDT", reclaim, 101).reason == "rsi+reclaim"
    assert band_reclaim([100] * 40 + [80, 79]) is False
    assert entry_signal("BTCUSDT", [100] * 40 + [70, 70], 35) is None


def test_a_huge_file_does_not_replace_the_book(tmp_path) -> None:
    from spotbot.exits import exit_reason
    from spotbot.journal import note_event
    from spotbot.mexc import MexcClient, MexcError, _query, clock_allows
    from spotbot.ops_http import _public
    from spotbot.signals import _ema_last
    from spotbot.state import LedgerError, write_atomic

    try:
        write_atomic(tmp_path / "book.json", "x" * 1_000_001)
    except LedgerError as exc:
        assert "large" in str(exc)
    else:
        raise AssertionError("a file past one megabyte must not be written")
    assert not (tmp_path / "book.json").exists()
    note_event(tmp_path, kind="exit")
    assert (tmp_path / "ops_events.jsonl").exists()
    try:
        _query({str(i): "1" for i in range(17)})
    except MexcError as exc:
        assert "wide" in str(exc)
    else:
        raise AssertionError("a wide query must not be sent")
    try:
        MexcClient("", "").ohlcv("BTCUSDT", "5m", 1_001)
    except MexcError as exc:
        assert "large" in str(exc)
    else:
        raise AssertionError("more than 1000 candles must not be requested")
    assert clock_allows(1_000_000, 1_000_000, 10_001) is False
    assert clock_allows(1_000_000, 1_000_100) is True
    assert _public(10**24) == "unreadable"
    assert _public(1.5) == "unreadable"
    assert _public(True) is True
    assert _public(5) == 5
    assert _ema_last(None, 14) is None
    assert _ema_last([10**24] * 20, 14) is None
    assert _ema_last([100] * 20, 600) is None
    try:
        exit_reason(1_000, 1_000, 10**24, 350, 700, 300, 200)
    except ValueError:
        pass
    else:
        raise AssertionError("a ceiling peak must not be an exit")


def test_a_long_book_text_is_not_opened(tmp_path) -> None:
    import json

    from spotbot.__main__ import _env_too_big, _log_line
    from spotbot.rules import RuleError, parse_symbol_rule
    from spotbot.state import LedgerError, load_book

    def position(reason: str = "stop", entry: int = 1) -> dict[str, object]:
        return {
            "symbol": "BTCUSDT",
            "entry_micro": entry,
            "peak_micro": 1,
            "quote_micro": 1,
            "base_atoms": 1,
            "reason": reason,
        }

    path = tmp_path / "book.json"
    path.write_text(json.dumps({"cash_micro": 1, "positions": [position("r" * 81)]}), encoding="utf-8")
    try:
        load_book(path, 1)
    except LedgerError as exc:
        assert "long" in str(exc)
        assert "r" * 81 not in str(exc)
    else:
        raise AssertionError("a long reason must not open the book")
    path.write_text(json.dumps({"cash_micro": 1, "positions": [position(entry=10**18)]}), encoding="utf-8")
    try:
        load_book(path, 1)
    except LedgerError as exc:
        assert "large" in str(exc)
    else:
        raise AssertionError("a legacy price past the ceiling must not open")
    wide = {"cash_micro": 1, "positions": []}
    for i in range(64):
        wide[f"extra{i}"] = 1
    path.write_text(json.dumps(wide), encoding="utf-8")
    try:
        load_book(path, 1)
    except LedgerError as exc:
        assert "fields" in str(exc)
    else:
        raise AssertionError("a book with too many fields must not open")
    fat = position()
    for i in range(11):
        fat[f"extra{i}"] = 1
    path.write_text(json.dumps({"cash_micro": 1, "positions": [fat]}), encoding="utf-8")
    try:
        load_book(path, 1)
    except LedgerError as exc:
        assert "fields" in str(exc)
    else:
        raise AssertionError("a position with too many fields must not open")
    path.write_text(
        json.dumps({"cash_micro": 1, "positions": [], "pair_stops": {"S" * 40: [1]}}),
        encoding="utf-8",
    )
    try:
        load_book(path, 1)
    except LedgerError as exc:
        assert "S" * 40 not in str(exc)
    else:
        raise AssertionError("a long pair name must not open the book")
    try:
        parse_symbol_rule({"symbol": "BTCUSDT", "takerCommission": "9" * 10})
    except RuleError as exc:
        assert "range" in str(exc)
        assert "9" * 10 not in str(exc)
    else:
        raise AssertionError("a huge fee must not be copied into the error")
    assert len(_log_line(RuntimeError("z" * 400))) == 180
    env = tmp_path / ".env"
    assert _env_too_big(env) is False
    env.write_text("x" * 65_537, encoding="utf-8")
    assert _env_too_big(env) is True


def test_a_deep_file_is_not_a_book(tmp_path) -> None:
    import json

    from spotbot.engine import _unseen, open_loss_micro
    from spotbot.reconcile import FeeAssetError, split_commission, usdt_commission
    from spotbot.sleeves import SleeveError, _treasury
    from spotbot.state import Book, LedgerError, load_book

    nested: object = 1
    for _ in range(12):
        nested = [nested]
    path = tmp_path / "book.json"
    path.write_text(json.dumps(nested), encoding="utf-8")
    try:
        load_book(path, 1)
    except LedgerError as exc:
        assert "deep" in str(exc)
    else:
        raise AssertionError("a deep file must not open as a book")
    treasury = tmp_path / "treasury.json"
    treasury.write_text(json.dumps(nested), encoding="utf-8")
    try:
        _treasury(treasury)
    except SleeveError as exc:
        assert "deep" in str(exc)
    else:
        raise AssertionError("a deep file must not open as a treasury")
    row = {
        "orderId": "1",
        "id": "7",
        "symbol": "BTCUSDT",
        "isBuyer": True,
        "qty": "0.5",
        "quoteQty": "6",
        "price": "12",
        "commission": "0.01",
        "commissionAsset": "X" * 40,
    }
    try:
        split_commission([row], "1", "BTC", "BUY")
    except FeeAssetError as exc:
        assert "text" in str(exc)
        assert "X" * 40 not in str(exc)
    else:
        raise AssertionError("a long commission name must not be read")
    try:
        usdt_commission([{"orderId": "1", "commission": "0.01", "commissionAsset": "Y" * 40}], "1")
    except FeeAssetError as exc:
        assert "Y" * 40 not in str(exc)
    else:
        raise AssertionError("a long commission name must not be summed")
    try:
        usdt_commission([], "nope")
    except FeeAssetError as exc:
        assert "digits" in str(exc)
    else:
        raise AssertionError("a trade id that is not digits must not be a zero fee")
    book = Book(cash_micro=1, positions=[], realized_micro=0, seen_at=1_000)
    assert _unseen(book, 1_100, 90_000) is True
    assert open_loss_micro([object()] * 9, {}) == 2**62


def test_a_wide_book_does_not_ask_the_exchange() -> None:
    from pathlib import Path

    from spotbot.engine import _close_positions, _entries_halted, _exit_fees, _roll_guard, _short, _slots_used, trading_day
    from spotbot.mexc import MexcError, signed_payload
    from spotbot.rules import RuleError, parse_symbol_rule
    from spotbot.state import Book

    assert paper_buy(1_000_000, 1_000_000_000_000, -1) == (0, 0)
    assert paper_sell(100, 1_000_000_000_000, -1) == (0, 0)
    held = Position("BTCUSDT", 1, 1, 1, 1, "stop")
    wide = Book(cash_micro=1_000_000, positions=[held] * 9, realized_micro=0)
    assert _close_positions(None, None, wide, Path("book.json"), "", False)[2] == ("unknown",)
    assert _exit_fees(None, wide) is None
    assert _slots_used(None, wide) == 14
    ceiling = Book(cash_micro=10**24, positions=[], realized_micro=0, guard_day="")
    _roll_guard(ceiling)
    assert ceiling.guard_day == ""
    today = Book(cash_micro=1_000_000, positions=[], realized_micro=-1, guard_day=trading_day(), guard_realized_micro=10**24 - 1, guard_cash_micro=1_000_000)
    assert _entries_halted(today, 500) is True
    marked = Book(cash_micro=1_000_000, positions=[], realized_micro=0, guard_day=trading_day(), guard_cash_micro=10**24)
    assert _entries_halted(marked, 500) is True
    assert _entries_halted(Book(cash_micro=1_000_000, positions=[], realized_micro=0, guard_day=trading_day()), 10_001) is True
    row = {str(i): 1 for i in range(129)}
    try:
        parse_symbol_rule(row)
        raise AssertionError("wide row")
    except RuleError as exc:
        assert "wide" in str(exc)
    try:
        signed_payload(row, False)
        raise AssertionError("wide ack")
    except MexcError as exc:
        assert "wide" in str(exc)
    assert len(_short("e" * 400)) == 180


def test_a_wide_exchange_answer_is_not_a_price(tmp_path) -> None:
    from spotbot.journal import note_event
    from spotbot.liquidity import candle_lift
    from spotbot.mexc import MexcClient, MexcError, book_prices, depth_notionals, parse_account, ticker_price
    from spotbot.rules import RuleError, parse_symbol_rule

    wide = {str(i): "1" for i in range(17)}
    wide["symbol"] = "BTCUSDT"
    wide["price"] = "1"
    try:
        ticker_price(wide, "BTCUSDT")
        raise AssertionError("wide price")
    except MexcError as exc:
        assert "price" in str(exc)
        assert "0" not in str(exc) or "BTCUSDT" in str(exc)
    try:
        book_prices(wide, "BTCUSDT")
        raise AssertionError("wide book")
    except MexcError as exc:
        assert "wide" in str(exc)
    try:
        depth_notionals(wide, "BTCUSDT")
        raise AssertionError("wide depth")
    except MexcError as exc:
        assert "wide" in str(exc)
    account = {"balances": [{"asset": "USDT", "free": "1", "locked": "0", **{str(i): "1" for i in range(14)}}]}
    try:
        parse_account(account)
        raise AssertionError("wide balance")
    except MexcError as exc:
        assert "wide" in str(exc)
        assert "USDT" not in str(exc)
    fat = {"balances": [], **{str(i): 1 for i in range(32)}}
    try:
        parse_account(fat)
        raise AssertionError("wide account")
    except MexcError as exc:
        assert "wide" in str(exc)
    client = MexcClient("", "")
    client._public = lambda *_args, **_kwargs: {str(i): 1 for i in range(9)}
    try:
        client.server_time_ms()
        raise AssertionError("wide time")
    except MexcError as exc:
        assert "object" in str(exc)
    client._public = lambda *_args, **_kwargs: {"serverTime": 10**15}
    try:
        client.server_time_ms()
        raise AssertionError("far time")
    except MexcError as exc:
        assert "timestamp" in str(exc)
        assert "15" not in str(exc) or len(str(exc)) < 80
    client._public = lambda *_args, **_kwargs: {str(i): 1 for i in range(17)}
    try:
        client.symbol_rule("BTCUSDT")
        raise AssertionError("wide info")
    except MexcError as exc:
        assert "wide" in str(exc)
    try:
        parse_symbol_rule({"symbol": "BTCUSDT", "filters": [1] * 65})
        raise AssertionError("long list")
    except RuleError as exc:
        assert "list" in str(exc)
    note_event(tmp_path, **{f"k{i}": 1 for i in range(33)})
    assert not (tmp_path / "ops_events.jsonl").exists()
    volumes = [1] * 12 + [10**18, 1]
    assert volume_ratio_bps(volumes) is None
    assert candle_lift("R" * 40, [100] * 12 + [400, 100], 2, 1, 2) is None
    assert candle_lift("REPLAY", [100] * 12 + [400, 100], 2, 1, 2) is not None


def test_a_wide_ticker_row_is_not_a_peer(tmp_path) -> None:
    import json

    from spotbot.guards import drawdown_blocks, note_pair_stop, pair_locked
    from spotbot.journal import note_event, note_quote
    from spotbot.liquidity import close_position_bps
    from spotbot.mexc import rank_liquid
    from spotbot.oracle import _binance_price, _bybit_price, _okx_price, cheapest_first, deviation_bps, lag_bps
    from spotbot.reconcile import FeeAssetError, split_commission
    from spotbot.state import Book

    wide = {"symbol": "ETHUSDT", "quoteVolume": "999999", "priceChangePercent": "1"}
    wide.update({str(i): "1" for i in range(62)})
    names = rank_liquid(
        [wide, {"symbol": "BTCUSDT", "quoteVolume": "10", "priceChangePercent": "1"}],
        1,
        -10_000,
        10_000,
        5,
    )
    assert names == ["BTCUSDT"]
    try:
        split_commission([{str(i): "1" for i in range(33)}], "1", "BTC", "BUY")
        raise AssertionError("wide trade")
    except FeeAssetError as exc:
        assert "wide" in str(exc)
    assert close_position_bps(2, 1, 10**20) is None
    assert close_position_bps(2, 1, 2) == 10_000
    assert deviation_bps(None) is None
    assert deviation_bps([1, 10**20]) is None
    assert lag_bps(10**20, [1]) is None
    assert lag_bps(100, None) is None
    assert cheapest_first(None) == []
    assert cheapest_first([("A" * 40, 1), ("ETHUSDT", 2), ("BTCUSDT", 10**12)]) == ["ETHUSDT"]
    assert _binance_price({"symbol": "BTCUSDT", "price": "1"}, "BTCUSDT") == "1"
    assert _binance_price({**{str(i): "1" for i in range(16)}, "symbol": "BTCUSDT", "price": "1"}, "BTCUSDT") is None
    assert _bybit_price({"result": {"list": [{"symbol": "BTCUSDT", "lastPrice": "1"}]}}, "BTCUSDT") == "1"
    fat_row = {"symbol": "BTCUSDT", "lastPrice": "1", **{str(i): "1" for i in range(63)}}
    assert _bybit_price({"result": {"list": [fat_row]}}, "BTCUSDT") is None
    assert _okx_price({"data": [{"instId": "BTC-USDT", "last": "1"}]}, "BTC-USDT") == "1"
    assert _okx_price({**{str(i): 1 for i in range(16)}, "data": [{"instId": "BTC-USDT", "last": "1"}]}, "BTC-USDT") is None
    nested: list[object] = []
    cursor = nested
    for _ in range(12):
        nxt: list[object] = []
        cursor.append(nxt)
        cursor = nxt
    (tmp_path / "ops_quotes.json").write_text(json.dumps({"BTCUSDT": nested, "S" * 40: 1}), encoding="utf-8")
    note_quote(tmp_path, "ETHUSDT", "1", "1", "1", "1", 1, 1)
    kept = json.loads((tmp_path / "ops_quotes.json").read_text(encoding="utf-8"))
    assert list(kept) == ["ETHUSDT"]
    (tmp_path / "ops_events.jsonl").write_text(("x" * 5_000) + "\n", encoding="utf-8")
    note_event(tmp_path, kind="ok")
    stored = (tmp_path / "ops_events.jsonl").read_text(encoding="utf-8")
    assert "x" * 5_000 not in stored
    assert "ok" in stored
    assert drawdown_blocks(1_000_000, 900_000, 10_001) is True
    book = Book(cash_micro=1, positions=[], realized_micro=0)
    note_pair_stop(book, "BTCUSDT", 10**15, 2, 60)
    assert not book.pair_stops
    book.pair_lock_until = {"BTCUSDT": 10**15}
    assert pair_locked(book, "BTCUSDT", 1_700_000_000) is True


def test_a_long_command_does_not_start(tmp_path) -> None:
    from pathlib import Path

    from spotbot.__main__ import main
    from spotbot.engine import _sibling_positions, sibling_pending
    from spotbot.reconcile import FeeAssetError, usdt_commission
    from spotbot.rules import RuleError, parse_symbol_rule
    from spotbot.state import LedgerError

    assert sibling_pending((Path(("N" * 40) + ".json"),)) == "sibling book name is too long"
    try:
        _sibling_positions((Path(("N" * 40) + ".json"),))
        raise AssertionError("stem")
    except LedgerError as exc:
        assert "long" in str(exc)
        assert "N" * 40 not in str(exc)
    assert main(["--flag"] * 17) == 2
    assert main(["--" + "a" * 31]) == 2
    try:
        usdt_commission([{str(i): "1" for i in range(33)}], "1")
        raise AssertionError("wide fee")
    except FeeAssetError as exc:
        assert "wide" in str(exc)
    try:
        parse_symbol_rule({"symbol": "BTCUSDT", "filters": [{str(i): 1 for i in range(33)}]})
        raise AssertionError("wide filter")
    except RuleError as exc:
        assert "wide" in str(exc)
        assert "0" not in str(exc) or "wide" in str(exc)
    deep: object = "x"
    for _ in range(8):
        deep = [deep]
    try:
        parse_symbol_rule({"symbol": "BTCUSDT", "filters": deep})
        raise AssertionError("deep filter")
    except RuleError as exc:
        assert "wide" in str(exc)


def test_a_wide_treasury_is_not_a_split(tmp_path) -> None:
    import json
    from datetime import datetime, timezone
    from pathlib import Path

    from spotbot.engine import _shown_name
    from spotbot.mexc import MexcClient, MexcError, _interval_ms
    from spotbot.ops_http import _events, _heartbeat
    from spotbot.sleeves import SleeveError, _open_split, _treasury

    assert _shown_name("A" * 40, Path("book.json")) == "book"
    assert _shown_name("sleeve_major", Path(("B" * 40) + ".json")) == "sleeve_major"
    assert _shown_name("", Path(("B" * 40) + ".json")) == "book"
    try:
        _interval_ms("m" * 20)
        raise AssertionError("interval")
    except MexcError as exc:
        assert "interval" in str(exc)
        assert "m" * 20 not in str(exc)
    client = MexcClient("k", "s")
    client._signed = lambda *_args, **_kwargs: [{str(i): 1 for i in range(33)}]
    try:
        client.my_trades("BTCUSDT")
        raise AssertionError("wide trade")
    except MexcError as exc:
        assert "wide" in str(exc)
    client._signed = lambda *_args, **_kwargs: ["nope"]
    try:
        client.my_trades("BTCUSDT")
        raise AssertionError("trade object")
    except MexcError as exc:
        assert "object" in str(exc)
    fat = {"funded_micro": 0, "sleeves": ["major", "alt", "meme"]}
    fat.update({str(i): 1 for i in range(7)})
    (tmp_path / "treasury.json").write_text(json.dumps(fat), encoding="utf-8")
    try:
        _treasury(tmp_path / "treasury.json")
        raise AssertionError("wide treasury")
    except SleeveError as exc:
        assert "fields" in str(exc)
    pending = {
        "funded_micro": 0,
        "sleeves": ["major", "alt", "meme"],
        "pending": {"target_micro": 3, "parts": [1, 1, 1], "a": 1, "b": 1, "c": 1},
    }
    try:
        _open_split(pending, 0)
        raise AssertionError("wide split")
    except SleeveError as exc:
        assert "wide" in str(exc)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    beat = {"at": stamp, "book": "paper"}
    beat.update({str(i): 1 for i in range(7)})
    (tmp_path / "ops_heartbeat.json").write_text(json.dumps(beat), encoding="utf-8")
    assert _heartbeat(tmp_path) is None
    long_line = json.dumps({"kind": "k" * 5_000})
    (tmp_path / "ops_events.jsonl").write_text(long_line + "\n" + json.dumps({"kind": "ok"}) + "\n", encoding="utf-8")
    rows = _events(tmp_path)
    assert [row.get("kind") for row in rows] == ["ok"]


def test_a_huge_log_does_not_start(tmp_path) -> None:
    from spotbot.__main__ import _log_refused
    from spotbot.engine import _log_oracle
    from spotbot.money import decimal_text, to_satoshi
    from spotbot.ops_http import OpsError, _status_bytes, snapshot
    from spotbot.signals import entry_signal, macd_cross

    weird = type("Q" * 40, (), {})()
    try:
        decimal_text(weird)
        raise AssertionError("kind")
    except MoneyError as exc:
        assert "Q" * 40 not in str(exc)
    try:
        to_satoshi("12.3.4")
        raise AssertionError("decimal")
    except MoneyError as exc:
        assert "12.3.4" not in str(exc)
    assert entry_signal("BTCUSDT", [100] * 30, 101) is None
    assert entry_signal("REPLAY", [100] * 30, 101) is None
    reclaim = [100] * 40 + [70, 99]
    assert entry_signal("BTCUSDT", reclaim, 101).reason == "rsi+reclaim"
    assert entry_signal("BTCUSDT", [100] * 40 + [70, 70], 35) is None
    assert entry_signal("BTCUSDT", [100] * 30, 501) is None
    assert macd_cross([100] * 40, 20, 10, 9) is None
    _log_oracle("A" * 40, 100, {"binance": 100}, tmp_path)
    _log_oracle("BTCUSDT", 100, {str(i): 100 for i in range(9)}, tmp_path)
    assert not (tmp_path / "ops_quotes.json").exists()
    folder = tmp_path / "ops.log"
    folder.mkdir()
    assert _log_refused(folder) is True
    small = tmp_path / "small.log"
    small.write_bytes(b"x" * 11)
    assert _log_refused(small) is False
    assert _log_refused(small, 10) is True
    planted = tmp_path / "notdir"
    planted.write_text("x", encoding="utf-8")
    assert snapshot(planted)["books"] == {"error": "data dir is not a directory"}
    try:
        _status_bytes(tmp_path, 19280, 10)
        raise AssertionError("status size")
    except OpsError as exc:
        assert "unreadable" in str(exc)


def test_a_long_day_is_not_a_guard(tmp_path) -> None:
    from spotbot.mexc import MexcError, ack_commission, executed_fill, signed_payload, _require_filled
    from spotbot.money import format_fixed
    from spotbot.state import LedgerError, _guard_day_ok

    try:
        _guard_day_ok("1" * 40)
        raise AssertionError("day")
    except LedgerError as exc:
        assert "date" in str(exc)
        assert "111" not in str(exc)
    try:
        format_fixed(1, 10**19)
        raise AssertionError("scale")
    except MoneyError as exc:
        assert "wire" in str(exc)
    try:
        signed_payload({"orderId": "1", "fills": list(range(129))}, False)
        raise AssertionError("fills")
    except MexcError as exc:
        assert "fills" in str(exc)
    assert signed_payload([{"id": "1"}], True) == [{"id": "1"}]
    try:
        signed_payload([{str(i): "1" for i in range(33)}], True)
        raise AssertionError("wide trade")
    except MexcError as exc:
        assert "wide" in str(exc)
    try:
        signed_payload(["nope"], True)
        raise AssertionError("trade object")
    except MexcError as exc:
        assert "object" in str(exc)
    try:
        executed_fill("nope")
        raise AssertionError("fill")
    except MexcError as exc:
        assert "object" in str(exc)
    try:
        _require_filled("nope", "buy")
        raise AssertionError("status")
    except MexcError as exc:
        assert "filled" in str(exc)
    try:
        ack_commission("nope", "BTC")
        raise AssertionError("ack")
    except MexcError as exc:
        assert "object" in str(exc)


def test_a_wide_stop_count_still_locks() -> None:
    from spotbot.engine import _status_text
    from spotbot.guards import marked_equity, note_pair_stop, pair_locked
    from spotbot.mexc import backoff_sec
    from spotbot.oracle import _shown_http
    from spotbot.state import Book

    book = Book(cash_micro=1, positions=[], realized_micro=0)
    for step in range(8):
        note_pair_stop(book, "BTCUSDT", 1_700_000_000 + step, 100, 60)
    assert pair_locked(book, "BTCUSDT", 1_700_000_008) is True
    broken = Book(cash_micro=1, positions=[], realized_micro=0, pair_stops={"BTCUSDT": 1})
    note_pair_stop(broken, "BTCUSDT", 1_700_000_000, 2, 60)
    assert broken.pair_stops["BTCUSDT"] == [1_700_000_000]
    assert marked_equity(1, [object()] * 9, {}) is None
    assert marked_equity(1, [], {str(i): 1 for i in range(15)}) is None
    assert backoff_sec(None, 10**9) == 86_400
    assert _shown_http(10**20) == "refused"
    assert _shown_http(404) == "404"
    assert _status_text({"status": "S" * 40}) == ""
    assert _status_text({"status": 2}) == "2"


def test_a_directory_is_not_a_book(tmp_path) -> None:
    from spotbot.engine import _apply_progress, _over_request
    from spotbot.ops_http import _show_book
    from spotbot.state import Book, LedgerError, load_book, remember_pending, write_atomic

    folder = tmp_path / "book.json"
    folder.mkdir()
    try:
        load_book(folder, 1)
        raise AssertionError("dir book")
    except LedgerError as exc:
        assert "file" in str(exc)
    try:
        write_atomic(folder, "x")
        raise AssertionError("dir write")
    except LedgerError as exc:
        assert "file" in str(exc)
    buy = Book(cash_micro=1, positions=[], realized_micro=0)
    remember_pending(buy, "abc", "BTCUSDT", "BUY", 0, 0)
    assert _over_request(buy, 1, 1) == "pending buy has no requested quote"
    sell = Book(cash_micro=1, positions=[], realized_micro=0)
    sell.pending_side = "SELL"
    sell.pending_base_atoms = 0
    assert _over_request(sell, 1, 1) == "pending sell has no requested base"
    buy.pending_quote_micro = 100
    assert _over_request(buy, 1, 10**24) == "fill is too large"
    wide = {
        "cash_micro": 1,
        "price_scale": 1_000_000_000_000,
        "positions": [{"entry_micro": 1_000_000_000_000, "peak_micro": 1_000_000_000_000, **{str(i): 1 for i in range(15)}}],
    }
    shown = _show_book(wide)
    assert shown["positions"] == ["unreadable"]
    assert _apply_progress(None, buy, "nope", 1, 1, 1) is False


def test_a_file_is_not_a_ledger_directory(tmp_path, caplog) -> None:
    import logging

    from spotbot.__main__ import _pause_sec
    from spotbot.analyzer import _native_file
    from spotbot.engine import _order_fees
    from spotbot.state import LedgerError, hold_ledger

    planted = tmp_path / "paper"
    planted.write_text("x", encoding="utf-8")
    try:
        with hold_ledger(planted):
            raise AssertionError("held")
    except LedgerError as exc:
        assert "directory" in str(exc)
    assert _pause_sec(60) == 60
    assert _pause_sec(10**9) == 86_400
    assert _pause_sec(True) == 86_400
    folder = tmp_path / "dll"
    folder.mkdir()
    assert _native_file(folder) is False
    small = tmp_path / "spotbot_native.dll"
    small.write_bytes(b"x" * 11)
    assert _native_file(small, 10) is False
    assert _native_file(small) is True
    with caplog.at_level(logging.WARNING):
        assert _order_fees(None, "Z" * 80, "1", "BUY") is None
    assert "Z" * 80 not in caplog.text


def test_macd_cross_still_counts_below_zero() -> None:
    from spotbot.signals import _ema_last, _ema_signed, macd_cross

    down = [2000] * 40 + [2000 - i * 30 for i in range(1, 30)]
    series = down + [down[-1] + i * 40 for i in range(1, 50)]
    assert macd_cross(series[:72]) == "buy"
    assert _ema_last([100, -1, 100], 2) is None
    assert _ema_signed([-5, -4, -3], 2) is not None


def test_a_pair_without_a_lot_does_not_stop_the_median(monkeypatch, capsys) -> None:
    from spotbot.replay_main import main
    from spotbot.rules import SymbolRule

    class _Client:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def symbol_rule(self, symbol: str) -> SymbolRule:
            if symbol == "PEPEUSDT":
                return SymbolRule(symbol, False, "base step is missing", 5, 0, 1, 0, "PEPE", 1)
            return SymbolRule(symbol, True, "", 5, 1, 1, 0, "COIN", 1)

        def ohlcv(self, symbol: str, interval: str, limit: int) -> list[tuple[int, int, int, int, int]]:
            return [(1, 1, 1, 1_000_000_000_000, 1_000_000)] * limit

    monkeypatch.setattr("spotbot.replay_main.MexcClient", _Client)
    monkeypatch.setattr("spotbot.replay_main.time.sleep", lambda _sec: None)
    assert main(["--sleeves", "--limit", "160"]) == 0
    assert "PEPEUSDT" in capsys.readouterr().out
    assert main(["--symbol", "PEPEUSDT", "--limit", "160"]) == 1


def test_the_env_cannot_turn_entries_on(monkeypatch) -> None:
    from spotbot.config import load_config

    monkeypatch.setenv("SPOT_SYMBOLS", "BTCUSDT")
    monkeypatch.setenv("SPOT_INTERVAL_SEC", "60")
    monkeypatch.setenv("SPOT_LIVE", "0")
    monkeypatch.setenv("SPOT_MODE", "rsi")
    monkeypatch.setenv("SPOT_TAKER_BPS", "5")
    monkeypatch.setenv("SPOT_DAILY_LOSS_BPS", "500")
    monkeypatch.setenv("SPOT_STOP_COOLDOWN_SEC", "900")
    monkeypatch.setenv("SPOT_PAPER_CASH_USDT", "1000")
    monkeypatch.setenv("SPOT_MIN_USDT", "3")
    monkeypatch.setenv("SPOT_ALLOC_BPS", "2000")
    monkeypatch.setenv("SPOT_RSI_BUY", "35")
    monkeypatch.setenv("SPOT_MAX_POSITIONS", "1")
    monkeypatch.setenv("SPOT_ENTRIES", "1")
    assert load_config(False).entries is False
    monkeypatch.setenv("SPOT_ENTRIES", "0")
    assert load_config(False).entries is False


def test_lift_needs_volume_and_bids() -> None:
    volumes = [100] * 12 + [400, 100]
    assert volume_ratio_bps(volumes) == 40_000
    assert lift_signal("ABCUSDT", volumes, 110, 100, 108, 2_000, 1_000) is not None
    assert lift_signal("ABCUSDT", volumes, 110, 100, 101, 2_000, 1_000) is None
    assert lift_signal("ABCUSDT", volumes, 110, 100, 108, 1_000, 2_000) is None
    assert ask_wall_exit(1_000, 2_000, 40) is True
    assert ask_wall_exit(1_000, 2_000, 10) is False


def test_oracle_width_and_analyzer_refuse() -> None:
    assert deviation_bps([100_000_000]) is None
    assert deviation_bps([100_000_000, 100_000_000, 100_200_000]) == 20
    assert deviation_bps([100_000_000, 101_000_000]) == 100
    assert _score_python(40_000, 8_000, 2, 30, 2_000, 1_000) == 10_000
    assert _score_python(40_000, 8_000, 80, 30, 2_000, 1_000) == 0
    assert _score_python(40_000, 8_000, 2, 30, 1_000, 2_000) == 0


def test_flat_round_trip_loses_the_taker_fee() -> None:
    price = 100_000_000
    spend = 200_000_000
    base, buy_fee = paper_buy(spend, price, 5)
    credit, sell_fee = paper_sell(base, price, 5)
    assert buy_fee == 100_000
    assert sell_fee > 0
    assert credit - spend < 0


def test_an_ask_back_under_the_band_is_not_bought(tmp_path) -> None:
    from spotbot.config import Config
    from spotbot.engine import _open_positions
    from spotbot.signals import reclaim_still
    from spotbot.state import Book

    closes = [100] * 40 + [90, 100]
    assert reclaim_still(closes, 100) is True
    assert reclaim_still(closes, 90) is False

    class _Back:
        def klines(self, _symbol: str) -> list[int]:
            return closes + [100]

        def book_top(self, _symbol: str) -> tuple[int, int]:
            return 90, 90

    cfg = Config(
        symbols=("BTCUSDT",),
        paper_cash_micro=20_000_000,
        interval_sec=60,
        max_positions=1,
        alloc_bps=10_000,
        min_notional_micro=1_000_000,
        rsi_buy=35,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        live=False,
        mode="rsi",
        taker_bps=5,
        daily_loss_bps=500,
        stop_cooldown_sec=900,
        symbol_lock=True,
        api_key="",
        api_secret="",
        entries=True,
    )
    book = Book(cash_micro=20_000_000, positions=[], realized_micro=0)
    opened, skipped = _open_positions(cfg, _Back(), book, tmp_path / "back.json", "book", 10**12)
    assert opened == 0 and skipped == 1 and book.positions == []


def test_rsi_entry_refuses_a_heavier_ask_at_the_touch(tmp_path) -> None:
    from spotbot.config import Config
    from spotbot.engine import _open_positions
    from spotbot.state import Book

    closes = [100] * 40 + [90, 100, 100]

    class _Book:
        def klines(self, _symbol: str) -> list[int]:
            return closes

        def book_top(self, _symbol: str) -> tuple[int, int]:
            return 100, 100

        def depth_notional(self, _symbol: str) -> tuple[int, int]:
            return 1, 2

    cfg = Config(
        symbols=("BTCUSDT",),
        paper_cash_micro=20_000_000,
        interval_sec=60,
        max_positions=1,
        alloc_bps=10_000,
        min_notional_micro=1_000_000,
        rsi_buy=35,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        live=False,
        mode="rsi",
        taker_bps=5,
        daily_loss_bps=500,
        stop_cooldown_sec=900,
        symbol_lock=True,
        api_key="",
        api_secret="",
        entries=True,
    )
    book = Book(cash_micro=20_000_000, positions=[], realized_micro=0)
    opened, skipped = _open_positions(cfg, _Book(), book, tmp_path / "touch.json", "book", 10**12)
    assert opened == 0 and skipped == 1 and book.positions == []


def test_a_far_book_level_is_not_the_next_trade() -> None:
    from spotbot.mexc import depth_notionals

    near = depth_notionals(
        {"bids": [["100", "1"]], "asks": [["100.01", "1"]], "lastUpdateId": 1},
        "BTCUSDT",
    )
    both = depth_notionals(
        {"bids": [["100", "1"], ["90", "5"]], "asks": [["100.01", "1"], ["110", "5"]], "lastUpdateId": 1},
        "BTCUSDT",
    )
    assert both == near


def test_a_jumped_close_stays_in_the_tape_and_stops() -> None:
    from spotbot.replay import replay_closes

    closes = [100_000_000] * 40 + [90_000_000, 98_000_000, 80_000_000]
    opens = [100_000_000] * 40 + [90_000_000, 98_000_000, 97_000_000]
    result = replay_closes(
        closes,
        cash_micro=1_000_000_000,
        alloc_bps=10_000,
        taker_bps=5,
        rsi_buy=35,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=10_000,
        trail_gap_bps=10_000,
        min_notional_micro=1,
        opens=opens,
    )
    assert result.trades == 1
    assert result.fills[0].exit_micro * 10_000 < result.fills[0].entry_micro * 9_000


def test_replay_stop_is_negative_after_fees() -> None:
    # Flat stretch, one close under the band, a reclaim, then a drop through the stop.
    closes = [100_000_000] * 40
    closes += [90_000_000, 98_000_000, 97_000_000]
    closes += [93_000_000] * 6
    result = replay_closes(
        closes,
        cash_micro=1_000_000_000,
        alloc_bps=10_000,
        taker_bps=5,
        rsi_buy=100,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=10_000,
        trail_gap_bps=10_000,
        min_notional_micro=1,
    )
    assert result.trades >= 1
    assert result.net_micro < 0
    untouched = replay_closes(
        closes,
        cash_micro=1_000_000_000,
        alloc_bps=10_000,
        taker_bps=5,
        rsi_buy=100,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=10_000,
        trail_gap_bps=10_000,
        min_notional_micro=1,
        entry_from=len(closes),
    )
    assert untouched.trades == 0
    assert untouched.net_micro == 0
    held = replay_closes(
        closes,
        cash_micro=1_000_000_000,
        alloc_bps=10_000,
        taker_bps=5,
        rsi_buy=100,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=10_000,
        trail_gap_bps=10_000,
        min_notional_micro=1,
        cooldown_bars=10**6,
        lookback_bars=10**6,
        lock_bars=10**6,
        lock_count=2,
    )
    assert held.trades >= 1
    assert held.trades <= result.trades
    assert held.net_micro < 0
    from spotbot.replay import _fill_price

    assert _fill_price([10, 20], [10, 99], 0) == 20
    assert _fill_price(None, [10, 99], 0) == 99
    from spotbot.mexc import MexcError, _join_klines

    assert len(_join_klines([[1, "a"]], [[2, "b"]], "BTCUSDT")) == 2
    try:
        _join_klines([[2, "a"]], [[2, "b"]], "BTCUSDT")
    except MexcError as exc:
        assert "short" in str(exc)
    else:
        raise AssertionError("a page that does not move earlier must not extend the tape")


def test_split_keeps_every_satoshi() -> None:
    parts = split_equal(100_000_000, 3)
    assert sum(parts) == 100_000_000
    assert parts[0] == 33_333_334
    assert parts[1] == parts[2] == 33_333_333


def test_new_deposit_does_not_reset_sleeve_profit(tmp_path) -> None:
    apply_funding(tmp_path, 100_000_000)
    books = ledger_dir(tmp_path, False)
    path = books / "sleeve_major.json"
    book = load_book(path, 0)
    before = book.cash_micro
    book.cash_micro += 2_000_000
    save_book(path, book)
    apply_funding(tmp_path, 100_000_000)
    assert load_book(path, 0).cash_micro == before + 2_000_000
    apply_funding(tmp_path, 130_000_000)
    assert load_book(path, 0).cash_micro == before + 2_000_000 + 10_000_000
    alt = load_book(books / "sleeve_alt.json", 0).cash_micro
    meme = load_book(books / "sleeve_meme.json", 0).cash_micro
    assert alt == 33_333_333 + 10_000_000
    assert meme == alt
    try:
        apply_funding(tmp_path, 90_000_000)
    except SleeveError:
        pass
    else:
        raise AssertionError("shrinking the main balance must be refused")
    held = load_book(path, 0).cash_micro
    (books / "treasury.json").write_text('{"funded_micro": 0}\n', encoding="utf-8")
    apply_funding(tmp_path, 130_000_000)
    assert load_book(path, 0).cash_micro == held
    assert load_book(books / "sleeve_alt.json", 0).cash_micro == alt


def test_failed_book_replace_keeps_the_previous_file(tmp_path, monkeypatch) -> None:
    from spotbot.state import Book

    path = tmp_path / "book.json"
    save_book(
        path,
        Book(
            cash_micro=5,
            positions=[],
            realized_micro=0,
            pending_client_id="keep",
            pending_symbol="BTCUSDT",
            pending_side="BUY",
            pending_quote_micro=1_000_000,
        ),
    )

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk")

    monkeypatch.setattr("spotbot.state.os.replace", boom)
    try:
        save_book(
            path,
            Book(
                cash_micro=9,
                positions=[],
                realized_micro=0,
                pending_client_id="lost",
                pending_symbol="ETHUSDT",
                pending_side="BUY",
                pending_quote_micro=1_000_000,
            ),
        )
    except OSError:
        pass
    else:
        raise AssertionError("a failed replace must not report success")
    loaded = load_book(path, 0)
    assert loaded.pending_client_id == "keep"
    assert loaded.pending_symbol == "BTCUSDT"
    assert loaded.cash_micro == 5


def test_corrupt_book_does_not_open(tmp_path) -> None:
    from spotbot.state import Book, LedgerError, Position, remember_pending

    path = tmp_path / "book.json"
    save_book(path, Book(cash_micro=5, positions=[], realized_micro=-1, fees_micro=0))
    assert load_book(path, 0).realized_micro == -1
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["cash_micro"] = -1
    path.write_text(json.dumps(raw), encoding="utf-8")
    try:
        load_book(path, 0)
    except LedgerError:
        pass
    else:
        raise AssertionError("negative cash must not open")
    doubled = Book(
        cash_micro=1,
        positions=[
            Position("BTCUSDT", 1, 1, 1, 1, "a", "c1", "e1"),
            Position("BTCUSDT", 1, 1, 1, 1, "b", "c2", "e2"),
        ],
        realized_micro=0,
    )
    path.write_text(json.dumps(doubled.to_json()), encoding="utf-8")
    try:
        load_book(path, 0)
    except LedgerError:
        pass
    else:
        raise AssertionError("two rows of one pair must not open")
    missing = Book(cash_micro=5, positions=[], realized_micro=0)
    remember_pending(missing, "abc", "BTCUSDT", "BUY", 0, 1)
    missing.pending_applied_atoms = 1
    path.write_text(json.dumps(missing.to_json()), encoding="utf-8")
    try:
        load_book(path, 0)
    except LedgerError:
        pass
    else:
        raise AssertionError("a buy fill without the coins must not open")
    short = Book(
        cash_micro=5_000_000,
        positions=[Position("BTCUSDT", 1, 1, 5_000_000, 1, "x", "abc", "1")],
        realized_micro=0,
    )
    remember_pending(short, "abc", "BTCUSDT", "BUY", 0, 5_000_000)
    short.pending_applied_atoms = 50_000_000
    short.pending_applied_quote = 5_000_000
    path.write_text(json.dumps(short.to_json()), encoding="utf-8")
    try:
        load_book(path, 0)
    except LedgerError:
        pass
    else:
        raise AssertionError("a buy row with the wrong coin count must not open")
    cheap = Book(
        cash_micro=5_000_000,
        positions=[Position("BTCUSDT", 1, 1, 4_999_999, 50_000_000, "x", "abc", "1")],
        realized_micro=0,
    )
    remember_pending(cheap, "abc", "BTCUSDT", "BUY", 0, 5_000_000)
    cheap.pending_applied_atoms = 50_000_000
    cheap.pending_applied_quote = 5_000_000
    path.write_text(json.dumps(cheap.to_json()), encoding="utf-8")
    try:
        load_book(path, 0)
    except LedgerError:
        pass
    else:
        raise AssertionError("a buy row with the wrong cost must not open")


def test_live_ledger_does_not_spend_paper_cash(tmp_path) -> None:
    from spotbot.state import LedgerError, bind_ledger

    apply_funding(tmp_path, 100_000_000, live=False)
    apply_funding(tmp_path, 50_000_000, live=True)
    paper = load_book(ledger_dir(tmp_path, False) / "sleeve_major.json", 0)
    live = load_book(ledger_dir(tmp_path, True) / "sleeve_major.json", 0)
    assert paper.cash_micro == 33_333_334
    assert live.cash_micro == 16_666_668
    paper.positions.append(
        Position(
            symbol="BTCUSDT",
            entry_micro=1,
            peak_micro=1,
            quote_micro=1,
            base_atoms=1,
            reason="test",
        )
    )
    try:
        bind_ledger(paper, True)
    except LedgerError:
        pass
    else:
        raise AssertionError("a paper coin must not become a live order")


def test_jump_is_not_a_price() -> None:
    assert price_ok(100_000_000, 110_000_000) is True
    assert price_ok(100_000_000, 10_000_000_000) is False


def test_clock_skew_pauses_live_orders() -> None:
    from spotbot.mexc import clock_allows

    assert clock_allows(1_000_000, 1_001_000) is True
    assert clock_allows(1_000_000, 1_003_001) is False
    assert clock_allows(1_000_000, 0) is False


def test_cheapest_mexc_is_bought_first() -> None:
    from spotbot.oracle import cheapest_first

    assert cheapest_first([("BTCUSDT", 10), ("ETHUSDT", -4), ("SOLUSDT", -4)]) == [
        "ETHUSDT",
        "SOLUSDT",
        "BTCUSDT",
    ]


def test_mexc_lag_blocks_a_rich_buy_and_arms_a_rich_sell() -> None:
    peers = [100_000_000, 100_000_000]
    assert lag_bps(100_000_000, peers) == 0
    assert lag_bps(100_200_000, peers) == 20
    assert lag_bps(99_800_000, peers) == -20
    assert entry_allowed(100_000_000, peers) is True
    assert entry_allowed(100_200_000, peers) is False
    assert entry_allowed(100_000_000, []) is False
    assert ahead_exit(100_200_000, peers, 40) is True
    assert ahead_exit(100_200_000, peers, 10) is False


def test_symbol_fee_and_lot_come_from_the_pair() -> None:
    from spotbot.rules import parse_symbol_rule, plan_paper_buy, round_base_atoms, round_quote_micro, uses_slot

    floki = parse_symbol_rule(
        {
            "symbol": "FLOKIUSDT",
            "status": "1",
            "isSpotTradingAllowed": True,
            "quoteAsset": "USDT",
            "st": False,
            "conceptPlates": ["Innovation", "MEME"],
            "takerCommission": "0.0008",
            "baseSizePrecision": "1",
            "quoteAmountPrecisionMarket": "1",
            "maxQuoteAmountMarket": "200000",
                "baseAsset": "FLOKI",
                "quotePrecision": "8",
                "orderTypes": ["LIMIT", "MARKET", "LIMIT_MAKER"],
            "tradeSideType": "1",
        }
    )
    assert floki.tradable is True
    assert floki.price_tick == 10_000
    assert floki.taker_bps == 8
    assert floki.base_step_atoms == 100_000_000
    assert floki.quote_step_micro == 1_000_000
    assert round_quote_micro(33_333_333, floki.quote_step_micro) == 33_000_000
    assert round_base_atoms(150_000_000, 100_000_000) == 100_000_000
    assert round_base_atoms(50_000_000, 100_000_000) == 0
    assert uses_slot(50_000_000, 100_000_000) is False
    assert uses_slot(100_000_000, 100_000_000) is True
    assert round_quote_micro(17, 5) == 15
    blocked = parse_symbol_rule(
        {
            "symbol": "XXUSDT",
            "status": "1",
            "isSpotTradingAllowed": True,
            "quoteAsset": "USDT",
            "st": False,
            "conceptPlates": ["Assessment"],
            "takerCommission": "0.0005",
            "baseSizePrecision": "1",
            "quoteAmountPrecisionMarket": "1",
            "baseAsset": "XX",
            "orderTypes": ["MARKET"],
        }
    )
    assert blocked.tradable is False
    tagged = dict(blocked.__dict__) if False else {
        "symbol": "YYUSDT",
        "status": "1",
        "isSpotTradingAllowed": True,
        "quoteAsset": "USDT",
        "st": True,
        "conceptPlates": [],
        "takerCommission": "0.0005",
        "baseSizePrecision": "0",
        "quoteAmountPrecisionMarket": "1",
        "baseAsset": "YY",
        "orderTypes": ["MARKET"],
    }
    assert parse_symbol_rule(tagged).tradable is False
    no_market = dict(tagged)
    no_market["symbol"] = "ZZUSDT"
    no_market["baseAsset"] = "ZZ"
    no_market["st"] = False
    no_market["orderTypes"] = ["LIMIT"]
    assert parse_symbol_rule(no_market).refuse_reason == "market orders are off"
    broken = dict(floki.__dict__) if False else {
        "symbol": "FLOKIUSDT",
        "status": "1",
        "isSpotTradingAllowed": True,
        "quoteAsset": "USDT",
        "st": False,
        "conceptPlates": [],
        "takerCommission": "0.0008",
        "baseSizePrecision": "1",
        "quoteAmountPrecisionMarket": "1",
            "maxQuoteAmountMarket": "not-a-number",
            "baseAsset": "FLOKI",
            "quotePrecision": "8",
            "orderTypes": ["MARKET"],
        "tradeSideType": "1",
    }
    refused = parse_symbol_rule(broken)
    assert refused.tradable is False
    assert refused.refuse_reason == "max quote is not decimal"
    missing_tick = dict(broken)
    missing_tick["quotePrecision"] = ""
    missing_tick["maxQuoteAmountMarket"] = "200000"
    assert parse_symbol_rule(missing_tick).refuse_reason == "price precision is missing"
    omitted = dict(floki.__dict__) if False else {
        "symbol": "FLOKIUSDT",
        "status": "1",
        "isSpotTradingAllowed": True,
        "quoteAsset": "USDT",
        "st": False,
        "baseAsset": "FLOKI",
        "takerCommission": "0.0008",
        "baseSizePrecision": "1",
        "quoteAmountPrecisionMarket": "1",
    }
    assert parse_symbol_rule(omitted).refuse_reason == "market orders are off"
    spot_off = dict(omitted)
    spot_off["orderTypes"] = ["MARKET"]
    spot_off["isSpotTradingAllowed"] = None
    assert parse_symbol_rule(spot_off).refuse_reason == "spot trading is off"
    wrong_base = dict(spot_off)
    wrong_base["isSpotTradingAllowed"] = True
    wrong_base["baseAsset"] = "ETH"
    assert parse_symbol_rule(wrong_base).refuse_reason == "base asset does not match the symbol"
    one_way = dict(wrong_base)
    one_way["baseAsset"] = "FLOKI"
    one_way["symbol"] = "FLOKIUSDT"
    one_way["tradeSideType"] = "2"
    assert parse_symbol_rule(one_way).refuse_reason == "spot side is not two-way"
    missing_side = dict(one_way)
    del missing_side["tradeSideType"]
    assert parse_symbol_rule(missing_side).refuse_reason == "spot side is not two-way"
    planned = plan_paper_buy(10_000_000, 100_000_000, 100, 5)
    assert planned is not None
    base, fee, debit = planned
    assert base % 100 == 0
    assert fee > 0
    assert debit <= 10_000_000


def test_absent_order_clears_only_after_three_misses() -> None:
    from spotbot.reconcile import pending_gone

    assert pending_gone(1, 0, False) is False
    assert pending_gone(2, 0, False) is False
    assert pending_gone(3, 0, False) is True
    assert pending_gone(3, 1, False) is False
    assert pending_gone(3, 0, True) is False
    from spotbot.reconcile import fee_fits

    assert fee_fits(4_000, 4_000) is True
    assert fee_fits(4_001, 4_000) is False
    assert fee_fits(-1, 4_000) is False
    from spotbot.reconcile import FeeAssetError, split_commission

    assert split_commission(
        [{
            "id": "7",
            "orderId": "1",
            "symbol": "BTCUSDT",
            "qty": "0.5",
            "quoteQty": "6",
            "price": "12",
            "commission": "0",
            "commissionAsset": "USDT",
            "isBuyer": True,
        }],
        "1",
        "BTC",
        "BUY",
    ) == (0, 0, 50_000_000, 6_000_000)
    from spotbot.reconcile import fills_match

    assert fills_match(50_000_000, 6_000_000, 50_000_000, 6_000_000) is True
    assert fills_match(40_000_000, 6_000_000, 50_000_000, 6_000_000) is False
    try:
        split_commission(
            [{"orderId": "2", "symbol": "BTCUSDT", "commission": "0.01", "commissionAsset": "USDT"}],
            "1",
            "BTC",
            "BUY",
        )
    except FeeAssetError:
        pass
    else:
        raise AssertionError("a missing trade row is not a zero fee")
    try:
        split_commission(
            [{"id": "1", "orderId": "1", "symbol": "ETHUSDT", "commission": "0.01", "commissionAsset": "USDT"}],
            "1",
            "BTC",
            "BUY",
        )
    except FeeAssetError:
        pass
    else:
        raise AssertionError("a trade for another symbol is not this order")
    repeated = {
        "id": "7",
        "orderId": "1",
        "symbol": "BTCUSDT",
        "qty": "0.5",
        "quoteQty": "6",
        "price": "12",
        "commission": "0",
        "commissionAsset": "USDT",
        "isBuyer": True,
    }
    try:
        split_commission([repeated, dict(repeated)], "1", "BTC", "BUY")
    except FeeAssetError:
        pass
    else:
        raise AssertionError("the same trade id is not a second fill")
    try:
        split_commission([{**repeated, "isBuyer": False}], "1", "BTC", "BUY")
    except FeeAssetError:
        pass
    else:
        raise AssertionError("a sell print is not a buy fill")


def test_exchange_body_must_be_json() -> None:
    from spotbot.mexc import MexcError, _json_body

    class _Body:
        def json(self) -> dict[str, str]:
            raise ValueError("not json")

    try:
        _json_body(_Body(), "order")
    except MexcError as exc:
        assert "not json" in str(exc)
    else:
        raise AssertionError("a broken body must stay an exchange error")


def test_exchange_error_code_is_not_an_order() -> None:
    from spotbot.mexc import MexcError, _reject_exchange_code

    _reject_exchange_code({"symbol": "BTCUSDT", "status": "FILLED", "orderId": "1"})
    _reject_exchange_code({"code": 200, "symbol": "BTCUSDT"})
    try:
        _reject_exchange_code({"code": -2010, "msg": "Account has insufficient balance"})
    except MexcError as exc:
        assert "-2010" in str(exc)
    else:
        raise AssertionError("an exchange error code must not pass as an order")
    from spotbot.mexc import MexcRateLimit

    try:
        _reject_exchange_code({"code": 429, "msg": "Too Many Requests"})
    except MexcRateLimit as exc:
        assert "429" in str(exc)
    else:
        raise AssertionError("a rate-limit code in the body must stop the caller")
    try:
        _reject_exchange_code({"code": "418", "msg": "banned"})
    except MexcRateLimit as exc:
        assert "418" in str(exc)
    else:
        raise AssertionError("a ban code in the body must stop the caller")
    try:
        _reject_exchange_code({"code": 403, "msg": "Access Denied"})
    except MexcRateLimit as exc:
        assert exc.retry_after_sec is None
        assert "403" in str(exc)
    else:
        raise AssertionError("an access-denied code must stop the caller")


def test_rate_limit_pause_honors_retry_after() -> None:
    from spotbot.mexc import MexcError, backoff_sec

    assert backoff_sec(30, 60) == 60
    assert backoff_sec(180, 60) == 180
    assert backoff_sec(None, 60) == 120
    assert backoff_sec(10**9, 60) == 259_200
    try:
        backoff_sec(30, 0)
    except MexcError as exc:
        assert "interval" in str(exc)
    else:
        raise AssertionError("a zero interval must not compute a pause")


def test_ten_fail_closed_checks() -> None:
    from spotbot.mexc import MexcError, book_prices, executed_fill, parse_klines, positive_int
    from spotbot.sanity import follows_close

    assert positive_int("1700000000000", "server time") == 1_700_000_000_000
    try:
        positive_int(True, "server time")
    except MexcError as exc:
        assert "integer" in str(exc)
    else:
        raise AssertionError("a boolean clock must be refused")
    try:
        positive_int(1.5, "server time")
    except MexcError as exc:
        assert "integer" in str(exc)
    else:
        raise AssertionError("a fractional clock must be refused")

    assert book_prices(
        {"symbol": "BTCUSDT", "bidPrice": "1", "askPrice": "1.01", "bidQty": "0.1", "askQty": "0.2"},
        "BTCUSDT",
    )[0] > 0
    try:
        book_prices({"bidPrice": "1", "askPrice": "1.01", "bidQty": "0", "askQty": "1"}, "BTCUSDT")
    except MexcError as exc:
        assert "empty book" in str(exc)
    else:
        raise AssertionError("a book level with no size must be refused")
    try:
        book_prices({"bidPrice": "0", "askPrice": "0"}, "BTCUSDT")
    except MexcError as exc:
        assert "empty book" in str(exc)
    else:
        raise AssertionError("a zero book must be refused")

    row = [1_000, "1", "1.1", "0.9", "1", "1", 2_000, "10"]
    later = [3_000, "1", "1.1", "0.9", "1", "1", 4_000, "10"]
    assert len(parse_klines("BTCUSDT", [row, later])) == 2
    quiet = [2_000, "1", "1.1", "0.9", "1", "0", 3_000, "0"]
    after = [3_000, "1", "1.1", "0.9", "1", "1", 4_000, "10"]
    assert len(parse_klines("BTCUSDT", [row, quiet, after])) == 2
    live = [1_700_000_000_000, "1", "1", "1", "1", "1", 1_700_000_300_000, "1"]
    live_next = [1_700_000_300_000, "1", "1", "1", "1", "1", 1_700_000_600_000, "1"]
    assert len(parse_klines("BTCUSDT", [live, live_next], 300_000)) == 2
    old = [1_700_000_000_000, "1", "1", "1", "1", "1", 1_700_000_299_999, "1"]
    old_next = [1_700_000_300_000, "1", "1", "1", "1", "1", 1_700_000_599_999, "1"]
    assert len(parse_klines("BTCUSDT", [old, old_next], 300_000)) == 2
    overlap = [1_500, "1", "1.1", "0.9", "1", "1", 2_500, "10"]
    try:
        parse_klines("BTCUSDT", [row, overlap])
    except MexcError as exc:
        assert "out of order" in str(exc)
    else:
        raise AssertionError("a candle that overlaps the previous one must be refused")
    broken = [5_000, "1", "0.5", "0.9", "1", "1", 6_000, "10"]
    try:
        parse_klines("BTCUSDT", [row, broken])
    except MexcError as exc:
        assert "range" in str(exc)
    else:
        raise AssertionError("a candle outside its range must be refused")
    backwards = [1_500, "1", "1.1", "0.9", "1", "1", 1_800, "10"]
    try:
        parse_klines("BTCUSDT", [later, backwards])
    except MexcError as exc:
        assert "out of order" in str(exc)
    else:
        raise AssertionError("a candle that steps backward must be refused")

    assert executed_fill({"executedQty": "0.000", "cummulativeQuoteQty": "1"}) is None
    try:
        executed_fill({"executedQty": "nope", "cummulativeQuoteQty": "1"})
    except MexcError as exc:
        assert "not decimal" in str(exc)
    else:
        raise AssertionError("a bad quantity must stay an error")

    close = 100_000_000_000_000
    assert follows_close(close, close * 11_500 // 10_000) is True
    assert follows_close(close, close * 12_000 // 10_000) is False


def test_named_rows_and_the_trade_list() -> None:
    from spotbot.mexc import (
        MexcClient,
        MexcError,
        book_prices,
        depth_notionals,
        parse_account,
        parse_klines,
        signed_payload,
        ticker_price,
    )
    from spotbot.oracle import _binance_price, _bybit_price, _okx_price

    try:
        book_prices(
            {"symbol": "ETHUSDT", "bidPrice": "1", "askPrice": "1.01", "bidQty": "1", "askQty": "1"},
            "BTCUSDT",
        )
    except MexcError as exc:
        assert "not BTCUSDT" in str(exc)
    else:
        raise AssertionError("a book for another pair must be refused")
    try:
        ticker_price({"symbol": "ETHUSDT", "price": "1"}, "BTCUSDT")
    except MexcError as exc:
        assert "not BTCUSDT" in str(exc)
    else:
        raise AssertionError("a last price for another pair must be refused")
    assert _binance_price({"symbol": "ETHUSDT", "price": "1"}, "BTCUSDT") is None
    assert _bybit_price({"result": {"list": [{"symbol": "ETHUSDT", "lastPrice": "1"}]}}, "BTCUSDT") is None
    assert _okx_price({"data": [{"instId": "ETH-USDT", "last": "1"}]}, "BTC-USDT") is None

    client = MexcClient("", "", 5)
    client._public = lambda _path, _params: {"symbols": [{"symbol": "ETHUSDT"}]}  # type: ignore[method-assign]
    try:
        client.symbol_rule("BTCUSDT")
    except MexcError as exc:
        assert "not BTCUSDT" in str(exc)
    else:
        raise AssertionError("exchangeInfo for another pair must be refused")
    assert "BTCUSDT" not in client._rules

    assert signed_payload([{"id": "1"}], True) == [{"id": "1"}]
    try:
        signed_payload([{"id": "1"}], False)
    except MexcError as exc:
        assert "not an object" in str(exc)
    else:
        raise AssertionError("a trade list must not be read as an order")

    quiet = [1_000, "1", "1.1", "0.9", "1", "1", 2_000, "0"]
    loud = [3_000, "1", "1.1", "0.9", "1", "1", 4_000, "10"]
    try:
        parse_klines("BTCUSDT", [quiet, loud])
    except MexcError as exc:
        assert "volume" in str(exc)
    else:
        raise AssertionError("a candle with no quote volume must be refused")
    short = [3_000, "1", "1.1", "0.9", "1", "1", 3_500, "10"]
    try:
        parse_klines("BTCUSDT", [[1_000, "1", "1.1", "0.9", "1", "1", 2_000, "10"], short])
    except MexcError as exc:
        assert "interval" in str(exc)
    else:
        raise AssertionError("a candle of another length must be refused")

    try:
        depth_notionals({"bids": [["1", "0"]], "asks": [["1.01", "1"]]}, "BTCUSDT")
    except MexcError as exc:
        assert "empty depth" in str(exc)
    else:
        raise AssertionError("a depth side with no size must be refused")
    try:
        depth_notionals({"bids": [["2", "1"]], "asks": [["1", "1"]]}, "BTCUSDT")
    except MexcError as exc:
        assert "crossed depth" in str(exc)
    else:
        raise AssertionError("a crossed depth must be refused")

    _total, free, bases, _free_bases = parse_account(
        {"balances": [{"asset": "btc", "free": "1", "locked": "0"}]}
    )
    assert free == 0 and bases["BTC"] == 100_000_000
    try:
        parse_account({"balances": [{"asset": "USDT", "free": "-1", "locked": "0"}]})
    except MexcError as exc:
        assert "negative" in str(exc)
    else:
        raise AssertionError("a negative balance must be refused")


def test_band_clock_journal_and_the_day(tmp_path) -> None:
    from datetime import datetime, timedelta, timezone

    from spotbot.engine import _now_ms, _now_sec
    from spotbot.guards import drawdown_blocks
    from spotbot.journal import note_quote
    from spotbot.mexc import rank_liquid
    from spotbot.signals import below_lower_band
    from spotbot.state import Book, LedgerError, Position, audit_book

    assert below_lower_band([10**17 + i for i in range(20)]) is False
    assert drawdown_blocks(1_000_000, -1, 1_000) is True
    assert _now_ms() // 1000 == _now_sec() or _now_ms() // 1000 == _now_sec() - 1

    (tmp_path / "ops_quotes.json").write_text("{", encoding="utf-8")
    note_quote(tmp_path, "BTCUSDT", "1", "-", "-", "-", None, None)
    saved = (tmp_path / "ops_quotes.json").read_text(encoding="utf-8")
    assert "BTCUSDT" in saved and saved.strip().endswith("}")

    rows = rank_liquid(
        [
            {"symbol": "btcusdt", "quoteVolume": "100", "priceChangePercent": "1"},
            {"symbol": "ETHUSDT", "quoteVolume": "50", "priceChangePercent": "1"},
            {"symbol": "ETHUSDT", "quoteVolume": "80", "priceChangePercent": "1"},
            {"symbol": "XRPUSDT", "quoteVolume": "90", "priceChangePercent": ""},
        ],
        1,
        50,
        200,
        8,
    )
    assert rows == ["ETHUSDT"]

    low = Book(
        cash_micro=1,
        positions=[Position("btcUSDT", 1, 1, 1, 1, "x")],
        realized_micro=0,
    )
    try:
        audit_book(low)
    except LedgerError as exc:
        assert "USDT" in str(exc)
    else:
        raise AssertionError("a lowercase pair must not open")
    tomorrow = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    ahead = Book(cash_micro=1, positions=[], realized_micro=0, guard_day=tomorrow)
    try:
        audit_book(ahead)
    except LedgerError as exc:
        assert "future" in str(exc)
    else:
        raise AssertionError("a future guard day must not open")


def test_treasury_and_a_repeated_market_row(tmp_path) -> None:
    from spotbot.mexc import MexcClient, MexcError, depth_notionals, parse_account
    from spotbot.ops_http import OpsError, _Handler, parse_ops_port
    from spotbot.sleeves import SleeveError, apply_funding
    from spotbot.state import LedgerError, load_book

    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "treasury.json").write_text('{"funded_micro": true}', encoding="utf-8")
    try:
        apply_funding(tmp_path, 100_000_000)
    except SleeveError as exc:
        assert "integer" in str(exc)
    else:
        raise AssertionError("a boolean treasury must not add cash")
    assert not (paper / "sleeve_major.json").exists()
    (paper / "treasury.json").write_text('{"funded_micro": -1}', encoding="utf-8")
    try:
        apply_funding(tmp_path, 100_000_000)
    except SleeveError as exc:
        assert "integer" in str(exc)
    else:
        raise AssertionError("a negative treasury must not add cash")
    (paper / "treasury.json").write_text("{", encoding="utf-8")
    try:
        apply_funding(tmp_path, 100_000_000)
    except SleeveError as exc:
        assert "not json" in str(exc)
    else:
        raise AssertionError("a broken treasury must not add cash")

    book_path = tmp_path / "book.json"
    book_path.write_text("{", encoding="utf-8")
    try:
        load_book(book_path, 1)
    except LedgerError as exc:
        assert "not json" in str(exc)
    else:
        raise AssertionError("a broken book must not open")
    assert book_path.read_text(encoding="utf-8") == "{"

    client = MexcClient("", "", 5)
    try:
        client.market_buy_quote("BTCUSDT", 0, "a" * 32)
    except MexcError as exc:
        assert "positive size" in str(exc)
    else:
        raise AssertionError("a zero buy must not be sent")
    client._public = lambda _path, _params: {"symbols": [{"symbol": "BTCUSDT"}, {"symbol": "BTCUSDT"}]}  # type: ignore[method-assign]
    try:
        client.symbol_rule("BTCUSDT")
    except MexcError as exc:
        assert "more than one" in str(exc)
    else:
        raise AssertionError("two exchangeInfo rows must be refused")
    assert "BTCUSDT" not in client._rules

    try:
        parse_account({"balances": [{"asset": "BTC", "free": "1", "locked": "0"}, {"asset": "btc", "free": "1", "locked": "0"}]})
    except MexcError as exc:
        assert "repeated" in str(exc)
    else:
        raise AssertionError("the same coin twice must not be summed")
    try:
        depth_notionals({"bids": [["1", "1"], ["1", "2"]], "asks": [["2", "1"]]}, "BTCUSDT")
    except MexcError as exc:
        assert "repeated" in str(exc)
    else:
        raise AssertionError("the same depth price twice must be refused")
    try:
        parse_ops_port("18180")
    except OpsError as exc:
        assert "18180" in str(exc)
    else:
        raise AssertionError("the mesh port must be refused")
    try:
        parse_ops_port("nope")
    except OpsError as exc:
        assert "integer" in str(exc)
    else:
        raise AssertionError("a named port must be refused")

    class _Fake:
        def _send(self, code: int, _content_type: str, body: bytes) -> None:
            self.code = code
            self.body = body

    fake = _Fake()
    _Handler.do_PUT(fake)  # type: ignore[arg-type]
    assert fake.code == 405 and fake.body == b"read only"


def test_redirects_bools_and_a_missing_field() -> None:
    from spotbot.fees import fee_on
    from spotbot.mexc import MexcError, depth_notionals
    from spotbot.reconcile import order_is_ours
    from spotbot.rules import round_base_atoms, round_quote_micro
    from spotbot.sleeves import SleeveError, split_equal
    from spotbot.state import LedgerError, Position, load_book

    ack = {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "type": "MARKET",
        "clientOrderId": "abc",
        "origClientOrderId": "other",
    }
    assert order_is_ours(ack, "BTCUSDT", "BUY", "abc") is False
    try:
        depth_notionals(
            {"lastUpdateId": 0, "bids": [["1", "1"]], "asks": [["2", "1"]]},
            "BTCUSDT",
        )
    except MexcError as exc:
        assert "update" in str(exc)
    else:
        raise AssertionError("a depth without an update id must be refused")
    try:
        fee_on(1_000_000, True)
    except ValueError as exc:
        assert "integer" in str(exc)
    else:
        raise AssertionError("a boolean fee must be refused")
    assert round_base_atoms(100, True) == 0
    assert round_quote_micro(100, True) == 0
    try:
        split_equal(True, 3)
    except SleeveError as exc:
        assert "integer" in str(exc)
    else:
        raise AssertionError("a boolean split must be refused")
    try:
        Position.from_json({"symbol": "BTCUSDT"})
    except LedgerError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("a position without a price must not open")
    import json
    import tempfile
    from pathlib import Path

    from spotbot.sleeves import apply_funding

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        book_path = root / "book.json"
        book_path.write_text(json.dumps({"positions": []}), encoding="utf-8")
        try:
            load_book(book_path, 1)
        except LedgerError as exc:
            assert "missing" in str(exc)
        else:
            raise AssertionError("a book without cash must not open")
        assert book_path.read_text(encoding="utf-8").startswith("{")
        try:
            apply_funding(root, True)
        except SleeveError as exc:
            assert "integer" in str(exc)
        else:
            raise AssertionError("a boolean main balance must not fund the sleeves")
        assert not (root / "paper" / "sleeve_major.json").exists()


def test_pair_limits_round_up_and_a_zero_fee_is_not_stuck() -> None:
    from spotbot.mexc import ack_commission
    from spotbot.rules import parse_symbol_rule

    row = {
        "symbol": "BTCUSDT",
        "status": "1",
        "isSpotTradingAllowed": True,
        "quoteAsset": "USDT",
        "st": False,
        "conceptPlates": [],
        "takerCommission": "0.00001",
        "baseSizePrecision": "0.000001",
        "quoteAmountPrecisionMarket": "1",
        "maxQuoteAmountMarket": "200000",
        "baseAsset": "BTC",
        "orderTypes": ["MARKET"],
        "tradeSideType": "1",
        "quotePrecision": "2",
    }
    rule = parse_symbol_rule(row)
    assert rule.tradable is True
    assert rule.taker_bps == 1
    missing_step = dict(row)
    missing_step["baseSizePrecision"] = "0"
    assert parse_symbol_rule(missing_step).refuse_reason == "base step is missing"
    missing_quote = dict(row)
    missing_quote["quoteAmountPrecisionMarket"] = "0"
    assert parse_symbol_rule(missing_quote).refuse_reason == "market min quote is not positive"
    zero_cap = dict(row)
    zero_cap["maxQuoteAmountMarket"] = "0"
    assert parse_symbol_rule(zero_cap).refuse_reason == "max quote is not positive"
    assert ack_commission({"commission": "0.00000000", "commissionAsset": "USDT"}, "BTC") == (0, 0)
    from spotbot.mexc import new_client_order_id

    assert new_client_order_id("BTCUSDT", "B") != new_client_order_id("BTCUSDT", "B")


def test_paper_sell_keeps_dust_below_the_lot() -> None:
    from spotbot.fees import paper_sell
    from spotbot.rules import round_base_atoms
    from spotbot.state import Book, Position, record_sell_fill

    step = 100_000_000
    base = 150_000_000
    sell = round_base_atoms(base, step)
    credit, fee = paper_sell(sell, 10_000_000_000_000, 5)
    book = Book(
        cash_micro=0,
        positions=[Position("BTCUSDT", 10_000_000, 10_000_000, 15_000_000, base, "test")],
        realized_micro=0,
    )
    assert record_sell_fill(book, "BTCUSDT", sell, credit, fee)
    assert len(book.positions) == 1
    assert book.positions[0].base_atoms == 50_000_000
    assert fee > 0


def test_sell_ack_is_the_fill() -> None:
    from spotbot.mexc import MexcError, _sell_credit

    credit, fee, base_fee = _sell_credit(
        {
            "status": "FILLED",
            "cummulativeQuoteQty": "10.5",
            "commission": "0.01",
            "commissionAsset": "USDT",
        },
        "BTC",
    )
    assert fee == 10_000
    assert base_fee == 0
    assert credit == 10_490_000
    try:
        _sell_credit(
            {
                "status": "FILLED",
                "cummulativeQuoteQty": "10.5",
                "commission": "0.01",
                "commissionAsset": "MX",
            },
            "BTC",
        )
    except MexcError:
        pass
    else:
        raise AssertionError("a fee in a third coin is not zero")
    try:
        _sell_credit({"cummulativeQuoteQty": "1", "executedQty": "1"}, "BTC")
    except MexcError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("a fill with no status is not filled")
    from spotbot.mexc import _filled_quote
    from spotbot.signals import closed_prices

    assert _filled_quote({"status": "FILLED", "cummulativeQuoteQty": "3.5"}, "buy") == 3_500_000
    try:
        _filled_quote({"status": "FILLED", "executedQty": "1"}, "buy")
    except MexcError:
        pass
    else:
        raise AssertionError("requested quote is not a fill")
    assert closed_prices([10, 20, 30]) == [10, 20]
    assert closed_prices([10]) == []
    try:
        _sell_credit({"status": "NEW", "cummulativeQuoteQty": "1"}, "BTC")
    except MexcError:
        pass
    else:
        raise AssertionError("an unfilled sell must not credit cash")


def test_daily_loss_stops_new_entries() -> None:
    from spotbot.engine import _entries_halted, trading_day
    from spotbot.state import Book

    today = trading_day()
    book = Book(
        cash_micro=100_000_000,
        positions=[],
        realized_micro=-5_000_000,
        guard_day=today,
        guard_realized_micro=0,
        guard_cash_micro=100_000_000,
    )
    assert _entries_halted(book, 500) is True
    book.realized_micro = -1_000_000
    assert _entries_halted(book, 500) is False
    assert _entries_halted(book, 500, 4_000_000) is True
    book.guard_day = "2000-01-01"
    book.realized_micro = 0
    book.guard_realized_micro = 0
    assert _entries_halted(book, 500, 5_000_000) is True
    assert book.guard_day == today
    from spotbot.engine import _roll_guard

    rolled = Book(
        cash_micro=100_000_000,
        positions=[],
        realized_micro=0,
        guard_day="2000-01-01",
        guard_realized_micro=0,
        guard_cash_micro=1,
    )
    _roll_guard(rolled)
    rolled.realized_micro = -5_000_000
    assert _entries_halted(rolled, 500) is True
    flat = Book(
        cash_micro=0,
        positions=[],
        realized_micro=-5_000_000,
        guard_day=today,
        guard_realized_micro=0,
        guard_cash_micro=0,
    )
    assert _entries_halted(flat, 500) is True
    flat.realized_micro = 5_000_000
    assert _entries_halted(flat, 500) is False


def test_new_entries_stay_off_and_exits_still_run(tmp_path, monkeypatch) -> None:
    from spotbot.config import Config, ConfigError, load_config
    from spotbot.engine import run_cycle
    from spotbot.rules import SymbolRule
    from spotbot.state import Book, Position, load_book, save_book

    monkeypatch.setattr("spotbot.engine.venue_quotes", lambda _symbol: {})
    monkeypatch.setenv("SPOT_SYMBOLS", "BTCUSDT")
    monkeypatch.setenv("SPOT_INTERVAL_SEC", "60")
    monkeypatch.setenv("SPOT_LIVE", "0")
    monkeypatch.setenv("SPOT_MODE", "rsi")
    monkeypatch.setenv("SPOT_TAKER_BPS", "5")
    monkeypatch.setenv("SPOT_DAILY_LOSS_BPS", "500")
    monkeypatch.setenv("SPOT_STOP_COOLDOWN_SEC", "900")
    monkeypatch.setenv("SPOT_PAPER_CASH_USDT", "1000")
    monkeypatch.setenv("SPOT_MIN_USDT", "3")
    monkeypatch.setenv("SPOT_ALLOC_BPS", "2000")
    monkeypatch.setenv("SPOT_RSI_BUY", "35")
    monkeypatch.setenv("SPOT_MAX_POSITIONS", "1")
    monkeypatch.setenv("SPOT_ENTRIES", "2")
    try:
        load_config(False)
    except ConfigError as exc:
        assert "SPOT_ENTRIES" in str(exc)
    else:
        raise AssertionError("SPOT_ENTRIES must be 0 or 1")

    class _Book:
        def forget_rules(self) -> None:
            return None

        def symbol_rule(self, symbol: str) -> SymbolRule:
            return SymbolRule(symbol, True, "", 5, 1, 1, 0, "BTC")

        def book_top(self, _symbol: str) -> tuple[int, int]:
            return 90_000_000_000_000, 90_100_000_000_000

        def klines(self, _symbol: str) -> list[int]:
            raise AssertionError("a new entry must not be scanned while entries are off")

    cfg = Config(
        symbols=("BTCUSDT",),
        paper_cash_micro=1_000_000,
        interval_sec=60,
        max_positions=1,
        alloc_bps=10_000,
        min_notional_micro=1,
        rsi_buy=35,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        live=False,
        mode="rsi",
        taker_bps=5,
        daily_loss_bps=500,
        stop_cooldown_sec=0,
        symbol_lock=True,
        api_key="",
        api_secret="",
    )
    path = tmp_path / "off.json"
    save_book(
        path,
        Book(
            cash_micro=0,
            positions=[Position("BTCUSDT", 100_000_000_000_000, 100_000_000_000_000, 10_000_000, 100_000_000, "test")],
            realized_micro=0,
        ),
    )
    report = run_cycle(cfg, _Book(), path)
    saved = load_book(path, 0)
    assert report.exits == 1
    assert report.entries == 0
    assert saved.positions == []
    assert saved.cash_micro > 0


def test_rate_limit_does_not_start_the_next_sleeve(tmp_path, monkeypatch) -> None:
    from spotbot.config import Config
    from spotbot.mexc import MexcError, MexcRateLimit
    from spotbot.sleeves import run_sleeves

    calls: list[str] = []

    def _cycle(cfg: Config, client: object, path: object, book_name: str = "", sibling_paths: tuple[object, ...] = ()) -> None:
        calls.append(book_name)
        if book_name == "major":
            raise MexcRateLimit("429")
        raise AssertionError(f"{book_name} must wait")

    monkeypatch.setattr("spotbot.sleeves.run_cycle", _cycle)
    cfg = Config(
        symbols=("BTCUSDT",),
        paper_cash_micro=3_000_000,
        interval_sec=60,
        max_positions=1,
        alloc_bps=10_000,
        min_notional_micro=1_000_000,
        rsi_buy=35,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        live=False,
        mode="rsi",
        taker_bps=5,
        daily_loss_bps=500,
        stop_cooldown_sec=900,
        symbol_lock=True,
        api_key="",
        api_secret="",
    )
    try:
        run_sleeves(cfg, object(), tmp_path)
    except MexcRateLimit as exc:
        assert "429" in str(exc)
    else:
        raise AssertionError("a rate limit must stop the remaining sleeves")
    assert calls == ["major"]

    calls.clear()

    def _continue(cfg: Config, client: object, path: object, book_name: str = "", sibling_paths: tuple[object, ...] = ()) -> None:
        calls.append(book_name)
        if book_name == "major":
            raise MexcError("rules down")

    monkeypatch.setattr("spotbot.sleeves.run_cycle", _continue)
    run_sleeves(cfg, object(), tmp_path)
    assert calls == ["major", "alt", "meme"]


def test_rate_limit_stops_the_cycle_and_keeps_the_book(tmp_path) -> None:
    from spotbot.config import Config
    from spotbot.engine import run_cycle
    from spotbot.mexc import MexcRateLimit
    from spotbot.rules import SymbolRule
    from spotbot.state import Book, Position, load_book, save_book

    seen: list[str] = []

    class _Limit:
        def forget_rules(self) -> None:
            return None

        def symbol_rule(self, symbol: str) -> SymbolRule:
            asset = symbol.replace("USDT", "")
            return SymbolRule(symbol, True, "", 5, 1, 1, 0, asset)

        def book_top(self, symbol: str) -> tuple[int, int]:
            seen.append(symbol)
            raise MexcRateLimit("429")

        def klines(self, _symbol: str) -> list[int]:
            raise AssertionError("a rate limit must not start the entry scan")

    cfg = Config(
        symbols=("BTCUSDT", "ETHUSDT"),
        paper_cash_micro=1_000_000,
        interval_sec=60,
        max_positions=2,
        alloc_bps=10_000,
        min_notional_micro=1,
        rsi_buy=35,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        live=False,
        mode="rsi",
        taker_bps=5,
        daily_loss_bps=500,
        stop_cooldown_sec=0,
        symbol_lock=True,
        api_key="",
        api_secret="",
    )
    path = tmp_path / "limit.json"
    save_book(
        path,
        Book(
            cash_micro=0,
            positions=[
                Position("BTCUSDT", 100_000_000_000_000, 100_000_000_000_000, 10_000_000, 100_000_000, "test"),
                Position("ETHUSDT", 100_000_000_000_000, 100_000_000_000_000, 10_000_000, 100_000_000, "test"),
            ],
            realized_micro=0,
        ),
    )
    try:
        run_cycle(cfg, _Limit(), path)
    except MexcRateLimit as exc:
        assert "429" in str(exc)
    else:
        raise AssertionError("a rate limit must leave the cycle after the book is saved")
    saved = load_book(path, 0)
    assert seen == ["BTCUSDT"]
    assert [pos.symbol for pos in saved.positions] == ["BTCUSDT", "ETHUSDT"]


def test_holdout_keeps_a_later_slice() -> None:
    from spotbot.replay import holdout_cut

    assert holdout_cut(500) == 300
    assert holdout_cut(160) == 80
    try:
        holdout_cut(159)
    except ValueError:
        pass
    else:
        raise AssertionError("a short tape must not be split")


def test_stop_pauses_the_next_entry() -> None:
    from spotbot.engine import mark_stop_cooldown
    from spotbot.state import Book

    book = Book(cash_micro=1, positions=[], realized_micro=0)
    mark_stop_cooldown(book, "take_profit", 900)
    assert book.cooldown_until == 0
    mark_stop_cooldown(book, "stop", 900)
    assert book.cooldown_until > int(__import__("time").time())


def test_ops_refuses_the_mesh_ports() -> None:
    from spotbot.ops_http import OpsError, check_ops_port

    check_ops_port(19280)
    for port in (18180, 18181, 18182):
        try:
            check_ops_port(port)
        except OpsError:
            continue
        raise AssertionError(f"port {port} must be refused")


def test_ops_snapshot_drops_secrets(tmp_path) -> None:
    import json

    from spotbot.journal import note_event, note_quote
    from spotbot.ops_http import snapshot

    (tmp_path / "sleeve_major.json").write_text(
        json.dumps(
            {
                "cash_micro": 33_333_334,
                "realized_micro": 0,
                "fees_micro": 0,
                "positions": [],
                "api_secret": "do-not-show",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "ops.log").write_text("cycle ok\napi_secret=hidden\n", encoding="utf-8")
    note_event(tmp_path, book="major", kind="exit", symbol="BTCUSDT", reason="stop", price="100.000000")
    note_quote(tmp_path, "BTCUSDT", "100.000000", "100.010000", "100.020000", "-", -1, 2)
    view = snapshot(tmp_path, 19280)
    text = json.dumps(view)
    assert "do-not-show" not in text
    assert "hidden" not in text
    assert view["books"]["sleeve_major"]["cash_micro"] == 33_333_334
    assert view["events"][-1]["symbol"] == "BTCUSDT"
    assert view["quotes"]["BTCUSDT"]["lag_bps"] == -1
    assert view["log"] == ["cycle ok"]
    (tmp_path / "paper").mkdir()
    (tmp_path / "paper" / "book.json").write_text("{", encoding="utf-8")
    (tmp_path / "ops_events.jsonl").write_text("not-json\n", encoding="utf-8")
    broken = snapshot(tmp_path, 19280)
    assert broken["books"]["paper/book"] == {"error": "book is not json"}
    assert broken["books"]["sleeve_major"]["cash_micro"] == 33_333_334
    assert "unreadable" == _shown_price()


def _shown_price() -> str:
    from spotbot.ops_http import _show_book

    view = _show_book(
        {
            "price_scale": 1_000_000_000_000,
            "positions": [{"symbol": "BTCUSDT", "entry_micro": 1.5, "peak_micro": 1}],
        }
    )
    return str(view["positions"][0]["entry_micro"])


def test_ops_page_answers_on_its_own_port(tmp_path) -> None:
    import json
    import threading
    import urllib.request

    from spotbot.ops_http import serve

    threading.Thread(target=serve, args=(tmp_path, 19281), daemon=True).start()
    body = ""
    status = ""
    for _ in range(30):
        try:
            with urllib.request.urlopen("http://127.0.0.1:19281/", timeout=1) as res:
                body = res.read().decode("utf-8")
            with urllib.request.urlopen("http://127.0.0.1:19281/api/status", timeout=1) as res:
                status = res.read().decode("utf-8")
            break
        except OSError:
            time.sleep(0.05)
    assert "Спот-бот" in body
    assert json.loads(status)["bind"] == "127.0.0.1:19281"
    assert "18180-18182" in status


def test_replay_signal_uses_the_cycle_window() -> None:
    import inspect

    from spotbot.mexc import KLINE_LIMIT, MexcClient
    from spotbot.replay import _signal_closes

    assert inspect.signature(MexcClient.klines).parameters["limit"].default == KLINE_LIMIT
    closes = list(range(1, 400))
    window = _signal_closes(closes, len(closes) - 1)
    assert len(window) == KLINE_LIMIT - 1
    assert window[-1] == closes[-1]
    assert window[0] == closes[-(KLINE_LIMIT - 1)]


def test_klines_returns_the_close_not_the_quote_volume() -> None:
    from spotbot.mexc import MexcClient

    client = MexcClient("", "")
    client.ohlcv = lambda *_args, **_kwargs: [  # type: ignore[method-assign]
        (10, 12, 8, 11, 5_000_000),
        (10, 12, 8, 14, 9_000_000),
    ]
    assert client.klines("BTCUSDT", "5m", 80) == [11, 14]


def test_lift_candle_replay_loses_on_the_stop() -> None:
    from spotbot.replay import replay_lift_bars

    bars = [(100_000_000, 100_000_000, 100_000_000, 100)] * 14
    bars.append((110_000_000, 100_000_000, 108_000_000, 400))
    bars.append((110_000_000, 100_000_000, 108_000_000, 400))
    bars += [(100_000_000, 90_000_000, 100_000_000, 100)] * 3
    result = replay_lift_bars(
        bars,
        cash_micro=1_000_000_000,
        alloc_bps=10_000,
        taker_bps=5,
        min_notional_micro=1,
    )
    assert result.trades >= 1
    assert result.net_micro < 0


def test_account_must_match_the_book() -> None:
    from spotbot.mexc import parse_account
    from spotbot.reconcile import base_is_free, inventory_mismatch

    usdt, free_usdt, bases, free_bases = parse_account(
        {
            "balances": [
                {"asset": "USDT", "free": "40", "locked": "2"},
                {"asset": "BTC", "free": "0.01000000", "locked": "0.01000000"},
                {"asset": "ETH", "free": "0", "locked": "0"},
            ]
        }
    )
    assert usdt == 42_000_000
    assert free_usdt == 40_000_000
    assert bases["BTC"] == 2_000_000
    assert free_bases["BTC"] == 1_000_000
    assert "ETH" not in bases
    assert inventory_mismatch([("BTCUSDT", 2_000_000)], bases) is None
    assert inventory_mismatch([("BTCUSDT", 1_000_000)], bases) is not None
    assert inventory_mismatch([], bases) is not None
    assert inventory_mismatch([], {"BTC": 1_000_000}, [("BTCUSDT", 1_000_000)]) is None
    assert inventory_mismatch([("ETHUSDT", 50)], {"ETH": 50, "BTC": 1_000_000}, [("BTCUSDT", 1_000_000)]) is None
    assert inventory_mismatch([], {"BTC": 1_000_000, "DOGE": 5}, [("BTCUSDT", 1_000_000)]) is not None
    assert base_is_free(1_000_000, 1_000_000) is True
    assert base_is_free(1_000_000, 2_000_000) is False
    from spotbot.mexc import MexcError

    try:
        parse_account(
            {
                "balances": [
                    {"asset": "BTC", "free": "0.01", "locked": "0"},
                    {"asset": "BTC", "free": "0.01", "locked": "0"},
                ]
            }
        )
    except MexcError as exc:
        assert "repeated" in str(exc)
    else:
        raise AssertionError("the same coin twice must not be summed")
    try:
        parse_account({"balances": ["BTC"]})
    except MexcError:
        pass
    else:
        raise AssertionError("a broken balance row is not an empty account")
    try:
        parse_account({"balances": [{"asset": "", "free": "1", "locked": "0"}]})
    except MexcError:
        pass
    else:
        raise AssertionError("a nameless balance is not zero")


def test_live_spend_stops_at_free_usdt() -> None:
    from spotbot.rules import cap_spend

    step = 1_000_000
    assert cap_spend(33_000_000, 10_000_000, step, 3_000_000, 0) == 10_000_000
    assert cap_spend(33_000_000, 400_000, step, 3_000_000, 0) == 0
    assert cap_spend(100_000_000, 100_000_000, step, 3_000_000, 5_000_000) == 5_000_000


def test_canceled_partial_keeps_the_rest() -> None:
    from spotbot.mexc import MexcError, executed_fill
    from spotbot.reconcile import order_finished
    from spotbot.state import Book, Position, record_sell_fill

    assert order_finished({"status": "CANCELED"}) is True
    assert order_finished({"status": "PARTIALLY_FILLED"}) is False
    assert executed_fill({"executedQty": "0", "cummulativeQuoteQty": "0"}) is None
    try:
        executed_fill({"executedQty": "1", "cummulativeQuoteQty": "0"})
    except MexcError:
        pass
    else:
        raise AssertionError("a positive quantity with a zero quote is not an empty fill")
    try:
        executed_fill({"executedQty": "nope", "cummulativeQuoteQty": "1"})
    except MexcError:
        pass
    else:
        raise AssertionError("an unreadable quantity is not an empty fill")
    got = executed_fill({"executedQty": "0.5", "cummulativeQuoteQty": "6"})
    assert got is not None
    assert got[0] == 50_000_000
    book = Book(
        cash_micro=0,
        positions=[
            Position("BTCUSDT", 10_000_000, 10_000_000, 10_000_000, 100_000_000, "test"),
        ],
        realized_micro=0,
    )
    assert record_sell_fill(book, "BTCUSDT", 50_000_000, 6_000_000, 0)
    assert book.positions[0].base_atoms == 50_000_000
    assert book.positions[0].quote_micro == 5_000_000
    assert book.cash_micro == 6_000_000
    assert book.realized_micro == 1_000_000


def test_closing_one_coin_still_sees_the_next() -> None:
    from spotbot.state import Book, Position, record_sell_fill

    book = Book(
        cash_micro=0,
        positions=[
            Position("BTCUSDT", 1, 1, 1_000_000, 100_000_000, "a"),
            Position("ETHUSDT", 1, 1, 1_000_000, 100_000_000, "b"),
        ],
        realized_micro=0,
    )
    seen: list[str] = []
    for pos in list(book.positions):
        seen.append(pos.symbol)
        if pos.symbol == "BTCUSDT":
            assert record_sell_fill(book, pos.symbol, pos.base_atoms, 900_000, 0)
    assert seen == ["BTCUSDT", "ETHUSDT"]
    assert [pos.symbol for pos in book.positions] == ["ETHUSDT"]
    dust = Position("BTCUSDT", 1, 1, 100, 1_000, "dust")
    full = Position("BTCUSDT", 1, 1, 10_000_000, 100_000_000, "full")
    doubled = Book(cash_micro=0, positions=[dust, full], realized_micro=0)
    assert record_sell_fill(doubled, "BTCUSDT", 100_000_000, 9_000_000, 0) is False
    assert doubled.positions[0] is dust
    assert record_sell_fill(doubled, "BTCUSDT", 100_000_000, 9_000_000, 0, full)
    assert doubled.positions == [dust]
    assert dust.base_atoms == 1_000


def test_buy_fill_is_recorded_once() -> None:
    from spotbot.reconcile import order_missing, usdt_commission
    from spotbot.state import Book, Position, apply_buy_progress, record_buy

    book = Book(cash_micro=10_000_000, positions=[], realized_micro=0)
    assert record_buy(book, "BTCUSDT", 100_000_000, 1_000_000, 8_000_000, 4_000, "test", "abc", "1")
    assert book.cash_micro == 1_996_000
    assert record_buy(book, "BTCUSDT", 100_000_000, 1_000_000, 8_000_000, 4_000, "test", "abc", "1") is False
    assert record_buy(book, "BTCUSDT", 100_000_000, 1_000_000, 8_000_000, 4_000, "test", "def", "2") is False
    assert book.cash_micro == 1_996_000
    assert len(book.positions) == 1
    other = Book(
        cash_micro=20_000_000,
        positions=[Position("ETHUSDT", 1, 1, 1_000_000, 1_000_000, "old", "abc", "9")],
        realized_micro=0,
    )
    assert apply_buy_progress(other, "BTCUSDT", 100_000_000, 50_000_000, 5_000_000, 0, "recovered", "abc", "1") is False
    assert other.positions[0].symbol == "ETHUSDT"
    assert other.positions[0].base_atoms == 1_000_000
    assert other.cash_micro == 20_000_000
    assert apply_buy_progress(Book(cash_micro=20_000_000, positions=[], realized_micro=0), "BTCUSDT", 100_000_000, 50_000_000, 5_000_000, 0, "recovered", "", "1") is False
    assert usdt_commission(
        [{"orderId": "1", "commission": "0.004", "commissionAsset": "USDT"}, {"orderId": "2", "commission": "1", "commissionAsset": "USDT"}],
        "1",
    ) == 4_000
    assert order_missing("Order does not exist.") is True
    assert order_missing("HTTP 500") is False
    assert order_missing("symbol does not exist") is False
    assert order_missing("exchange code -2011: rejected") is True
    from spotbot.reconcile import order_is_ours

    ours = {"symbol": "BTCUSDT", "side": "BUY", "type": "MARKET", "clientOrderId": "abc"}
    assert order_is_ours(ours, "BTCUSDT", "BUY", "abc") is True
    assert order_is_ours(ours, "ETHUSDT", "BUY", "abc") is False
    assert order_is_ours(ours, "BTCUSDT", "SELL", "abc") is False
    assert order_is_ours({"symbol": "BTCUSDT", "side": "BUY", "type": "MARKET"}, "BTCUSDT", "BUY", "abc") is False
    limit = dict(ours)
    limit["type"] = "LIMIT"
    assert order_is_ours(limit, "BTCUSDT", "BUY", "abc") is False
    from spotbot.engine import _over_request
    from spotbot.state import Book, remember_pending

    book = Book(cash_micro=1, positions=[], realized_micro=0)
    remember_pending(book, "abc", "BTCUSDT", "BUY", 0, 5_000_000)
    assert _over_request(book, 1, 5_000_000) is None
    assert _over_request(book, 1, 5_000_001) == "pending buy filled more quote than requested"


def test_partial_fill_moves_cash_once() -> None:
    from spotbot.state import Book, Position, apply_buy_progress, apply_sell_progress, remember_pending

    book = Book(cash_micro=20_000_000, positions=[], realized_micro=0)
    remember_pending(book, "abc", "BTCUSDT", "BUY", 0, 10_000_000)
    assert apply_buy_progress(book, "BTCUSDT", 100_000_000, 50_000_000, 5_000_000, 2_500, "recovered", "abc", "1")
    assert apply_buy_progress(book, "BTCUSDT", 100_000_000, 50_000_000, 5_000_000, 2_500, "recovered", "abc", "1")
    assert book.cash_micro == 14_997_500
    assert apply_buy_progress(book, "BTCUSDT", 100_000_000, 100_000_000, 10_000_000, 5_000, "recovered", "abc", "1")
    assert book.positions[0].base_atoms == 100_000_000
    assert book.cash_micro == 9_995_000
    assert book.fees_micro == 5_000
    assert book.pending_client_id == "abc"
    gone = Book(cash_micro=book.cash_micro, positions=[], realized_micro=0)
    remember_pending(gone, "abc", "BTCUSDT", "BUY", 0, 10_000_000)
    gone.pending_applied_atoms = book.pending_applied_atoms
    gone.pending_applied_quote = book.pending_applied_quote
    gone.pending_applied_fee = book.pending_applied_fee
    assert apply_buy_progress(gone, "BTCUSDT", 100_000_000, 100_000_000, 10_000_000, 5_000, "recovered", "abc", "1") is False
    assert gone.cash_micro == book.cash_micro
    assert gone.positions == []
    book.positions[0].base_atoms -= 1
    assert apply_buy_progress(book, "BTCUSDT", 100_000_000, 100_000_000, 10_000_000, 5_000, "recovered", "abc", "1") is False
    assert book.cash_micro == 9_995_000
    book.positions[0].base_atoms += 1
    book.positions[0].quote_micro -= 1
    assert apply_buy_progress(book, "BTCUSDT", 100_000_000, 100_000_000, 10_000_000, 5_000, "recovered", "abc", "1") is False
    assert book.cash_micro == 9_995_000
    book.positions[0].quote_micro += 1
    book.positions[0].entry_micro += 1
    assert apply_buy_progress(book, "BTCUSDT", 100_000_000, 100_000_000, 10_000_000, 5_000, "recovered", "abc", "1") is False
    assert book.cash_micro == 9_995_000

    sold = Book(
        cash_micro=0,
        positions=[Position("BTCUSDT", 100_000_000, 100_000_000, 10_000_000, 100_000_000, "test", "buy1", "9")],
        realized_micro=0,
        pending_client_id="sell1",
        pending_symbol="BTCUSDT",
        pending_side="SELL",
        pending_base_atoms=100_000_000,
    )
    assert apply_sell_progress(sold, "BTCUSDT", 50_000_000, 6_000_000, 0)
    assert apply_sell_progress(sold, "BTCUSDT", 50_000_000, 6_000_000, 0)
    assert sold.cash_micro == 6_000_000
    assert sold.positions[0].base_atoms == 50_000_000
    assert apply_sell_progress(sold, "BTCUSDT", 100_000_000, 11_000_000, 1_000)
    assert sold.cash_micro == 10_999_000
    assert sold.fees_micro == 1_000
    assert sold.positions == []

    late = Book(cash_micro=20_000_000, positions=[], realized_micro=0)
    remember_pending(late, "late", "BTCUSDT", "BUY", 0, 5_000_000)
    assert apply_buy_progress(late, "BTCUSDT", 100_000_000, 50_000_000, 5_000_000, 0, "recovered", "late", "1")
    assert apply_buy_progress(late, "BTCUSDT", 100_000_000, 50_000_000, 5_000_000, 1_000, "recovered", "late", "1")
    assert late.cash_micro == 14_999_000
    assert late.fees_micro == 1_000
    assert apply_buy_progress(late, "BTCUSDT", 100_000_000, 50_000_000, 5_000_000, 500, "recovered", "late", "1") is False
    assert late.cash_micro == 14_999_000
    assert apply_sell_progress(sold, "BTCUSDT", 100_000_000, 11_000_000, 2_000)
    assert sold.cash_micro == 10_998_000
    assert sold.fees_micro == 2_000
    assert apply_sell_progress(sold, "BTCUSDT", 100_000_000, 11_000_000, 1_000) is False
    assert sold.cash_micro == 10_998_000

    peaked = Book(cash_micro=20_000_000, positions=[], realized_micro=0)
    remember_pending(peaked, "peak", "BTCUSDT", "BUY", 0, 7_500_000)
    assert apply_buy_progress(peaked, "BTCUSDT", 200_000_000, 25_000_000, 5_000_000, 0, "recovered", "peak", "1")
    assert apply_buy_progress(peaked, "BTCUSDT", 100_000_000, 50_000_000, 5_000_000, 0, "recovered", "peak", "1")
    assert peaked.positions[0].entry_micro == 10_000_000_000_000
    assert peaked.positions[0].peak_micro == 10_000_000_000_000
    peaked.positions[0].peak_micro = 250_000_000_000_000
    assert apply_buy_progress(peaked, "BTCUSDT", 100_000_000, 75_000_000, 7_500_000, 0, "recovered", "peak", "1")
    assert peaked.positions[0].peak_micro == 250_000_000_000_000


def test_live_partial_sell_keeps_the_rest(tmp_path, monkeypatch) -> None:
    from spotbot.config import Config
    from spotbot.engine import _close_positions
    from spotbot.mexc import OrderFill
    from spotbot.rules import SymbolRule
    from spotbot.state import Book, Position

    monkeypatch.setattr("spotbot.engine.venue_quotes", lambda _symbol: {})

    class _Client:
        def symbol_rule(self, symbol: str) -> SymbolRule:
            return SymbolRule(symbol, True, "", 5, 1_000_000, 1_000_000, 0, "BTC")

        def price(self, _symbol: str) -> int:
            return 60_000_000

        def book_top(self, symbol: str) -> tuple[int, int]:
            mark = self.price(symbol)
            return mark, mark

        def spot_balances(self) -> tuple[int, int, dict[str, int], dict[str, int]]:
            return 0, 0, {"BTC": 100_000_000}, {"BTC": 100_000_000}

        def market_sell_base(self, symbol: str, base_atoms: int, client_order_id: str) -> OrderFill:
            assert symbol == "BTCUSDT"
            assert base_atoms == 100_000_000
            return OrderFill(90_000_000, 5_000_000, 0, client_order_id, "9")

        def my_trades(self, _symbol: str, order_id: str = "") -> list[object]:
            assert order_id == "9"
            return [{
                "id": "9",
                "orderId": "9",
                "symbol": "BTCUSDT",
                "qty": "0.9",
                "quoteQty": "5",
                "price": "5.555555",
                "commission": "0",
                "commissionAsset": "USDT",
                "isBuyer": False,
            }]

    cfg = Config(
        symbols=("BTCUSDT",),
        paper_cash_micro=0,
        interval_sec=60,
        max_positions=1,
        alloc_bps=10_000,
        min_notional_micro=3_000_000,
        rsi_buy=35,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        live=True,
        mode="rsi",
        taker_bps=5,
        daily_loss_bps=500,
        stop_cooldown_sec=0,
        symbol_lock=True,
        api_key="",
        api_secret="",
    )
    book = Book(
        cash_micro=0,
        positions=[Position("BTCUSDT", 100_000_000, 100_000_000, 10_000_000, 100_000_000, "test")],
        realized_micro=0,
    )
    closed, _marks, unmarked = _close_positions(cfg, _Client(), book, tmp_path / "live" / "book.json", "book", True)
    assert closed == 1
    assert unmarked == ()
    assert len(book.positions) == 1
    assert book.positions[0].base_atoms == 10_000_000
    assert book.positions[0].quote_micro == 1_000_000
    assert book.cash_micro == 5_000_000
    assert book.pending_client_id == ""

    class _SplitFee(_Client):
        def market_sell_base(self, symbol: str, base_atoms: int, client_order_id: str) -> OrderFill:
            return OrderFill(90_000_000, 4_900_000, 100_000, client_order_id, "9")

        def my_trades(self, _symbol: str, order_id: str = "") -> list[object]:
            return [{
                "id": "9",
                "orderId": "9",
                "symbol": "BTCUSDT",
                "qty": "0.9",
                "quoteQty": "5",
                "price": "5.555555",
                "commission": "0.2",
                "commissionAsset": "USDT",
                "isBuyer": False,
            }]

    split = Book(
        cash_micro=0,
        positions=[Position("BTCUSDT", 100_000_000, 100_000_000, 10_000_000, 100_000_000, "test")],
        realized_micro=0,
    )
    closed, _marks, unmarked = _close_positions(cfg, _SplitFee(), split, tmp_path / "live" / "split.json", "book", True)
    assert closed == 0
    assert unmarked == ()
    assert split.positions[0].base_atoms == 100_000_000
    assert split.cash_micro == 0
    assert split.pending_client_id != ""

    class _CoinFee(_Client):
        def market_sell_base(self, symbol: str, base_atoms: int, client_order_id: str) -> OrderFill:
            return OrderFill(90_000_000, 5_000_000, 0, client_order_id, "9", 10_000)

    coin = Book(
        cash_micro=0,
        positions=[Position("BTCUSDT", 100_000_000, 100_000_000, 10_000_000, 100_000_000, "test")],
        realized_micro=0,
    )
    closed, _marks, unmarked = _close_positions(cfg, _CoinFee(), coin, tmp_path / "live" / "coin.json", "book", True)
    assert closed == 0
    assert unmarked == ()
    assert coin.positions[0].base_atoms == 100_000_000
    assert coin.cash_micro == 0
    assert coin.pending_client_id != ""
    assert coin.pending_ack_base_fee == 10_000
    from spotbot.engine import _apply_progress

    assert _apply_progress(_Client(), coin, {"orderId": "9"}, 90_000_000, 5_000_000, 100_000_000) is False
    assert coin.positions[0].base_atoms == 100_000_000
    assert coin.cash_micro == 0


def test_pending_sell_blocks_the_other_coin(tmp_path, monkeypatch) -> None:
    from spotbot.config import Config
    from spotbot.engine import _close_positions
    from spotbot.mexc import MexcError
    from spotbot.rules import SymbolRule
    from spotbot.state import Book, Position

    monkeypatch.setattr("spotbot.engine.venue_quotes", lambda _symbol: {})
    calls: list[str] = []

    class _Client:
        def symbol_rule(self, symbol: str) -> SymbolRule:
            return SymbolRule(symbol, True, "", 5, 1, 1_000_000, 0, symbol[:-4])

        def price(self, _symbol: str) -> int:
            return 50_000_000

        def book_top(self, symbol: str) -> tuple[int, int]:
            mark = self.price(symbol)
            return mark, mark

        def spot_balances(self) -> tuple[int, int, dict[str, int], dict[str, int]]:
            return 0, 0, {}, {"BTC": 100_000_000, "ETH": 100_000_000}

        def market_sell_base(self, symbol: str, _base_atoms: int, _client_order_id: str) -> None:
            calls.append(symbol)
            raise MexcError("ack lost")

    cfg = Config(
        symbols=("BTCUSDT", "ETHUSDT"),
        paper_cash_micro=0,
        interval_sec=60,
        max_positions=1,
        alloc_bps=10_000,
        min_notional_micro=1,
        rsi_buy=35,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        live=True,
        mode="rsi",
        taker_bps=5,
        daily_loss_bps=500,
        stop_cooldown_sec=0,
        symbol_lock=True,
        api_key="",
        api_secret="",
    )
    book = Book(
        cash_micro=0,
        positions=[
            Position("BTCUSDT", 100_000_000, 100_000_000, 10_000_000, 100_000_000, "test"),
            Position("ETHUSDT", 100_000_000, 100_000_000, 10_000_000, 100_000_000, "test"),
        ],
        realized_micro=0,
    )
    closed, _marks, unmarked = _close_positions(cfg, _Client(), book, tmp_path / "live" / "book.json", "book", True)
    assert closed == 0
    assert unmarked == ()
    assert calls == ["BTCUSDT"]
    assert book.pending_symbol == "BTCUSDT"
    assert book.pending_client_id != ""
    assert len(book.positions) == 2
    from spotbot.state import LedgerError, remember_pending

    kept = book.pending_client_id
    try:
        remember_pending(book, "other", "ETHUSDT", "SELL", 1)
    except LedgerError:
        pass
    else:
        raise AssertionError("a second client id must not replace the first")
    assert book.pending_client_id == kept
    assert book.pending_symbol == "BTCUSDT"


def test_sibling_pending_blocks_this_book(tmp_path, monkeypatch) -> None:
    from spotbot.config import Config
    from spotbot.engine import run_cycle, sibling_pending
    from spotbot.mexc import MexcError
    from spotbot.rules import SymbolRule
    from spotbot.state import Book, Position, remember_pending, save_book

    monkeypatch.setattr("spotbot.engine.venue_quotes", lambda _symbol: {})
    sibling = tmp_path / "sleeve_major.json"
    other = Book(cash_micro=0, positions=[], realized_micro=0, ledger="live")
    remember_pending(other, "major-buy", "ETHUSDT", "BUY", 0, 1_000_000)
    save_book(sibling, other)
    assert sibling_pending((sibling,)) == "sleeve_major pending ETHUSDT"

    path = tmp_path / "sleeve_alt.json"
    held = Book(
        cash_micro=0,
        positions=[Position("BTCUSDT", 100_000_000, 100_000_000, 10_000_000, 100_000_000, "test")],
        realized_micro=0,
        ledger="live",
    )
    save_book(path, held)

    class _Client:
        def forget_rules(self) -> None:
            return None

        def symbol_rule(self, symbol: str) -> SymbolRule:
            return SymbolRule(symbol, True, "", 5, 1, 1_000_000, 0, symbol[:-4])

        def server_time_ms(self) -> int:
            raise MexcError("time unread")

        def price(self, _symbol: str) -> int:
            return 50_000_000

        def book_top(self, symbol: str) -> tuple[int, int]:
            mark = self.price(symbol)
            return mark, mark

        def spot_balances(self) -> tuple[int, int, dict[str, int], dict[str, int]]:
            return 0, 0, {"BTC": 100_000_000}, {"BTC": 100_000_000}

        def market_sell_base(self, symbol: str, _base: int, _client: str) -> None:
            raise AssertionError(f"sell sent while a sibling order is open: {symbol}")

    cfg = Config(
        symbols=("BTCUSDT",),
        paper_cash_micro=0,
        interval_sec=60,
        max_positions=1,
        alloc_bps=10_000,
        min_notional_micro=1,
        rsi_buy=35,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        live=True,
        mode="rsi",
        taker_bps=5,
        daily_loss_bps=500,
        stop_cooldown_sec=0,
        symbol_lock=True,
        api_key="",
        api_secret="",
    )
    run_cycle(cfg, _Client(), path, book_name="alt", sibling_paths=(sibling,))
    kept = load_book(path, 0)
    assert kept.pending_client_id == ""
    assert len(kept.positions) == 1
    assert kept.positions[0].base_atoms == 100_000_000


def test_unresolved_order_blocks_the_next_buy() -> None:
    from pathlib import Path

    from spotbot.config import Config
    from spotbot.engine import _apply_progress, _try_buy
    from spotbot.mexc import MexcError
    from spotbot.state import Book, remember_pending

    book = Book(cash_micro=20_000_000, positions=[], realized_micro=0)
    remember_pending(book, "keep-me", "BTCUSDT", "BUY", 0)
    cfg = Config(
        symbols=("ETHUSDT",),
        paper_cash_micro=20_000_000,
        interval_sec=60,
        max_positions=1,
        alloc_bps=10_000,
        min_notional_micro=1_000_000,
        rsi_buy=35,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        live=True,
        mode="rsi",
        taker_bps=5,
        daily_loss_bps=500,
        stop_cooldown_sec=0,
        symbol_lock=True,
        api_key="",
        api_secret="",
    )

    class _Boom:
        def symbol_rule(self, _symbol: str) -> None:
            raise AssertionError("a second order must not start")

    assert _try_buy(cfg, _Boom(), book, Path("book.json"), "book", "ETHUSDT", 1, "test", 10**12) is False
    assert book.pending_client_id == "keep-me"

    class _FeeDown:
        def my_trades(self, _symbol: str, order_id: str = "") -> list[object]:
            raise MexcError("trades unread")

    assert _apply_progress(_FeeDown(), book, {"orderId": "9"}, 50_000_000, 5_000_000, 100_000_000) is False
    assert book.positions == []
    assert book.cash_micro == 20_000_000
    assert book.pending_client_id == "keep-me"


def test_base_fee_is_not_kept_as_coins() -> None:
    from spotbot.reconcile import FeeAssetError, split_commission
    from spotbot.state import Book, apply_buy_progress, remember_pending

    usdt, base, traded_base, traded_quote = split_commission(
        [{
            "id": "1",
            "orderId": "1",
            "symbol": "BTCUSDT",
            "qty": "0.5",
            "quoteQty": "5",
            "price": "10",
            "commission": "0.0001",
            "commissionAsset": "BTC",
            "isBuyer": True,
        }],
        "1",
        "BTC",
        "BUY",
    )
    assert usdt == 0
    assert base == 10_000
    assert traded_base == 50_000_000
    assert traded_quote == 5_000_000
    try:
        split_commission(
            [{
                "id": "1",
                "orderId": "1",
                "qty": "0.5",
                "quoteQty": "5",
                "price": "10",
                "commission": "1",
                "commissionAsset": "MX",
                "isBuyer": True,
            }],
            "1",
            "BTC",
            "BUY",
        )
    except FeeAssetError:
        pass
    else:
        raise AssertionError("a third-asset fee must not be priced as zero")

    book = Book(cash_micro=20_000_000, positions=[], realized_micro=0)
    remember_pending(book, "abc", "BTCUSDT", "BUY", 0, 5_000_000)
    assert apply_buy_progress(
        book, "BTCUSDT", 100_000_000, 50_000_000, 5_000_000, 0, "recovered", "abc", "1", 10_000
    )
    assert book.positions[0].base_atoms == 49_990_000
    assert apply_buy_progress(
        book, "BTCUSDT", 100_000_000, 50_000_000, 5_000_000, 0, "recovered", "abc", "1", 10_000
    )
    assert book.positions[0].base_atoms == 49_990_000
    assert book.cash_micro == 15_000_000
    assert apply_buy_progress(
        book, "BTCUSDT", 100_000_000, 50_000_000, 5_000_000, 0, "recovered", "abc", "1", 20_000
    )
    assert book.positions[0].base_atoms == 49_980_000
    assert book.cash_micro == 15_000_000
    assert apply_buy_progress(
        book, "BTCUSDT", 100_000_000, 50_000_000, 5_000_000, 0, "recovered", "abc", "1", 10_000
    ) is False
    assert book.positions[0].base_atoms == 49_980_000

    class _BaseFee:
        def my_trades(self, _symbol: str, order_id: str = "") -> list[object]:
            return [{
                "id": "1",
                "orderId": "1",
                "symbol": "BTCUSDT",
                "qty": "0.5",
                "quoteQty": "5",
                "price": "10",
                "commission": "0.0001",
                "commissionAsset": "BTC",
                "isBuyer": True,
            }]

    from spotbot.engine import _apply_progress

    fresh = Book(cash_micro=20_000_000, positions=[], realized_micro=0)
    remember_pending(fresh, "abc", "BTCUSDT", "BUY", 0, 5_000_000)
    assert _apply_progress(_BaseFee(), fresh, {"orderId": "1"}, 50_000_000, 5_000_000, 10_000_000)
    net = 50_000_000 - 10_000
    assert fresh.positions[0].base_atoms == net
    assert fresh.positions[0].entry_micro == 5_000_000 * 1_000_000 * 100_000_000 // net
    assert fresh.positions[0].entry_micro > 10_000_000_000_000


def test_paper_sell_stays_when_rules_are_down(tmp_path, monkeypatch) -> None:
    from spotbot.config import Config
    from spotbot.engine import _close_positions
    from spotbot.mexc import MexcError
    from spotbot.state import Book, Position

    monkeypatch.setattr("spotbot.engine.venue_quotes", lambda _symbol: {})

    class _Client:
        def symbol_rule(self, _symbol: str) -> None:
            raise MexcError("exchangeInfo down")

        def price(self, _symbol: str) -> int:
            return 60_000_000

        def book_top(self, symbol: str) -> tuple[int, int]:
            mark = self.price(symbol)
            return mark, mark

    cfg = Config(
        symbols=("BTCUSDT",),
        paper_cash_micro=0,
        interval_sec=60,
        max_positions=1,
        alloc_bps=10_000,
        min_notional_micro=3_000_000,
        rsi_buy=35,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        live=False,
        mode="rsi",
        taker_bps=5,
        daily_loss_bps=500,
        stop_cooldown_sec=0,
        symbol_lock=True,
        api_key="",
        api_secret="",
    )
    book = Book(
        cash_micro=0,
        positions=[Position("BTCUSDT", 100_000_000, 100_000_000, 10_000_000, 100_000_000, "test")],
        realized_micro=0,
    )
    closed, _marks, unmarked = _close_positions(cfg, _Client(), book, tmp_path / "paper" / "book.json", "book", True)
    assert closed == 0
    assert unmarked == ()
    assert book.positions[0].base_atoms == 100_000_000
    assert book.cash_micro == 0


def test_bad_market_number_stays_an_exchange_error() -> None:
    from spotbot.mexc import MexcClient, MexcError, _filled_quote
    from spotbot.reconcile import FeeAssetError, split_commission

    client = MexcClient("", "")
    client._public = lambda _path, _params: [
        [0, "1", "1", "1", "1", "1", 0, "1"],
        [0, "nope", "1", "1", "1", "1", 0, "1"],
    ]
    try:
        client.ohlcv("BTCUSDT")
    except MexcError as exc:
        assert "bad kline" in str(exc)
    else:
        raise AssertionError("a bad candle must not escape as a raw number error")
    try:
        _filled_quote({"cummulativeQuoteQty": "nope"}, "buy")
    except MexcError:
        pass
    else:
        raise AssertionError("a bad fill quote must stay an exchange error")
    try:
        split_commission(
            [{
                "id": "1",
                "orderId": "1",
                "qty": "0.5",
                "quoteQty": "5",
                "price": "10",
                "commission": "nope",
                "commissionAsset": "USDT",
                "isBuyer": True,
            }],
            "1",
            "BTC",
            "BUY",
        )
    except FeeAssetError:
        pass
    else:
        raise AssertionError("a bad commission must not escape")


def test_sell_remainder_stays_until_the_fill_is_honest(tmp_path) -> None:
    from spotbot.engine import _apply_progress, _resolve_pending
    from spotbot.reconcile import FeeAssetError, split_commission
    from spotbot.state import (
        Book,
        LedgerError,
        Position,
        apply_buy_progress,
        apply_sell_progress,
        record_buy,
        remember_pending,
        save_book,
    )

    held = Book(
        cash_micro=0,
        positions=[Position("BTCUSDT", 100_000_000, 100_000_000, 10_000_000, 100_000_000, "test", "buy1", "9")],
        realized_micro=0,
    )
    remember_pending(held, "sell1", "BTCUSDT", "SELL", 100_000_000)
    held.pending_open_base = 100_000_000
    held.pending_open_quote = 10_000_000
    assert apply_sell_progress(held, "BTCUSDT", 50_000_000, 5_000_000, 0)
    assert held.positions[0].base_atoms == 50_000_000
    held.positions.clear()
    assert apply_sell_progress(held, "BTCUSDT", 50_000_000, 5_000_000, 0) is False
    assert held.pending_client_id == "sell1"
    assert held.cash_micro == 5_000_000
    held.positions.append(Position("BTCUSDT", 100_000_000, 100_000_000, 5_000_000, 40_000_000, "test", "buy1", "9"))
    assert apply_sell_progress(held, "BTCUSDT", 100_000_000, 10_000_000, 0) is False
    assert held.pending_applied_atoms == 50_000_000
    held.positions[0].base_atoms = 50_000_000
    assert apply_sell_progress(held, "BTCUSDT", 100_000_000, 10_000_000, 0)
    assert held.positions == []
    assert apply_sell_progress(held, "BTCUSDT", 100_000_000, 10_000_000, 0)

    path = tmp_path / "book.json"
    broken = Book(cash_micro=0, positions=[], realized_micro=0)
    remember_pending(broken, "sell1", "BTCUSDT", "SELL", 100_000_000)
    broken.pending_open_base = 100_000_000
    broken.pending_applied_atoms = 50_000_000
    try:
        save_book(path, broken)
    except LedgerError:
        pass
    else:
        raise AssertionError("a missing sell remainder must not be written")
    assert not path.exists()
    path.write_text('{"cash_micro": -1, "positions": []}', encoding="utf-8")
    try:
        save_book(path, Book(cash_micro=-1, positions=[], realized_micro=0))
    except LedgerError:
        pass
    else:
        raise AssertionError("a negative cash book must not replace the file")
    assert path.read_text(encoding="utf-8").startswith('{"cash_micro": -1')

    peaked = Book(cash_micro=20_000_000, positions=[], realized_micro=0)
    remember_pending(peaked, "peak", "BTCUSDT", "BUY", 0, 5_000_000)
    assert apply_buy_progress(peaked, "BTCUSDT", 100_000_000, 50_000_000, 5_000_000, 0, "recovered", "peak", "1")
    peaked.positions[0].peak_micro = peaked.positions[0].entry_micro - 1
    assert apply_buy_progress(peaked, "BTCUSDT", 100_000_000, 50_000_000, 5_000_000, 0, "recovered", "peak", "1") is False
    try:
        remember_pending(Book(cash_micro=1, positions=[], realized_micro=0), "bad id", "BTCUSDT", "BUY", 0)
    except LedgerError:
        pass
    else:
        raise AssertionError("a client id with a space must be refused")
    over = Book(cash_micro=1, positions=[], realized_micro=0)
    remember_pending(over, "abc", "BTCUSDT", "BUY", 0, 5_000)
    over.pending_applied_quote = 1_000
    over.pending_applied_fee = 2_000
    fee_path = tmp_path / "fee.json"
    fee_path.write_text(__import__("json").dumps(over.to_json()), encoding="utf-8")
    try:
        from spotbot.state import load_book

        load_book(fee_path, 0)
    except LedgerError:
        pass
    else:
        raise AssertionError("a fee above the fill must not open")
    try:
        split_commission(
            [{
                "id": "1",
                "orderId": "1",
                "qty": "0.5",
                "quoteQty": "5",
                "commission": "0",
                "commissionAsset": "USDT",
                "isBuyer": True,
            }],
            "1",
            "BTC",
            "BUY",
        )
    except FeeAssetError:
        pass
    else:
        raise AssertionError("a trade row without a price must not close a fee")

    stuck = Book(cash_micro=0, positions=[], realized_micro=0)
    remember_pending(stuck, "sell1", "BTCUSDT", "SELL", 50_000_000)
    stuck.pending_open_base = 100_000_000

    class _Match:
        def order_by_client(self, _symbol: str, _client_id: str) -> dict[str, str]:
            return {
                "symbol": "BTCUSDT",
                "side": "SELL",
                "type": "MARKET",
                "clientOrderId": "sell1",
                "orderId": "9",
                "status": "FILLED",
                "executedQty": "0.5",
                "cummulativeQuoteQty": "5",
            }

        def my_trades(self, _symbol: str, order_id: str = "") -> list[object]:
            assert order_id == "9"
            return [{
                "id": "1",
                "orderId": "9",
                "symbol": "BTCUSDT",
                "qty": "0.5",
                "quoteQty": "5",
                "price": "10",
                "commission": "0",
                "commissionAsset": "USDT",
                "isBuyer": False,
            }]

    assert _resolve_pending(_Match(), stuck, path) == "pending fill was not recorded"
    assert stuck.pending_client_id == "sell1"
    assert _apply_progress(_Match(), stuck, {"orderId": "abc"}, 50_000_000, 5_000_000, 10_000_000) is False
    assert stuck.pending_client_id == "sell1"

    capped = Book(cash_micro=20_000_000, positions=[], realized_micro=0)
    remember_pending(capped, "abc", "BTCUSDT", "BUY", 0, 5_000_000)
    assert apply_buy_progress(capped, "ETHUSDT", 100_000_000, 50_000_000, 5_000_000, 0, "recovered", "abc", "1") is False
    assert apply_buy_progress(capped, "BTCUSDT", 100_000_000, 50_000_000, 5_000_000, 0, "recovered", "other", "1") is False
    assert apply_buy_progress(capped, "BTCUSDT", 100_000_000, 50_000_000, 5_000_001, 0, "recovered", "abc", "1") is False
    assert apply_buy_progress(capped, "BTCUSDT", 100_000_000, 50_000_000, 5_000_000, 0, "recovered", "abc", "nope") is False
    assert capped.cash_micro == 20_000_000
    assert record_buy(capped, "BTCUSDT", 100_000_000, 1, 1, 0, "test", "abc", "e1") is False
    wide = Book(
        cash_micro=0,
        positions=[
            Position("BTCUSDT", 100_000_000, 100_000_000, 10_000_000, 100_000_000, "test", "buy1", "9"),
            Position("ETHUSDT", 100_000_000, 100_000_000, 10_000_000, 100_000_000, "test", "eth1", "8"),
        ],
        realized_micro=0,
    )
    remember_pending(wide, "sell1", "BTCUSDT", "SELL", 50_000_000)
    wide.pending_open_base = 100_000_000
    assert apply_sell_progress(wide, "ETHUSDT", 50_000_000, 5_000_000, 0) is False
    assert apply_sell_progress(wide, "BTCUSDT", 60_000_000, 5_000_000, 0) is False
    assert apply_sell_progress(wide, "BTCUSDT", 50_000_000, 5_000_000, 6_000_000) is False
    assert wide.positions[1].base_atoms == 100_000_000
    assert wide.cash_micro == 0
    bare = Book(cash_micro=1, positions=[], realized_micro=0)
    remember_pending(bare, "sell1", "BTCUSDT", "SELL", 1)
    bare.pending_base_atoms = 0
    bare_path = tmp_path / "bare.json"
    bare_path.write_text(__import__("json").dumps(bare.to_json()), encoding="utf-8")
    try:
        from spotbot.state import load_book

        load_book(bare_path, 0)
    except LedgerError:
        pass
    else:
        raise AssertionError("a sell with no size must not open")
    try:
        split_commission(
            [{
                "id": "x",
                "orderId": "1",
                "qty": "0.5",
                "quoteQty": "5",
                "price": "10",
                "commission": "0",
                "commissionAsset": "USDT",
                "isBuyer": True,
            }],
            "1",
            "BTC",
            "BUY",
        )
    except FeeAssetError:
        pass
    else:
        raise AssertionError("a trade id that is not digits must not close a fee")
    named = Book(cash_micro=20_000_000, positions=[], realized_micro=0)
    remember_pending(named, "abc", "BTCUSDT", "BUY", 0, 5_000_000)
    named.pending_exchange_order_id = "9"
    assert apply_buy_progress(named, "BTCUSDT", 0, 50_000_000, 5_000_000, 0, "recovered", "abc", "1") is False
    assert named.cash_micro == 20_000_000
    assert apply_sell_progress(wide, "BTCUSDT", 50_000_000, 0, 0) is False
    assert wide.cash_micro == 0
    alien = tmp_path / "alien.json"
    alien.write_text(
        __import__("json").dumps({
            "cash_micro": 1,
            "positions": [],
            "pending_client_id": "abc",
            "pending_symbol": "BTCUSDT",
            "pending_side": "BUY",
            "pending_quote_micro": 1,
            "pending_exchange_order_id": "nope",
        }),
        encoding="utf-8",
    )
    try:
        from spotbot.state import load_book

        load_book(alien, 0)
    except LedgerError:
        pass
    else:
        raise AssertionError("a non-digit exchange id must not open")
    try:
        split_commission(
            [{
                "id": "1",
                "orderId": "1",
                "qty": "0.5",
                "quoteQty": "5",
                "price": "10",
                "commission": "0",
                "commissionAsset": "USDT",
                "isBuyer": True,
            }],
            "1",
            "BTC",
            "BUY",
        )
    except FeeAssetError:
        pass
    else:
        raise AssertionError("a trade row without a symbol must not close a fee")

    from spotbot.mexc import MexcError
    from spotbot.reconcile import inventory_mismatch, pending_gone
    from spotbot.sleeves import sleeve_symbols

    assert len(sleeve_symbols()) == 14
    assert len(set(sleeve_symbols())) == 14
    assert pending_gone(3, 0, False, True) is False
    assert inventory_mismatch([("BTCUSDT", 1), ("BTCUSDT", 1)], {"BTC": 2}) is not None
    stolen = Book(
        cash_micro=0,
        positions=[Position("BTCUSDT", 100_000_000, 100_000_000, 10_000_000, 100_000_000, "test", "sell1", "9")],
        realized_micro=0,
    )
    remember_pending(stolen, "sell1", "BTCUSDT", "SELL", 50_000_000)
    stolen.pending_open_base = 100_000_000
    assert apply_sell_progress(stolen, "BTCUSDT", 50_000_000, 5_000_000, 0) is False
    stolen.positions[0].client_order_id = "buy1"
    stolen.pending_exchange_order_id = "9"
    assert apply_sell_progress(stolen, "BTCUSDT", 50_000_000, 5_000_000, 0) is False
    assert stolen.positions[0].base_atoms == 100_000_000
    low = tmp_path / "low.json"
    low.write_text(
        __import__("json").dumps({
            "cash_micro": 1,
            "positions": [{
                "symbol": "BTCUSDT",
                "entry_micro": 2,
                "peak_micro": 1,
                "quote_micro": 1,
                "base_atoms": 1,
                "reason": "test",
            }],
        }),
        encoding="utf-8",
    )
    try:
        load_book(low, 0)
    except LedgerError:
        pass
    else:
        raise AssertionError("a peak below the entry must not open")

    class _Missing:
        def order_by_client(self, _symbol: str, _client_id: str) -> dict[str, str]:
            raise MexcError("Order does not exist.")

    acked = Book(cash_micro=1, positions=[], realized_micro=0)
    remember_pending(acked, "sell1", "BTCUSDT", "SELL", 50_000_000)
    acked.pending_exchange_order_id = "9"
    ack_path = tmp_path / "ack.json"
    for _ in range(3):
        _resolve_pending(_Missing(), acked, ack_path)
    assert acked.pending_client_id == "sell1"

    class _Cancel:
        def order_by_client(self, _symbol: str, _client_id: str) -> dict[str, str]:
            return {
                "symbol": "BTCUSDT",
                "side": "SELL",
                "type": "MARKET",
                "clientOrderId": "sell1",
                "orderId": "9",
                "status": "CANCELED",
                "executedQty": "0",
                "cummulativeQuoteQty": "0",
            }

    kept_fill = Book(cash_micro=1, positions=[], realized_micro=0)
    remember_pending(kept_fill, "sell1", "BTCUSDT", "SELL", 50_000_000)
    kept_fill.pending_applied_atoms = 10
    kept_fill.pending_applied_quote = 1
    assert _resolve_pending(_Cancel(), kept_fill, ack_path) == "pending fill disappeared"
    assert kept_fill.pending_client_id == "sell1"

    from spotbot.config import ConfigError, load_config
    from spotbot.engine import _try_buy

    monkeypatch = __import__("pytest").MonkeyPatch()
    try:
        monkeypatch.setenv("SPOT_SYMBOLS", "BTCUSDT,ETHUSDT")
        monkeypatch.setenv("SPOT_INTERVAL_SEC", "60")
        monkeypatch.setenv("SPOT_LIVE", "0")
        monkeypatch.setenv("SPOT_MODE", "rsi")
        monkeypatch.setenv("SPOT_TAKER_BPS", "5")
        monkeypatch.setenv("SPOT_DAILY_LOSS_BPS", "500")
        monkeypatch.setenv("SPOT_STOP_COOLDOWN_SEC", "900")
        monkeypatch.setenv("SPOT_PAPER_CASH_USDT", "1000")
        monkeypatch.setenv("SPOT_MIN_USDT", "3")
        monkeypatch.setenv("SPOT_ALLOC_BPS", "2000")
        monkeypatch.setenv("SPOT_RSI_BUY", "35")
        monkeypatch.setenv("SPOT_MAX_POSITIONS", "1")
        monkeypatch.setenv("SPOT_SYMBOLS", "BTCUSDT,BTCUSDT")
        try:
            load_config(False)
        except ConfigError as exc:
            assert "duplicate" in str(exc)
        else:
            raise AssertionError("a duplicated pair must not load")
        monkeypatch.setenv("SPOT_SYMBOLS", "BTC")
        try:
            load_config(False)
        except ConfigError as exc:
            assert "not a USDT pair" in str(exc)
        else:
            raise AssertionError("a pair that is not USDT must not load")
        monkeypatch.setenv("SPOT_SYMBOLS", "BTCUSDT")
        monkeypatch.setenv("SPOT_ALLOC_BPS", "20000")
        try:
            load_config(False)
        except ConfigError as exc:
            assert "SPOT_ALLOC_BPS" in str(exc)
        else:
            raise AssertionError("an allocation above the cash must not load")
        monkeypatch.setenv("SPOT_ALLOC_BPS", "2000")
        monkeypatch.setenv("SPOT_RSI_BUY", "0")
        try:
            load_config(False)
        except ConfigError as exc:
            assert "SPOT_RSI_BUY" in str(exc)
        else:
            raise AssertionError("an RSI of zero must not load")
        monkeypatch.setenv("SPOT_RSI_BUY", "35")
        monkeypatch.setenv("SPOT_MAX_POSITIONS", "0")
        try:
            load_config(False)
        except ConfigError as exc:
            assert "SPOT_MAX_POSITIONS" in str(exc)
        else:
            raise AssertionError("zero slots must not load")
        monkeypatch.setenv("SPOT_MAX_POSITIONS", "1")
        assert load_config(False).symbols == ("BTCUSDT",)
    finally:
        monkeypatch.undo()
    held_book = Book(
        cash_micro=20_000_000,
        positions=[Position("BTCUSDT", 100_000_000, 100_000_000, 10_000_000, 100_000_000, "test")],
        realized_micro=0,
    )
    from spotbot.config import Config

    cfg = Config(
        symbols=("BTCUSDT",),
        paper_cash_micro=20_000_000,
        interval_sec=60,
        max_positions=1,
        alloc_bps=10_000,
        min_notional_micro=1_000_000,
        rsi_buy=35,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        live=False,
        mode="rsi",
        taker_bps=5,
        daily_loss_bps=500,
        stop_cooldown_sec=900,
        symbol_lock=True,
        api_key="",
        api_secret="",
    )
    assert _try_buy(cfg, object(), held_book, tmp_path / "again.json", "book", "BTCUSDT", 100_000_000, "test", 10**12) is False
    assert _try_buy(cfg, object(), Book(cash_micro=1, positions=[], realized_micro=0), tmp_path / "out.json", "book", "ETHUSDT", 100_000_000, "test", 10**12) is False
    from spotbot.rules import budget_micro
    from spotbot.signals import entry_signal

    assert budget_micro(10_000_000, 10_000) == 10_000_000
    assert budget_micro(10_000_000, 20_000) == 0
    assert budget_micro(0, 10_000) == 0
    assert entry_signal("BTCUSDT", [0, *([100] * 19)], 35) is None
    from dataclasses import replace
    from spotbot.engine import run_cycle

    try:
        run_cycle(replace(cfg, alloc_bps=20_000), object(), tmp_path / "wide.json")
    except ConfigError as exc:
        assert "allocation" in str(exc)
    else:
        raise AssertionError("a cycle with an allocation above the cash must not start")
    assert len(held_book.positions) == 1
    frozen = tmp_path / "frozen.json"
    frozen.write_text('{"cash_micro": 1, "positions": [], "cooldown_until": 9999999999}', encoding="utf-8")
    try:
        load_book(frozen, 0)
    except LedgerError:
        pass
    else:
        raise AssertionError("a cooldown that is not a timestamp must not open")


def test_a_wild_mark_does_not_sell(tmp_path, monkeypatch) -> None:
    from spotbot.config import Config
    from spotbot.engine import _close_positions
    from spotbot.rules import SymbolRule
    from spotbot.sanity import mark_ok
    from spotbot.state import Book, Position

    monkeypatch.setattr("spotbot.engine.venue_quotes", lambda _symbol: {})
    assert mark_ok(100_000_000, 60_000_000) is True
    assert mark_ok(100_000_000, 0) is False
    assert mark_ok(100_000_000, 100_000_000 * 100) is False

    cfg = Config(
        symbols=("BTCUSDT",),
        paper_cash_micro=1_000_000,
        interval_sec=60,
        max_positions=1,
        alloc_bps=10_000,
        min_notional_micro=1,
        rsi_buy=35,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        live=False,
        mode="rsi",
        taker_bps=5,
        daily_loss_bps=500,
        stop_cooldown_sec=900,
        symbol_lock=True,
        api_key="",
        api_secret="",
    )

    class _Wild:
        def symbol_rule(self, symbol: str) -> SymbolRule:
            return SymbolRule(symbol, True, "", 5, 1, 1, 0, "BTC")

        def price(self, _symbol: str) -> int:
            return 100_000_000 * 100

        def book_top(self, symbol: str) -> tuple[int, int]:
            mark = self.price(symbol)
            return mark, mark

        def market_sell_base(self, *_args: object) -> None:
            raise AssertionError("a 100x print must not sell")

    wild = Book(
        cash_micro=0,
        positions=[Position("BTCUSDT", 100_000_000, 100_000_000, 10_000_000, 100_000_000, "test")],
        realized_micro=0,
    )
    closed, _marks, unmarked = _close_positions(cfg, _Wild(), wild, tmp_path / "wild.json", "book", True)
    assert closed == 0
    assert unmarked == ("BTCUSDT",)
    assert wild.positions[0].peak_micro == 100_000_000
    assert wild.positions[0].base_atoms == 100_000_000

    class _Dust(_Wild):
        def price(self, _symbol: str) -> int:
            return 96

    dust = Book(
        cash_micro=0,
        positions=[Position("BTCUSDT", 100, 100, 100, 1, "test")],
        realized_micro=0,
    )
    closed, _marks, unmarked = _close_positions(cfg, _Dust(), dust, tmp_path / "dust.json", "book", True)
    assert closed == 0
    assert dust.positions[0].base_atoms == 1
    assert dust.cash_micro == 0

    class _Alien(_Wild):
        def symbol_rule(self, symbol: str) -> SymbolRule:
            return SymbolRule(symbol, True, "", 5, 1, 1, 0, "ETH")

        def price(self, _symbol: str) -> int:
            return 96_000_000

    alien = Book(
        cash_micro=0,
        positions=[Position("BTCUSDT", 100_000_000, 100_000_000, 10_000_000, 100_000_000, "test")],
        realized_micro=0,
    )
    closed, _marks, unmarked = _close_positions(cfg, _Alien(), alien, tmp_path / "alien.json", "book", True)
    assert closed == 0
    assert alien.positions[0].base_atoms == 100_000_000
    assert alien.cash_micro == 0


def test_hold_and_median_and_next_bar() -> None:
    from spotbot.replay import hold_net, median_micro

    flat = [100_000_000] * 50
    held = hold_net(
        flat,
        cash_micro=1_000_000_000,
        alloc_bps=10_000,
        taker_bps=5,
        base_step_atoms=1,
        min_notional_micro=1,
    )
    assert held is not None and held < 0
    from spotbot.sanity import price_grid_ok

    assert price_grid_ok(100_000_000, 350) is True
    assert price_grid_ok(8, 350) is False
    assert median_micro([1, 4, 9]) == 4
    assert median_micro([-4, -1]) == -4
    assert median_micro([]) is None


def test_drawdown_pair_lock_and_spread(tmp_path) -> None:
    from spotbot.config import Config
    from spotbot.engine import _try_buy, run_cycle
    from spotbot.guards import drawdown_blocks, note_pair_stop, pair_locked, spread_blocks, top_spread_bps
    from spotbot.rules import SymbolRule
    from spotbot.state import Book, save_book

    assert drawdown_blocks(1_000_000, 900_000, 1_000) is True
    assert drawdown_blocks(1_000_000, 901_000, 1_000) is False
    assert top_spread_bps(100_000_000, 100_300_000) == 30
    assert spread_blocks(30, 30) is False
    assert spread_blocks(31, 30) is True

    book = Book(cash_micro=20_000_000, positions=[], realized_micro=0)
    note_pair_stop(book, "BTCUSDT", 1_000, 3, 100)
    note_pair_stop(book, "BTCUSDT", 1_001, 3, 100)
    assert pair_locked(book, "BTCUSDT", 1_001) is False
    note_pair_stop(book, "BTCUSDT", 1_002, 3, 100)
    assert pair_locked(book, "BTCUSDT", 1_002) is True
    assert pair_locked(book, "ETHUSDT", 1_002) is False
    book.pair_lock_until = {"BTCUSDT": 4_000_000_000}
    cfg = Config(
        symbols=("BTCUSDT",),
        paper_cash_micro=20_000_000,
        interval_sec=60,
        max_positions=1,
        alloc_bps=10_000,
        min_notional_micro=1_000_000,
        rsi_buy=35,
        stop_bps=350,
        take_bps=700,
        trail_arm_bps=300,
        trail_gap_bps=200,
        live=False,
        mode="rsi",
        taker_bps=5,
        daily_loss_bps=500,
        stop_cooldown_sec=900,
        symbol_lock=True,
        api_key="",
        api_secret="",
    )
    assert _try_buy(cfg, object(), book, tmp_path / "lock.json", "book", "BTCUSDT", 100_000_000, "test", 10**12) is False
    assert book.positions == []
    dust = Book(cash_micro=20_000_000, positions=[], realized_micro=0)
    assert _try_buy(cfg, object(), dust, tmp_path / "dust.json", "book", "BTCUSDT", 8, "test", 10**12) is False
    assert dust.positions == []

    class _Wide:
        def symbol_rule(self, symbol: str) -> SymbolRule:
            return SymbolRule(symbol, True, "", 5, 1, 1_000_000, 0, "BTC")

        def book_top(self, _symbol: str) -> tuple[int, int]:
            return 99_690_958, 100_000_000

    wide = Book(cash_micro=20_000_000, positions=[], realized_micro=0)
    assert _try_buy(cfg, _Wide(), wide, tmp_path / "wide-book.json", "book", "BTCUSDT", 100_000_000, "test", 10**12) is False
    assert wide.positions == []

    class _Quiet:
        def forget_rules(self) -> None:
            return None

        def price(self, _symbol: str) -> int:
            raise AssertionError("a drawdown halt must not price a new entry")

    path = tmp_path / "peak.json"
    save_book(path, Book(cash_micro=800_000_000, positions=[], realized_micro=0, equity_peak_micro=1_000_000_000))
    run_cycle(cfg, _Quiet(), path)
    saved = path.read_text(encoding="utf-8")
    assert "800000000" in saved

