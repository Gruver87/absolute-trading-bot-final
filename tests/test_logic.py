from spotbot.analyzer import _score_python
from spotbot.liquidity import ask_wall_exit, lift_signal, volume_ratio_bps
from spotbot.oracle import deviation_bps
from spotbot.money import format_fixed, format_usdt, parse_micro, to_satoshi, MoneyError
from spotbot.signals import entry_signal, macd_cross, rsi


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
