from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Dict, List

from domain.entities import TradeSignal
from domain.indicators import AdxTracker


class _ATR:
    def __init__(self, period: int = 14):
        self.period = max(2, int(period))
        self.prev = None
        self.value = None
        self.tr = deque(maxlen=self.period)

    def update(self, high, low, close):
        high, low, close = float(high), float(low), float(close)
        if self.prev is None:
            self.prev = close
            return None
        tr = max(high - low, abs(high - self.prev), abs(low - self.prev))
        if self.value is None:
            self.tr.append(tr)
            if len(self.tr) < self.period:
                self.prev = close
                return None
            self.value = sum(self.tr) / self.period
        else:
            self.value = ((self.value * (self.period - 1)) + tr) / self.period
        self.prev = close
        return self.value


@dataclass
class TrendState:
    phase: str = "WATCH"
    entry_price: float = 0.0
    peak: float = 0.0
    last_add: float = 0.0


class TrendOrchestrator:
    """조건검색 후보를 대상으로 상승 추세 진입을 판단하는 통합 추세 엔진."""

    name = "trend_combo"
    label = "상승추세 통합 (ADX+DMI/Donchian/Livermore)"
    requires_rsi = False

    def __init__(self, settings, cooldown, order_sizer, market_hours):
        self.buy_cash = int(getattr(settings, "buy_cash", 500000))
        self.cooldown = cooldown
        self.order_sizer = order_sizer
        self.market_hours = market_hours
        self.breakout_period = max(3, int(getattr(settings, "trend_breakout_period", 10)))
        self.exit_period = max(2, int(getattr(settings, "trend_exit_period", 5)))
        self.momentum_bars = max(2, int(getattr(settings, "trend_momentum_bars", 3)))
        self.adx_period = max(2, int(getattr(settings, "trend_adx_period", 14)))
        self.adx_threshold = float(getattr(settings, "trend_adx_threshold", 20.0))
        self.atr_period = max(2, int(getattr(settings, "trend_atr_period", 14)))
        self.stop_atr = float(getattr(settings, "trend_stop_atr_mult", 1.0))
        self.trail_atr = float(getattr(settings, "trend_trailing_atr_mult", 1.5))
        self.max_chase_atr = float(getattr(settings, "trend_max_chase_atr_mult", 1.5))
        self.add_enabled = bool(getattr(settings, "trend_pyramiding_enabled", False))
        self.add_atr = float(getattr(settings, "trend_add_atr_mult", 1.2))
        self.max_adds = max(0, int(getattr(settings, "trend_max_adds", 1)))
        self.h: Dict[str, deque] = {}
        self.l: Dict[str, deque] = {}
        self.c: Dict[str, deque] = {}
        self.adx: Dict[str, AdxTracker] = {}
        self.atr: Dict[str, _ATR] = {}
        self.prev_adx: Dict[str, float] = {}
        self.state: Dict[str, TrendState] = {}
        self.add_count: Dict[str, int] = {}

    def _hist(self, code):
        size = max(100, self.breakout_period + 20)
        return (self.h.setdefault(code, deque(maxlen=size)),
                self.l.setdefault(code, deque(maxlen=size)),
                self.c.setdefault(code, deque(maxlen=size)))

    def on_rsi_update(self, code, rsi, price, position_qty, high=None, low=None) -> List[TradeSignal]:
        if not self.market_hours.is_open(self.cooldown.now()):
            return []
        high = price if high is None else high
        low = price if low is None else low
        highs, lows, closes = self._hist(code)
        highs.append(float(high)); lows.append(float(low)); closes.append(float(price))

        atr = self.atr.setdefault(code, _ATR(self.atr_period)).update(high, low, price)
        result = self.adx.setdefault(code, AdxTracker(self.adx_period)).update(float(high), float(low), float(price))
        adx = plus = minus = None
        if result is not None:
            adx, plus, minus = result

        st = self.state.setdefault(code, TrendState())
        signals: List[TradeSignal] = []

        if position_qty > 0:
            st.phase = "IN_POSITION"
            st.entry_price = st.entry_price or float(price)
            st.peak = max(st.peak or float(price), float(price))
            if atr and atr > 0:
                stop = st.entry_price - self.stop_atr * atr
                trail = st.peak - self.trail_atr * atr
                if float(price) <= stop or float(price) <= trail:
                    qty = self.order_sizer.sell_quantity(position_qty, 1.0)
                    if qty > 0:
                        signals.append(TradeSignal(code=code, side="SELL", quantity=qty, reason=f"TREND EXIT ATR stop/trail atr={atr:.2f}", price=price, tag="trend:ATR_EXIT"))
                        st.phase = "EXIT_COOLDOWN"
                        return signals
            if len(lows) >= self.exit_period and float(price) <= min(list(lows)[-self.exit_period:]):
                qty = self.order_sizer.sell_quantity(position_qty, 1.0)
                if qty > 0:
                    signals.append(TradeSignal(code=code, side="SELL", quantity=qty, reason=f"TREND EXIT Donchian {self.exit_period}", price=price, tag="trend:DONCHIAN_EXIT"))
                    st.phase = "EXIT_COOLDOWN"
                    return signals
            if adx is not None and plus is not None and minus is not None:
                if adx < self.adx_threshold * 0.75 or minus > plus:
                    qty = self.order_sizer.sell_quantity(position_qty, 1.0)
                    if qty > 0:
                        signals.append(TradeSignal(code=code, side="SELL", quantity=qty, reason=f"TREND EXIT DMI/ADX adx={adx:.1f} DI+={plus:.1f} DI-={minus:.1f}", price=price, tag="trend:DMI_EXIT"))
                        st.phase = "EXIT_COOLDOWN"
                        return signals
            if self.add_enabled and atr and atr > 0 and self.add_count.get(code, 0) < self.max_adds:
                base = st.last_add or st.entry_price
                if float(price) >= base + self.add_atr * atr and self.cooldown.allow(code):
                    qty = self.order_sizer.buy_quantity(max(0, int(self.buy_cash * 0.5)), price)
                    if qty > 0:
                        self.cooldown.mark(code)
                        self.add_count[code] = self.add_count.get(code, 0) + 1
                        st.last_add = float(price)
                        signals.append(TradeSignal(code=code, side="BUY", quantity=qty, reason=f"TREND PYRAMID add={self.add_count[code]} atr={atr:.2f}", price=price, tag=f"trend:ADD_{self.add_count[code]}"))
            return signals

        if len(closes) < max(self.breakout_period + 1, self.momentum_bars + 1) or atr is None or atr <= 0:
            st.phase = "WARMUP"
            return []

        previous_high = max(list(highs)[-(self.breakout_period + 1):-1])
        breakout = float(price) > previous_high
        momentum = all(closes[-i - 1] < closes[-i] for i in range(1, self.momentum_bars + 1))
        dmi_ok = False
        if adx is not None and plus is not None and minus is not None:
            prev = self.prev_adx.get(code)
            adx_rising = prev is not None and adx >= prev
            dmi_ok = adx >= self.adx_threshold and plus > minus and adx_rising
            self.prev_adx[code] = float(adx)

        chase_ok = float(price) <= previous_high + self.max_chase_atr * atr
        confirmation = breakout and chase_ok and (dmi_ok or momentum)
        if confirmation and self.cooldown.allow(code):
            qty = self.order_sizer.buy_quantity(self.buy_cash, price)
            if qty > 0:
                self.cooldown.mark(code)
                st.phase = "IN_POSITION"
                st.entry_price = float(price)
                st.peak = float(price)
                st.last_add = float(price)
                self.add_count[code] = 0
                reason = f"TREND ENTRY breakout({self.breakout_period}) + {'DMI/ADX' if dmi_ok else 'momentum'}"
                if adx is not None:
                    reason += f" ADX={adx:.1f} DI+={plus:.1f} DI-={minus:.1f}"
                signals.append(TradeSignal(code=code, side="BUY", quantity=qty, reason=reason, price=price, tag="trend:ENTRY"))
        else:
            st.phase = "SETUP" if breakout else "WATCH"
        return signals

    def reset_code(self, code):
        for d in (self.h, self.l, self.c, self.adx, self.atr, self.state, self.prev_adx, self.add_count):
            d.pop(code, None)
