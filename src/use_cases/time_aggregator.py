from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Dict, List, Optional

from domain.entities import Candle, Tick


@dataclass
class _TimeCandleState:
    """분봉 생성 중간 상태를 보관한다."""

    open: int
    high: int
    low: int
    close: int
    volume: int
    tick_count: int
    end_time: Optional[str]
    bucket: int


class TimeAggregator:
    """틱 데이터를 분봉 기준으로 묶어 캔들을 생성한다."""

    def __init__(self, minutes_per_candle: int) -> None:
        """분봉 생성에 사용할 분 단위를 설정한다."""
        self._minutes_per_candle = max(1, int(minutes_per_candle))
        self._states: Dict[str, _TimeCandleState] = {}

    def update(self, tick: Tick) -> Optional[Candle]:
        """틱 데이터를 반영하고 분봉 완성 시 반환한다."""
        bucket = self._to_bucket(tick.time)
        if bucket is None:
            return None
        state = self._states.get(tick.code)
        if state is None or state.bucket != bucket:
            candle = None
            if state is not None:
                candle = Candle(
                    code=tick.code,
                    open=state.open,
                    high=state.high,
                    low=state.low,
                    close=state.close,
                    volume=state.volume,
                    tick_count=state.tick_count,
                    end_time=state.end_time,
                )
            self._states[tick.code] = _TimeCandleState(
                open=tick.price,
                high=tick.price,
                low=tick.price,
                close=tick.price,
                volume=tick.volume,
                tick_count=1,
                end_time=tick.time,
                bucket=bucket,
            )
            return candle

        state.high = max(state.high, tick.price)
        state.low = min(state.low, tick.price)
        state.close = tick.price
        state.volume += tick.volume
        state.tick_count += 1
        state.end_time = tick.time
        return None

    def get_current_candle(self, code: str) -> Optional[Candle]:
        """현재 진행 중인 분봉을 반환한다."""
        state = self._states.get(code)
        if state is None:
            return None
        return Candle(
            code=code,
            open=state.open,
            high=state.high,
            low=state.low,
            close=state.close,
            volume=state.volume,
            tick_count=state.tick_count,
            end_time=state.end_time,
        )

    def reset(self, code: str) -> None:
        """특정 종목의 누적 상태를 초기화한다."""
        self._states.pop(code, None)

    def flush_by_clock(self, now_value) -> List[Candle]:
        """새 틱이 없어도 시계 기준으로 지난 버킷 분봉을 확정한다."""
        now_bucket = self._to_bucket_from_any(now_value)
        if now_bucket is None:
            return []
        finalized: List[Candle] = []
        remove_codes: List[str] = []
        for code, state in self._states.items():
            # 현재 진행 버킷과 동일하면 유지, 다르면 확정한다.
            if state.bucket == now_bucket:
                continue
            finalized.append(
                Candle(
                    code=code,
                    open=state.open,
                    high=state.high,
                    low=state.low,
                    close=state.close,
                    volume=state.volume,
                    tick_count=state.tick_count,
                    end_time=state.end_time,
                )
            )
            remove_codes.append(code)
        for code in remove_codes:
            self._states.pop(code, None)
        return finalized

    def _to_bucket(self, time_text: str) -> Optional[int]:
        """체결시간 문자열을 분봉 버킷으로 변환한다."""
        if not time_text:
            return None
        digits = "".join([c for c in str(time_text) if c.isdigit()])
        if not digits:
            return None
        digits = digits.zfill(6)
        try:
            hour = int(digits[0:2])
            minute = int(digits[2:4])
        except ValueError:
            return None
        total_minutes = hour * 60 + minute
        return (total_minutes // self._minutes_per_candle) * self._minutes_per_candle

    def _to_bucket_from_any(self, value) -> Optional[int]:
        """datetime/time/문자열 시간을 분봉 버킷으로 변환한다."""
        if isinstance(value, datetime.datetime):
            total_minutes = value.hour * 60 + value.minute
            return (total_minutes // self._minutes_per_candle) * self._minutes_per_candle
        if isinstance(value, datetime.time):
            total_minutes = value.hour * 60 + value.minute
            return (total_minutes // self._minutes_per_candle) * self._minutes_per_candle
        return self._to_bucket(str(value))
