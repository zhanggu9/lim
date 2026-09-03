from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from domain.entities import Candle, Tick


@dataclass
class _CandleState:
    """캔들 생성 중간 상태를 보관한다."""

    open: int
    high: int
    low: int
    close: int
    volume: int
    tick_count: int
    end_time: Optional[str]


class TickAggregator:
    """틱 데이터를 지정한 개수로 묶어 캔들을 생성한다."""

    def __init__(self, ticks_per_candle: int) -> None:
        """캔들을 만들기 위한 틱 개수를 설정한다."""
        self._ticks_per_candle = ticks_per_candle
        self._states: Dict[str, _CandleState] = {}

    def update(self, tick: Tick) -> Optional[Candle]:
        """틱 데이터를 반영하고 캔들 완성 시 반환한다."""
        state = self._states.get(tick.code)
        if state is None:
            state = _CandleState(
                open=tick.price,
                high=tick.price,
                low=tick.price,
                close=tick.price,
                volume=tick.volume,
                tick_count=1,
                end_time=tick.time,
            )
            self._states[tick.code] = state
        else:
            state.high = max(state.high, tick.price)
            state.low = min(state.low, tick.price)
            state.close = tick.price
            state.volume += tick.volume
            state.tick_count += 1
            state.end_time = tick.time

        if state.tick_count >= self._ticks_per_candle:
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
            self._states.pop(tick.code, None)
            return candle

        return None

    def reset(self, code: str) -> None:
        """특정 종목의 누적 상태를 초기화한다."""
        self._states.pop(code, None)

    def get_current_candle(self, code: str) -> Optional[Candle]:
        """현재 진행 중인 틱 캔들을 반환한다."""
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
