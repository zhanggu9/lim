import datetime

from use_cases.daily_trade_tracker import DailyTradeTracker


class DummyClock:
    """Test clock for daily tracker."""

    def __init__(self) -> None:
        self._now = datetime.datetime(2026, 2, 10, 10, 0, 0)

    def now(self) -> datetime.datetime:
        return self._now

    def advance_days(self, days: int) -> None:
        self._now += datetime.timedelta(days=days)


def test_daily_trade_tracker_calculates_net():
    clock = DummyClock()
    tracker = DailyTradeTracker(clock, fee_rate=0.001)

    tracker.record(code="000001", side="BUY", qty=10, price=1000, avg_price=0)
    tracker.record(code="000001", side="SELL", qty=10, price=1100, avg_price=1000)

    assert tracker.buy_amount == 10000
    assert tracker.sell_amount == 11000
    assert tracker.realized_pnl == 1000
    assert tracker.fee_amount == 21
    assert tracker.net_pnl == 979
    assert round(tracker.profit_rate, 2) == 9.79


def test_daily_trade_tracker_resets_on_new_day():
    clock = DummyClock()
    tracker = DailyTradeTracker(clock, fee_rate=0.0)

    tracker.record(code="000001", side="BUY", qty=1, price=1000, avg_price=0)
    assert tracker.trade_count == 1

    clock.advance_days(1)
    tracker.record(code="000001", side="SELL", qty=1, price=1100, avg_price=1000)

    assert tracker.trade_count == 1
    assert tracker.buy_amount == 0
    assert tracker.sell_amount == 1100


def test_daily_trade_tracker_details_groups_by_first_buy_time():
    clock = DummyClock()
    tracker = DailyTradeTracker(clock, fee_rate=0.0)

    tracker.record(code="000002", side="BUY", qty=2, price=2000, name="Beta", time="101500")
    tracker.record(code="000001", side="BUY", qty=1, price=1000, name="Alpha", time="100500")
    tracker.record(code="000001", side="SELL", qty=1, price=1100, name="Alpha", time="101000")

    details = tracker.details()
    items = tracker.detail_items()

    assert "10:15:00 / Beta 평균단가 2,000원 / 매수 4,000원 / 매도 0원" in details
    assert "10:05:00 / Alpha / 매수 1,000원 / 매도 1,100원" in details
    assert "Alpha / 체결" not in details
    assert "Beta / 체결" not in details
    assert details.index("10:15:00 / Beta") < details.index("10:05:00 / Alpha")
    assert items[0]["first_buy"] == "10:15:00"
    assert items[0]["name"] == "Beta"
    assert items[1]["first_buy"] == "10:05:00"
    assert items[1]["name"] == "Alpha"


def test_daily_trade_tracker_splits_same_first_buy_time_by_symbol():
    clock = DummyClock()
    tracker = DailyTradeTracker(clock, fee_rate=0.0)

    tracker.record(code="000001", side="BUY", qty=1, price=1000, name="Alpha", time="100500")
    tracker.record(code="000002", side="BUY", qty=2, price=2000, name="Beta", time="100500")
    tracker.record(code="000002", side="SELL", qty=2, price=2100, name="Beta", time="101000")

    items = tracker.detail_items()

    assert len(items) == 2
    assert items[0]["first_buy"] == "10:05:00"
    assert items[0]["name"] == "Beta"
    assert items[0]["buy_amount"] == 4000
    assert items[0]["sell_amount"] == 4200
    assert items[0]["net_pnl"] == 200
    assert items[1]["first_buy"] == "10:05:00"
    assert items[1]["name"] == "Alpha"
    assert items[1]["buy_amount"] == 1000
    assert items[1]["sell_amount"] == 0
    assert items[1]["net_pnl"] == 0


def test_daily_trade_tracker_splits_same_symbol_by_first_buy_cycle():
    clock = DummyClock()
    tracker = DailyTradeTracker(clock, fee_rate=0.0)

    tracker.record(code="000001", side="BUY", qty=1, price=1000, name="Alpha", time="100500")
    tracker.record(code="000001", side="SELL", qty=1, price=1100, name="Alpha", time="101000")
    tracker.record(code="000001", side="BUY", qty=2, price=1200, name="Alpha", time="103000")
    tracker.record(code="000001", side="SELL", qty=2, price=1250, name="Alpha", time="104000")

    items = tracker.detail_items()

    assert len(items) == 2
    assert items[0]["first_buy"] == "10:30:00"
    assert items[0]["buy_amount"] == 2400
    assert items[0]["sell_amount"] == 2500
    assert items[1]["first_buy"] == "10:05:00"
    assert items[1]["buy_amount"] == 1000
    assert items[1]["sell_amount"] == 1100
