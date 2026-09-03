from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Tick:
    """실시간 체결 틱 데이터를 표현한다."""

    code: str
    price: int
    volume: int
    time: str


@dataclass(frozen=True)
class Candle:
    """틱 수 기반 캔들 데이터를 표현한다."""

    code: str
    open: int
    high: int
    low: int
    close: int
    volume: int
    tick_count: int
    end_time: Optional[str]


@dataclass(frozen=True)
class TradeSignal:
    """전략이 생성한 주문 신호를 표현한다."""

    code: str
    side: str
    quantity: int
    reason: str
    price: int
    tag: str = ""


@dataclass(frozen=True)
class TradeExecution:
    """체결 정보를 표현한다."""

    code: str
    side: str
    quantity: int
    price: int
    time: str
    name: str = ""
    order_no: str = ""
    order_qty: int = 0
    remaining_qty: int = 0
