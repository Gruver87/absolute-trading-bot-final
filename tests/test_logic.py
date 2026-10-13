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


def test_replay_stop_is_negative_after_fees() -> None:
    # Long flat stretch, one dip under the band, then a further drop through the stop.
    closes = [100_000_000] * 44
    closes += [90_000_000, 90_000_000]
    closes += [80_000_000] * 6
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

