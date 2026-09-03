from __future__ import annotations

import datetime
import queue
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class StatusSnapshot:
    """UI에 표시할 상태 정보를 담는다."""

    server_mode: str
    account_no: str
    condition_index: int
    condition_name: str
    strategy_name: str
    candle_source: str
    ticks_per_candle: int
    minutes_per_candle: int
    rsi_period: int
    condition_version: int
    strategy_version: int
    candle_version: int
    rsi_period_version: int
    buy_order_version: int
    exclude_version: int
    buy_size_mode: str
    buy_size_value: int
    excluded_codes_text: str
    excluded_items: List[dict]
    watchlist_count: int
    holding_count: int
    last_signal: str
    last_rsi: str
    last_update: datetime.datetime
    realtime_status: str
    realtime_status_level: str
    real_ingress_queue_size: int
    tick_compute_queue_size: int
    tick_compute_queue_capacity: int
    tick_drop_count: int
    tr_limit_wait_ms_1s: float
    order_limit_wait_ms_1s: float
    watchlist_names: str
    holdings_summary: str
    rsi_summary: str
    rsi_items: List[dict]
    account_summary: str
    daily_trade_details: str
    daily_trade_items: List[dict]
    condition_items: List[dict]
    strategy_items: List[dict]
    holdings_items: List[dict]
    rsi_overbought: float = 70.0
    rsi_sell_half: float = 39.0
    rsi_sell_all: float = 29.0


class StatusBus:
    """스레드 간 상태 전달을 위한 큐를 제공한다."""

    def __init__(self) -> None:
        """상태 전달용 큐를 초기화한다."""
        self._queue = queue.Queue()

    def publish(self, snapshot: StatusSnapshot) -> None:
        """상태 스냅샷을 큐에 넣는다."""
        self._queue.put(snapshot)

    def try_get(self) -> Optional[StatusSnapshot]:
        """큐에서 최신 상태 스냅샷 1건을 비차단으로 가져온다."""
        latest: Optional[StatusSnapshot] = None
        try:
            latest = self._queue.get_nowait()
        except queue.Empty:
            return None
        while True:
            try:
                latest = self._queue.get_nowait()
            except queue.Empty:
                break
        return latest
