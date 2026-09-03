from use_cases.time_aggregator import TimeAggregator
from domain.entities import Tick


def test_time_aggregator_builds_candle_on_minute_change():
    aggregator = TimeAggregator(minutes_per_candle=1)

    tick1 = Tick(code="000001", price=100, volume=1, time="090001")
    tick2 = Tick(code="000001", price=110, volume=2, time="090030")
    tick3 = Tick(code="000001", price=105, volume=1, time="090101")

    assert aggregator.update(tick1) is None
    assert aggregator.update(tick2) is None

    candle = aggregator.update(tick3)
    assert candle is not None
    assert candle.open == 100
    assert candle.high == 110
    assert candle.low == 100
    assert candle.close == 110
    assert candle.volume == 3
    assert candle.tick_count == 2


def test_time_aggregator_respects_multi_minute_bucket():
    aggregator = TimeAggregator(minutes_per_candle=5)

    tick1 = Tick(code="000001", price=100, volume=1, time="090000")
    tick2 = Tick(code="000001", price=101, volume=1, time="090359")
    tick3 = Tick(code="000001", price=99, volume=1, time="090500")

    assert aggregator.update(tick1) is None
    assert aggregator.update(tick2) is None

    candle = aggregator.update(tick3)
    assert candle is not None
    assert candle.open == 100
    assert candle.close == 101
    assert candle.high == 101
    assert candle.low == 100


def test_time_aggregator_flush_by_clock_finalizes_without_next_tick():
    aggregator = TimeAggregator(minutes_per_candle=1)

    assert aggregator.update(Tick(code="000001", price=100, volume=1, time="090001")) is None
    assert aggregator.update(Tick(code="000001", price=103, volume=1, time="090030")) is None

    flushed = aggregator.flush_by_clock("090101")
    assert len(flushed) == 1
    candle = flushed[0]
    assert candle.code == "000001"
    assert candle.open == 100
    assert candle.high == 103
    assert candle.low == 100
    assert candle.close == 103

    # 이미 확정된 캔들은 다시 나오지 않는다.
    assert aggregator.flush_by_clock("090102") == []
