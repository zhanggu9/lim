from __future__ import annotations

import datetime


class SystemClock:
    """설정된 타임존 기준의 현재 시각을 반환한다."""

    def __init__(self, timezone: str) -> None:
        """타임존 정보를 준비한다."""
        self._timezone = timezone
        self._tz = self._get_timezone(timezone)

    def now(self) -> datetime.datetime:
        """현재 시각을 반환한다."""
        return datetime.datetime.now(self._tz)

    @staticmethod
    def _get_timezone(timezone: str):
        """타임존 객체를 생성한다."""
        try:
            from zoneinfo import ZoneInfo

            return ZoneInfo(timezone)
        except Exception:
            import pytz

            return pytz.timezone(timezone)
