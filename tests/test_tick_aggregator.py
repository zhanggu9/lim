from use_cases.tick_aggregator import TickAggregator
from domain.entities import Tick


def test_tick_aggregator_builds_candle():
    """지정한 틱 수만큼 모이면 캔들을 생성한다."""
    aggregator = TickAggregator(ticks_per_candle=3)
    ticks = [
        Tick(code="000001", price=10, volume=1, time="090000"),
        Tick(code="000001", price=12, volume=2, time="090001"),
        Tick(code="000001", price=11, volume=3, time="090002"),
    ]
    candle = None
    for t in ticks:
        candle = aggregator.update(t)
    assert candle is not None
    assert candle.open == 10
    assert candle.high == 12
    assert candle.low == 10
    assert candle.close == 11
    assert candle.volume == 6
    assert candle.tick_count == 3


def test_tick_aggregator_resets_after_candle():
    """캔들이 완성되면 다음 틱은 새 캔들로 시작한다."""
    aggregator = TickAggregator(ticks_per_candle=2)
    t1 = Tick(code="000001", price=10, volume=1, time="090000")
    t2 = Tick(code="000001", price=11, volume=1, time="090001")
    t3 = Tick(code="000001", price=9, volume=1, time="090002")

    assert aggregator.update(t1) is None
    candle = aggregator.update(t2)
    assert candle is not None
    candle2 = aggregator.update(t3)
    assert candle2 is None
