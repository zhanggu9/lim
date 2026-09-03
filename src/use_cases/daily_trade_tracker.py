from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class _Lot:
    """매수 체결 한 건을 보관한다 (FIFO 손익 계산용)."""
    qty: int
    price: int


@dataclass
class DailyTradeStats:
    """당일 매매 집계를 보관한다."""

    date: str
    buy_amount: int = 0
    sell_amount: int = 0
    realized_pnl: int = 0
    fee_amount: int = 0
    trade_count: int = 0

    @property
    def net_pnl(self) -> int:
        """수수료를 차감한 손익을 반환한다."""
        return self.realized_pnl - self.fee_amount

    @property
    def profit_rate(self) -> float:
        """수수료 차감 손익률을 반환한다."""
        if self.buy_amount <= 0:
            return 0.0
        return self.net_pnl / self.buy_amount * 100.0


@dataclass
class _TradeCycle:
    """한 번의 최초매수 시각부터 포지션 종료까지의 매매 사이클."""

    code: str
    name: str
    first_buy: str
    stats: DailyTradeStats
    ledger: "_PositionLedger" = field(default_factory=lambda: _PositionLedger())


class _PositionLedger:
    """종목별 매수 이력을 FIFO로 관리하여 서버 없이 평균단가를 계산한다."""

    def __init__(self) -> None:
        self._lots: List[_Lot] = []  # FIFO 매수 이력
        self._held_qty: int = 0       # 현재 보유 수량
        self._held_cost: int = 0      # 현재 보유 원가 합계

    @property
    def avg_price(self) -> int:
        """현재 평균 매입단가를 반환한다."""
        if self._held_qty <= 0:
            return 0
        return int(round(self._held_cost / self._held_qty))

    def buy(self, qty: int, price: int) -> None:
        """매수 체결을 반영한다."""
        if qty <= 0 or price <= 0:
            return
        self._lots.append(_Lot(qty=qty, price=price))
        self._held_qty += qty
        self._held_cost += qty * price

    def sell(self, qty: int) -> int:
        """매도 체결을 반영하고 FIFO 기준 평균 매입단가를 반환한다.
        
        반환값은 당일 매수 이력 기반의 평균단가입니다.
        당일 매수 이력이 없으면 현재 avg_price(잔여 이력 기반)를 반환합니다.
        """
        if qty <= 0:
            return self.avg_price

        cost_basis = self.avg_price  # 기본값: 현재 전체 평균단가

        # FIFO 소진
        remaining = qty
        consumed_cost = 0
        consumed_qty = 0

        new_lots = []
        for lot in self._lots:
            if remaining <= 0:
                new_lots.append(lot)
                continue
            take = min(lot.qty, remaining)
            consumed_cost += take * lot.price
            consumed_qty += take
            remaining -= take
            if lot.qty > take:
                new_lots.append(_Lot(qty=lot.qty - take, price=lot.price))

        self._lots = new_lots

        if consumed_qty > 0:
            cost_basis = int(round(consumed_cost / consumed_qty))

        # 보유 잔량 업데이트
        sold = qty - max(0, remaining)  # 실제로 FIFO에서 소진된 수량
        self._held_qty = max(0, self._held_qty - qty)
        self._held_cost = max(0, self._held_cost - sold * cost_basis)

        if self._held_qty == 0:
            self._held_cost = 0
            self._lots = []

        return cost_basis


