import datetime

from domain.indicators import RsiTracker


def test_rsi_tracker_returns_none_until_ready():
    """RSI는 기간만큼 데이터가 쌓이기 전에는 None을 반환한다."""
    tracker = RsiTracker(period=14)
    closes = list(range(1, 15))
    results = [tracker.update(c) for c in closes[:-1]]
    assert all(r is None for r in results)


def test_rsi_tracker_all_gains_results_100():
    """손실이 없으면 RSI는 100으로 수렴한다."""
    tracker = RsiTracker(period=14)
    closes = list(range(1, 16))
    rsi = None
    for c in closes:
        rsi = tracker.update(c)
    assert rsi == 100.0


def test_rsi_tracker_mixed_series():
    """상승/하락이 섞인 경우 RSI가 0~100 범위에 있어야 한다."""
    tracker = RsiTracker(period=14)
    closes = [100, 102, 101, 103, 99, 98, 101, 105, 104, 103, 107, 106, 108, 107, 109]
    rsi = None
    for c in closes:
        rsi = tracker.update(c)
    assert rsi is not None
    assert 0.0 <= rsi <= 100.0
