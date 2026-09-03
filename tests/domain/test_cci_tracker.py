from domain.indicators import CciTracker


def test_cci_tracker_returns_positive_value_on_strong_uptrend():
    tracker = CciTracker(period=5)

    values = []
    candles = [
        (100, 99, 100),
        (102, 100, 101),
        (104, 102, 103),
        (107, 105, 106),
        (111, 108, 110),
    ]
    for high, low, close in candles:
        values.append(tracker.update(high, low, close))

    assert values[-1] is not None
    assert values[-1] > 100.0
