from __future__ import annotations

import math


class OrderSizer:
    """매수/매도 수량을 계산한다."""

    def buy_quantity(self, cash: int, price: int) -> int:
        """매수 금액과 가격으로 수량을 내림 계산한다."""
        if price <= 0:
            return 0
        return int(math.floor(cash / price))

    def sell_quantity(self, position_qty: int, ratio: float) -> int:
        """보유 수량과 비율로 매도 수량을 내림 계산한다."""
        if position_qty <= 0:
            return 0
        return int(math.floor(position_qty * ratio))
