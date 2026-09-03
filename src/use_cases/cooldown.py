from __future__ import annotations

import datetime
from typing import Dict, Protocol


class Clock(Protocol):
    """현재 시각을 반환하는 시계 인터페이스."""

    def now(self) -> datetime.datetime:
        """현재 시각을 반환한다."""
        raise NotImplementedError


class CooldownTracker:
    """종목별 쿨다운 시간을 관리한다."""

    def __init__(self, seconds: int, clock: Clock) -> None:
        self._seconds = seconds
        self._clock = clock
        self._last_action: Dict[str, datetime.datetime] = {}

    def allow(self, code: str) -> bool:
        """쿨다운을 통과했는지 확인한다."""
        last = self._last_action.get(code)
        if last is None:
            return True
        return (self._clock.now() - last).total_seconds() >= self._seconds

    def mark(self, code: str) -> None:
        """현재 시각으로 쿨다운 기준을 갱신한다."""
        self._last_action[code] = self._clock.now()

    def now(self) -> datetime.datetime:
        """현재 시각을 반환한다."""
        return self._clock.now()
