from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class RsiTracker:
    """Wilder 방식으로 RSI를 점진 계산한다."""

    period: int = 14

    def __post_init__(self) -> None:
        """초기 상태를 준비한다."""
        self._prev_close: Optional[float] = None
        self._avg_gain: Optional[float] = None
        self._avg_loss: Optional[float] = None
        self._gain_sum: float = 0.0
        self._loss_sum: float = 0.0
        self._count: int = 0

    def update(self, close: float) -> Optional[float]:
        """종가를 반영해 RSI를 계산하고 반환한다."""
        if self._prev_close is None:
            self._prev_close = close
            return None

        diff = close - self._prev_close
        gain = diff if diff > 0 else 0.0
        loss = -diff if diff < 0 else 0.0

        if self._count < self.period:
            self._gain_sum += gain
            self._loss_sum += loss
            self._count += 1
            self._prev_close = close
            if self._count < self.period:
                return None
            self._avg_gain = self._gain_sum / self.period
            self._avg_loss = self._loss_sum / self.period
            return self._calc_rsi(self._avg_gain, self._avg_loss)

        self._avg_gain = ((self._avg_gain or 0.0) * (self.period - 1) + gain) / self.period
        self._avg_loss = ((self._avg_loss or 0.0) * (self.period - 1) + loss) / self.period
        self._prev_close = close
        return self._calc_rsi(self._avg_gain, self._avg_loss)

    def preview(self, close: float) -> Optional[float]:
        """현재 상태를 변경하지 않고 주어진 종가 기준의 RSI를 계산한다."""
        if self._prev_close is None or self._avg_gain is None or self._avg_loss is None:
            return None
        
        diff = close - self._prev_close
        gain = diff if diff > 0 else 0.0
        loss = -diff if diff < 0 else 0.0
        
        avg_gain = (self._avg_gain * (self.period - 1) + gain) / self.period
        avg_loss = (self._avg_loss * (self.period - 1) + loss) / self.period
        return self._calc_rsi(avg_gain, avg_loss)

    @staticmethod
    def _calc_rsi(avg_gain: float, avg_loss: float) -> float:
        """평균 상승/하락값으로 RSI를 계산한다.
        
        Wilder 방식에 따라 avg_loss가 0이면 100을 반환한다.
        단, avg_gain과 avg_loss가 모두 매우 작은 경우(가격 정체)는 50을 반환하여
        값이 0이나 100으로 수렴(왜곡)되는 것을 방지한다.
        """
        eps = 1e-2
        if (avg_gain + avg_loss) < eps:
            return 50.0
        if avg_loss < eps:
            return 100.0
        if avg_gain < eps and avg_loss >= eps:
            return 0.0
            
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))


class AdxTracker:
    """Wilder 방식 ADX/DMI 추적기.

    update(high, low, close) 를 호출하면 (adx, di_plus, di_minus) 튜플을 반환한다.
    초기값이 채워지기 전에는 None을 반환할 수 있다.
    """

    def __init__(self, period: int = 14) -> None:
        self.period = max(1, int(period))
        self._prev_high: Optional[float] = None
        self._prev_low: Optional[float] = None
        self._prev_close: Optional[float] = None

        self._tr_sum = 0.0
        self._atr: Optional[float] = None

        self._pd_sum = 0.0
        self._nd_sum = 0.0
        self._pdm: Optional[float] = None
        self._ndm: Optional[float] = None

        self._dx_list = []
        self._adx: Optional[float] = None
        self._prev_adx: Optional[float] = None
        self._count = 0

    def update(self, high: float, low: float, close: float):
        if self._prev_high is None:
            self._prev_high = high
            self._prev_low = low
            self._prev_close = close
            return None

        # True Range
        tr = max(high - low, abs(high - (self._prev_close or close)), abs(low - (self._prev_close or close)))

        # DM (Directional Movement)
        up_move = high - (self._prev_high or high)
        down_move = (self._prev_low or low) - low
        pdm = up_move if up_move > down_move and up_move > 0 else 0.0
        ndm = down_move if down_move > up_move and down_move > 0 else 0.0

        self._count += 1

        # 초기값 기간 (count <= period): 합계 누적
        if self._count <= self.period:
            self._tr_sum += tr
            self._pd_sum += pdm
            self._nd_sum += ndm
            if self._count == self.period:
                # 초기 Wilder 스무딩: 단순 평균
                self._atr = self._tr_sum / self.period if self._tr_sum > 0 else 0.01  # avoid division by zero
                self._pdm = self._pd_sum / self.period
                self._ndm = self._nd_sum / self.period
        else:
            # Wilder 스무딩 적용 (count > period)
            self._atr = ((self._atr or 0.01) * (self.period - 1) + tr) / self.period
            self._pdm = ((self._pdm or 0.0) * (self.period - 1) + pdm) / self.period
            self._ndm = ((self._ndm or 0.0) * (self.period - 1) + ndm) / self.period

        # DI 계산 (항상 계산하되, 초기값이 완성되면 의미 있는 값이 나옴)
        di_plus = 100.0 * (self._pdm / self._atr) if self._atr and self._atr > 0 else 0.0
        di_minus = 100.0 * (self._ndm / self._atr) if self._atr and self._atr > 0 else 0.0

        # DX 계산 및 ADX 스무딩
        if (di_plus + di_minus) > 0:
            dx = 100.0 * (abs(di_plus - di_minus) / (di_plus + di_minus))
        else:
            dx = 0.0

        if self._count <= self.period:
            # 초기값 기간: DX 누적
            self._dx_list.append(dx)
            if self._count == self.period:
                # period가 완성되면 초기 ADX = DX의 평균
                self._adx = sum(self._dx_list) / len(self._dx_list)
        else:
            # count > period: Wilder 스무딩된 ADX
            self._adx = ((self._adx or 0.0) * (self.period - 1) + dx) / self.period

        # 보관값 갱신
        self._prev_high = high
        self._prev_low = low
        self._prev_close = close
        self._prev_adx = self._adx  # 현재 ADX를 이전값으로 저장

        # 항상 최신 ADX/DI 값을 반환 (초기값: ADX는 None, DI는 0)
        return (self._adx, di_plus, di_minus)

    def get_adx_trend(self) -> Optional[str]:
        """ADX 추세를 반환한다. 'rising', 'falling', or None."""
        if self._adx is None or self._prev_adx is None:
            return None
        if self._adx > self._prev_adx:
            return "rising"
        elif self._adx < self._prev_adx:
            return "falling"
        return None

    def get_atr(self) -> Optional[float]:
        """현재 Wilder ATR 값을 반환한다."""
        return self._atr


class CciTracker:
    """단순 이동평균 기반 CCI(Commodity Channel Index) 추적기."""

    def __init__(self, period: int = 20) -> None:
        self.period = max(2, int(period))
        self._typical_prices: List[float] = []

    def update(self, high: float, low: float, close: float) -> Optional[float]:
        typical_price = (float(high) + float(low) + float(close)) / 3.0
        self._typical_prices.append(typical_price)
        if len(self._typical_prices) > self.period:
            self._typical_prices.pop(0)
        if len(self._typical_prices) < self.period:
            return None

        sma = sum(self._typical_prices) / float(self.period)
        mean_dev = sum(abs(tp - sma) for tp in self._typical_prices) / float(self.period)
        if mean_dev <= 1e-9:
            return 0.0
        return (typical_price - sma) / (0.015 * mean_dev)
