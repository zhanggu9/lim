from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Set


@dataclass
class Position:
    """보유 포지션 정보를 보관한다."""

    qty: int
    sellable: int
    avg_price: int


class Portfolio:
    """보유 종목과 수량을 관리한다."""

    def __init__(self) -> None:
        """포트폴리오 저장소를 초기화한다."""
        self._positions: Dict[str, Position] = {}

    def update_from_holdings(self, holdings: Dict[str, Dict[str, int]]) -> None:
        """보유 종목 조회 결과로 포지션을 갱신한다."""
        positions: Dict[str, Position] = {}
        for code, data in holdings.items():
            qty = data.get("qty", 0)
            # TR 응답에 수량 0 행이 섞여 들어오는 경우를 제외해 유령 보유가 남지 않게 한다.
            if qty <= 0:
                continue
            sellable = data.get("sellable", 0)
            if sellable <= 0:
                sellable = qty
            positions[code] = Position(
                qty=qty,
                sellable=sellable,
                avg_price=data.get("avg_price", 0),
            )
        self._positions = positions

    def update_position(self, code: str, qty: int, sellable: int, avg_price: int = 0) -> None:
        """단일 종목 포지션을 갱신한다."""
        if qty <= 0:
            self._positions.pop(code, None)
            return
        prev = self._positions.get(code)
        price = avg_price if avg_price > 0 else (prev.avg_price if prev else 0)
        self._positions[code] = Position(qty=qty, sellable=sellable, avg_price=price)

    def get_qty(self, code: str) -> int:
        """보유 수량을 반환한다."""
        position = self._positions.get(code)
        return position.qty if position else 0

    def get_sellable(self, code: str) -> int:
        """매도 가능 수량을 반환한다."""
        position = self._positions.get(code)
        return position.sellable if position else 0

    def get_avg_price(self, code: str) -> int:
        """평균 매입가를 반환한다."""
        position = self._positions.get(code)
        return position.avg_price if position else 0

    def get_codes(self) -> Set[str]:
        """보유 종목 코드 집합을 반환한다."""
        return set(self._positions.keys())

    def count(self) -> int:
        """보유 종목 수를 반환한다."""
        return len(self._positions)

    def get_positions(self) -> Dict[str, Position]:
        """전체 포지션 사본을 반환한다."""
        return dict(self._positions)
