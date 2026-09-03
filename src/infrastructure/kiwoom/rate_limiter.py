from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, Deque, Tuple


class AsyncRateLimiter:
    """멀티스레드 환경에서 호출 빈도를 제한한다."""

    def __init__(
        self,
        max_calls: int,
        period_sec: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        """period_sec 창에서 max_calls를 넘지 않도록 제한한다."""
        self._max_calls = max(1, int(max_calls))
        self._period_sec = max(0.001, float(period_sec))
        self._clock = clock
        self._sleep = sleep_fn
        self._timestamps: Deque[float] = deque()
        self._wait_events: Deque[Tuple[float, float]] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """요청 가능 시점까지 대기 후 슬롯을 확보한다."""
        waited_total_sec = 0.0
        while True:
            wait_sec = 0.0
            with self._lock:
                now = self._clock()
                self._prune_call_timestamps(now)
                if len(self._timestamps) < self._max_calls:
                    self._timestamps.append(now)
                    if waited_total_sec > 0.0:
                        self._wait_events.append((now, waited_total_sec * 1000.0))
                        self._prune_wait_events(now, 1.0)
                    return
                oldest = self._timestamps[0]
                wait_sec = max(0.0, self._period_sec - (now - oldest))
            if wait_sec > 0.0:
                waited_total_sec += wait_sec
                self._sleep(wait_sec)

    def get_wait_ms_last_sec(self, window_sec: float = 1.0) -> float:
        """최근 window_sec 동안 누적된 대기시간(ms)을 반환한다."""
        target_window = max(0.1, float(window_sec))
        with self._lock:
            now = self._clock()
            self._prune_wait_events(now, target_window)
            return sum(wait_ms for _, wait_ms in self._wait_events)

    def _prune_call_timestamps(self, now: float) -> None:
        """호출 제한 윈도우 밖의 호출시각을 제거한다."""
        window_start = now - self._period_sec
        while self._timestamps and self._timestamps[0] <= window_start:
            self._timestamps.popleft()

    def _prune_wait_events(self, now: float, window_sec: float) -> None:
        """대기시간 통계 윈도우 밖의 이벤트를 제거한다."""
        window_start = now - window_sec
        while self._wait_events and self._wait_events[0][0] <= window_start:
            self._wait_events.popleft()
