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
    assert paid == 8_500_000
    dust = implied_price_micro(10_000_000, 10_000)
    assert dust == 100_000_000_000
    try:
        implied_price_micro(0, 1)
    except MoneyError:
        pass
    else:
        raise AssertionError("a zero quote is not a fill price")


def test_parse_micro_rounds_down() -> None:
    assert parse_micro("3") == 3_000_000
    assert parse_micro("1.0000009") == 1_000_000
    assert format_usdt(3_500_000) == "3.500000"
    assert format_fixed(3_500_000, 1_000_000) == "3.5"
    assert format_fixed(150_000_000, 100_000_000) == "1.5"
    try:
        to_satoshi(1.5)
    except MoneyError:
        pass
    else:
        raise AssertionError("float must be refused")


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
    assert deviation_bps([100_000_000, 101_000_000]) == 99
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


def test_replay_stop_is_negative_after_fees() -> None:
    # Long flat stretch, one dip under the band, then a further drop through the stop.
    closes = [100_000_000] * 45
    closes[-1] = 90_000_000
    closes += [80_000_000] * 5
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
            "orderTypes": ["LIMIT", "MARKET", "LIMIT_MAKER"],
            "tradeSideType": "1",
        }
    )
    assert floki.tradable is True
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
            "symbol": "XUSDT",
            "status": "1",
            "isSpotTradingAllowed": True,
            "quoteAsset": "USDT",
            "st": False,
            "conceptPlates": ["Assessment"],
            "takerCommission": "0.0005",
            "baseSizePrecision": "1",
            "quoteAmountPrecisionMarket": "1",
            "baseAsset": "X",
            "orderTypes": ["MARKET"],
        }
    )
    assert blocked.tradable is False
    tagged = dict(blocked.__dict__) if False else {
        "symbol": "YUSDT",
        "status": "1",
        "isSpotTradingAllowed": True,
        "quoteAsset": "USDT",
        "st": True,
        "conceptPlates": [],
        "takerCommission": "0.0005",
        "baseSizePrecision": "0",
        "quoteAmountPrecisionMarket": "1",
        "baseAsset": "Y",
        "orderTypes": ["MARKET"],
    }
    assert parse_symbol_rule(tagged).tradable is False
    no_market = dict(tagged)
    no_market["symbol"] = "ZUSDT"
    no_market["baseAsset"] = "Z"
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
        "orderTypes": ["MARKET"],
        "tradeSideType": "1",
    }
    refused = parse_symbol_rule(broken)
    assert refused.tradable is False
    assert refused.refuse_reason == "max quote is not decimal"
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


def test_paper_sell_keeps_dust_below_the_lot() -> None:
    from spotbot.fees import paper_sell
    from spotbot.rules import round_base_atoms
    from spotbot.state import Book, Position, record_sell_fill

    step = 100_000_000
    base = 150_000_000
    sell = round_base_atoms(base, step)
    credit, fee = paper_sell(sell, 10_000_000, 5)
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
    from datetime import date

    from spotbot.engine import _entries_halted
    from spotbot.state import Book

    today = date.today().isoformat()
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


def test_lift_candle_replay_loses_on_the_stop() -> None:
    from spotbot.replay import replay_lift_bars

    bars = [(100_000_000, 100_000_000, 100_000_000, 100)] * 14
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

    again = parse_account(
        {
            "balances": [
                {"asset": "BTC", "free": "0.01", "locked": "0"},
                {"asset": "BTC", "free": "0.01", "locked": "0"},
            ]
        }
    )
    assert again[2]["BTC"] == 2_000_000
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
    from spotbot.mexc import executed_fill
    from spotbot.reconcile import order_finished
    from spotbot.state import Book, Position, record_sell_fill

    assert order_finished({"status": "CANCELED"}) is True
    assert order_finished({"status": "PARTIALLY_FILLED"}) is False
    assert executed_fill({"executedQty": "0", "cummulativeQuoteQty": "0"}) is None
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
        positions=[Position("BTCUSDT", 100_000_000, 100_000_000, 10_000_000, 100_000_000, "test", "sell1", "9")],
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
    assert peaked.positions[0].entry_micro == 10_000_000
    assert peaked.positions[0].peak_micro == 10_000_000
    peaked.positions[0].peak_micro = 250_000_000
    assert apply_buy_progress(peaked, "BTCUSDT", 100_000_000, 75_000_000, 7_500_000, 0, "recovered", "peak", "1")
    assert peaked.positions[0].peak_micro == 250_000_000


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
    assert fresh.positions[0].entry_micro == 5_000_000 * 100_000_000 // net
    assert fresh.positions[0].entry_micro > 10_000_000


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
        positions=[Position("BTCUSDT", 100_000_000, 100_000_000, 10_000_000, 100_000_000, "test", "sell1", "9")],
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
    held.positions.append(Position("BTCUSDT", 100_000_000, 100_000_000, 5_000_000, 40_000_000, "test", "sell1", "9"))
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
            Position("BTCUSDT", 100_000_000, 100_000_000, 10_000_000, 100_000_000, "test", "sell1", "9"),
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
