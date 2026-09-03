from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Optional


@dataclass
class MarketHours:
    """정규장 시간과 요일 조건을 판단한다."""

    start: str
    end: str
    timezone: str

    def __post_init__(self) -> None:
        """시작/종료 시간을 파싱한다."""
        self._start_time = self._parse_time(self.start)
        self._end_time = self._parse_time(self.end)

    def is_open(self, now: datetime.datetime) -> bool:
        """현재 시각이 정규장인지 확인한다."""
        local_now = self._to_timezone(now)
        if local_now.weekday() >= 5:
            return False
        current_time = local_now.time()
        return self._start_time <= current_time <= self._end_time

    def _to_timezone(self, now: datetime.datetime) -> datetime.datetime:
        """시각을 지정된 타임존으로 변환한다."""
        tz = self._get_timezone()
        if now.tzinfo is None:
            return now.replace(tzinfo=tz)
        return now.astimezone(tz)

    def _get_timezone(self):
        """타임존 객체를 가져온다."""
        try:
            from zoneinfo import ZoneInfo

            return ZoneInfo(self.timezone)
        except Exception:
            import pytz

            return pytz.timezone(self.timezone)

    @staticmethod
    def _parse_time(value: str) -> datetime.time:
        """HH:MM 문자열을 time 객체로 변환한다."""
        hour, minute = value.split(":")
        return datetime.time(hour=int(hour), minute=int(minute))
