import datetime

from use_cases.market_hours import MarketHours


def _seoul_time(year, month, day, hour, minute):
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("Asia/Seoul")
    except Exception:
        import pytz

        tz = pytz.timezone("Asia/Seoul")
    return datetime.datetime(year, month, day, hour, minute, tzinfo=tz)


def test_market_hours_open_and_close():
    """정규장 시간 여부를 판단한다."""
    hours = MarketHours(start="09:00", end="15:30", timezone="Asia/Seoul")
    open_time = _seoul_time(2026, 2, 9, 9, 0)
    close_time = _seoul_time(2026, 2, 9, 15, 31)

    assert hours.is_open(open_time) is True
    assert hours.is_open(close_time) is False


def test_market_hours_weekend_closed():
    """주말에는 거래하지 않는다."""
    hours = MarketHours(start="09:00", end="15:30", timezone="Asia/Seoul")
    saturday = _seoul_time(2026, 2, 7, 10, 0)

    assert hours.is_open(saturday) is False
