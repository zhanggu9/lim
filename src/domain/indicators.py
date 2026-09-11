from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class RsiTracker:
    """Wilder 방식으로 RSI를 점진 계산한다."""

    period: int = 14

    def __post_init__(self) -> None:
        self._prev_close: Optional[float] = None
        self._avg_gain: Optional[float] = None
        self._avg_loss: Optional[float] = None
        self._gain_sum: float = 0.0
        self._loss_sum: float = 0.0
        self._count: int = 0

    def update(self, close: float) -> Optional[float]:
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
    """Wilder 방식 ADX/DMI 추적기."""

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

        old_adx = self._adx
        tr = max(high - low, abs(high - (self._prev_close or close)), abs(low - (self._prev_close or close)))
        up_move = high - (self._prev_high or high)
        down_move = (self._prev_low or low) - low
        pdm = up_move if up_move > down_move and up_move > 0 else 0.0
        ndm = down_move if down_move > up_move and down_move > 0 else 0.0
        self._count += 1

        if self._count <= self.period:
            self._tr_sum += tr
            self._pd_sum += pdm
            self._nd_sum += ndm
            if self._count == self.period:
                self._atr = self._tr_sum / self.period if self._tr_sum > 0 else 0.01
                self._pdm = self._pd_sum / self.period
                self._ndm = self._nd_sum / self.period
        else:
            self._atr = ((self._atr or 0.01) * (self.period - 1) + tr) / self.period
            self._pdm = ((self._pdm or 0.0) * (self.period - 1) + pdm) / self.period
            self._ndm = ((self._ndm or 0.0) * (self.period - 1) + ndm) / self.period

        di_plus = 100.0 * (self._pdm / self._atr) if self._atr and self._atr > 0 else 0.0
        di_minus = 100.0 * (self._ndm / self._atr) if self._atr and self._atr > 0 else 0.0
        if (di_plus + di_minus) > 0:
            dx = 100.0 * (abs(di_plus - di_minus) / (di_plus + di_minus))
        else:
            dx = 0.0

        if self._count <= self.period:
            self._dx_list.append(dx)
            if self._count == self.period:
                self._adx = sum(self._dx_list) / len(self._dx_list)
        else:
            self._adx = ((self._adx or 0.0) * (self.period - 1) + dx) / self.period

        self._prev_high = high
        self._prev_low = low
        self._prev_close = close
        self._prev_adx = old_adx
        return (self._adx, di_plus, di_minus)

    def get_adx_trend(self) -> Optional[str]:
        if self._adx is None or self._prev_adx is None:
            return None
        if self._adx > self._prev_adx:
            return "rising"
        if self._adx < self._prev_adx:
            return "falling"
        return None

    def get_atr(self) -> Optional[float]:
        return self._atr


class CciTracker:
    """단순 이동평균 기반 CCI 추적기."""

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