class DailyTradeTracker:
    """당일 매매 내역을 집계한다.

    avg_price는 서버에서 받아오지 않고, 당일 BUY 체결 이력을 직접 누적하여
    FIFO 방식으로 계산합니다. SELL 손익 계산이 서버 응답 지연과 무관하게 정확합니다.
    """

    def __init__(self, clock, fee_rate: float = 0.0) -> None:
        self._clock = clock
        self._fee_rate = float(fee_rate)
        self._stats = DailyTradeStats(date=self._today())
        self._active_cycles: Dict[str, _TradeCycle] = {}
        self._completed_cycles: List[_TradeCycle] = []

    def record(
        self,
        code: str,
        side: str,
        qty: int,
        price: int,
        avg_price: int = 0,
        name: str = "",
        time: str = "",
    ) -> None:
        """체결 정보를 집계한다.

        avg_price 인수는 무시됩니다. 손익은 내부 BUY 이력에서 직접 계산합니다.
        (하위 호환성 유지를 위해 인수 자체는 남겨둡니다)
        """
        if qty <= 0 or price <= 0:
            return
        self._reset_if_new_day()

        amount = int(price) * int(qty)
        self._stats.trade_count += 1
        fee = int(round(amount * self._fee_rate))
        self._stats.fee_amount += fee

        if side == "BUY":
            cycle = self._active_cycles.get(code)
            if cycle is None:
                cycle = _TradeCycle(
                    code=code,
                    name=name or code,
                    first_buy=self._normalize_time_str(time),
                    stats=DailyTradeStats(date=self._stats.date),
                )
                self._active_cycles[code] = cycle
            elif name:
                cycle.name = name

            cycle.stats.trade_count += 1
            cycle.stats.fee_amount += fee
            self._stats.buy_amount += amount
            cycle.stats.buy_amount += amount
            cycle.ledger.buy(qty, price)
        elif side == "SELL":
            cycle = self._active_cycles.get(code)
            if cycle is None:
                cycle = _TradeCycle(
                    code=code,
                    name=name or code,
                    first_buy=self._normalize_time_str(time),
                    stats=DailyTradeStats(date=self._stats.date),
                )
                self._active_cycles[code] = cycle
            elif name:
                cycle.name = name

            cycle.stats.trade_count += 1
            cycle.stats.fee_amount += fee
            self._stats.sell_amount += amount
            cycle.stats.sell_amount += amount
            # 서버 참조 없이 자체 FIFO 이력에서 평균단가 계산
            cost_basis = cycle.ledger.sell(qty)
            realized = (int(price) - cost_basis) * int(qty)
            self._stats.realized_pnl += realized
            cycle.stats.realized_pnl += realized
            if cycle.ledger._held_qty <= 0:
                self._completed_cycles.append(cycle)
                self._active_cycles.pop(code, None)

    def summary(self) -> str:
        """당일 매매 요약 문자열을 반환한다."""
        if self._stats.trade_count <= 0:
            return "-"
        return (
            f"체결 {self._stats.trade_count}건 / 매수 {self._stats.buy_amount:,}원 / 매도 {self._stats.sell_amount:,}원 / "
            f"실현손익 {self._stats.net_pnl:+,}원 ({self._stats.profit_rate:.2f}%)"
        )

    def details(self) -> str:
        """최초매수 시각별 당일 매매 요약 문자열을 반환한다."""
        items = self.detail_items()
        if not items:
            return "-"
        lines = []
        for item in items:
            avg = int(item.get("avg_price", 0) or 0)
            avg_str = f" 평균단가 {avg:,}원" if avg > 0 else ""
            lines.append(
                f"{item.get('first_buy', '-')} / {item.get('name', '-')}{avg_str} / 매수 {int(item.get('buy_amount', 0)):,}원 / "
                f"매도 {int(item.get('sell_amount', 0)):,}원 / "
                f"실현손익 {int(item.get('net_pnl', 0)):+,}원 ({float(item.get('profit_rate', 0.0)):.2f}%)"
            )
        return "\n".join(lines)

    def detail_items(self) -> List[dict]:
        """UI 표시에 사용할 구조화된 최초매수 시각별 당일 매매 항목을 반환한다."""
        cycles = list(self._completed_cycles) + list(self._active_cycles.values())
        if not cycles:
            return []

        def _sort_key(value: str) -> tuple:
            normalized = value if value and value != "-" else ""
            return (normalized == "", normalized)

        items: List[dict] = []
        sorted_cycles = sorted(
            cycles,
            key=lambda cycle: (_sort_key(cycle.first_buy), str(cycle.name or cycle.code), str(cycle.code)),
            reverse=True,
        )
        for cycle in sorted_cycles:
            stats = cycle.stats
            avg_price = cycle.ledger.avg_price if cycle.ledger.avg_price > 0 else 0
            profit_rate = 0.0
            if int(stats.buy_amount) > 0:
                profit_rate = (int(stats.net_pnl) / int(stats.buy_amount)) * 100.0
            items.append(
                {
                    "type": "trade_group",
                    "codes": [cycle.code],
                    "name": cycle.name or cycle.code,
                    "first_buy": cycle.first_buy,
                    "avg_price": int(avg_price),
                    "buy_amount": int(stats.buy_amount),
                    "sell_amount": int(stats.sell_amount),
                    "net_pnl": int(stats.net_pnl),
                    "fee_amount": int(stats.fee_amount),
                    "profit_rate": float(profit_rate),
                }
            )
        return items

    @property
    def buy_amount(self) -> int:
        return self._stats.buy_amount

    @property
    def sell_amount(self) -> int:
        return self._stats.sell_amount

    @property
    def realized_pnl(self) -> int:
        return self._stats.realized_pnl

    @property
    def fee_amount(self) -> int:
        return self._stats.fee_amount

    @property
    def net_pnl(self) -> int:
        return self._stats.net_pnl

    @property
    def profit_rate(self) -> float:
        return self._stats.profit_rate

    @property
    def trade_count(self) -> int:
        return self._stats.trade_count

    def _today(self) -> str:
        """현재 날짜 문자열을 반환한다."""
        return self._clock.now().strftime("%Y%m%d")

    def _reset_if_new_day(self) -> None:
        """날짜가 바뀌었으면 집계를 초기화한다."""
        today = self._today()
        if self._stats.date != today:
            self._stats = DailyTradeStats(date=today)
            self._active_cycles = {}
            self._completed_cycles = []

    def _normalize_time_str(self, value: str) -> str:
        """체결 시각 문자열을 사람이 보기 좋은 형식으로 정규화한다."""
        if value:
            digits = "".join([c for c in str(value) if c.isdigit()])
            if len(digits) >= 6:
                return f"{digits[0:2]}:{digits[2:4]}:{digits[4:6]}"
            if len(digits) == 4:
                return f"{digits[0:2]}:{digits[2:4]}:00"
        return self._clock.now().strftime("%H:%M:%S")
