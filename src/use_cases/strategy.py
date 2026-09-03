from __future__ import annotations

from dataclasses import dataclass, field
import datetime
from typing import Dict, List, Optional

from domain.entities import TradeSignal
from domain.indicators import AdxTracker, CciTracker
from use_cases.cooldown import CooldownTracker
from use_cases.market_hours import MarketHours
from use_cases.order_sizer import OrderSizer


class _AtrTracker:
    """Wilder 방식 ATR 추적기."""

    def __init__(self, period: int = 14) -> None:
        self.period = max(1, int(period))
        self._prev_close: Optional[float] = None
        self._atr: Optional[float] = None
        self._tr_values: List[float] = []

    def update(self, high: float, low: float, close: float) -> Optional[float]:
        if self._prev_close is None:
            self._prev_close = close
            return None

        tr = max(
            high - low,
            abs(high - self._prev_close),
            abs(low - self._prev_close),
        )
        if self._atr is None:
            self._tr_values.append(float(tr))
            if len(self._tr_values) < self.period:
                self._prev_close = close
                return None
            self._atr = sum(self._tr_values) / float(self.period)
            self._tr_values = []
            self._prev_close = close
            return self._atr

        self._atr = ((self._atr * float(self.period - 1)) + float(tr)) / float(self.period)
        self._prev_close = close
        return self._atr


@dataclass
class RsiStrategy:
    """RSI 기반 매매 전략을 수행한다."""

    overbought: float
    sell_half: float
    sell_all: float
    buy_cash: int
    cooldown: CooldownTracker
    order_sizer: OrderSizer
    market_hours: MarketHours
    grid_step_percent: float = 1.3
    stage_multipliers: List[float] = field(default_factory=lambda: [1.0, 1.0, 0.8, 0.6, 0.4, 0.2])
    pyramiding_enabled: bool = True
    entry_atr_mult: float = 0.0
    add_atr_mult: float = 0.0
    atr_trailing_mult: float = 0.0
    atr_buffer_mult: float = 0.0
    atr_period: int = 14
    profit_protect_atr_mult: float = 0.0
    use_adx_filter: bool = False
    adx_period: int = 14
    adx_threshold: float = 25.0
    use_cci_filter: bool = False
    cci_period: int = 20
    cci_entry_threshold: float = 0.0
    cci_add_threshold: float = 100.0
    name: str = field(init=False, default="rsi_grid")
    label: str = field(init=False, default="RSI 그리드")
    requires_rsi: bool = field(init=False, default=True)

    def __post_init__(self) -> None:
        """RSI 이전 값을 저장할 맵을 초기화한다."""
        self.atr_period = max(2, int(self.atr_period))
        self.entry_atr_mult = max(0.0, float(self.entry_atr_mult))
        self.add_atr_mult = max(0.0, float(self.add_atr_mult))
        self.atr_trailing_mult = max(0.0, float(self.atr_trailing_mult))
        self.atr_buffer_mult = max(0.0, float(self.atr_buffer_mult))
        self.profit_protect_atr_mult = max(0.0, float(self.profit_protect_atr_mult))
        self.use_adx_filter = bool(self.use_adx_filter)
        self.adx_period = max(2, int(self.adx_period))
        self.adx_threshold = float(self.adx_threshold)
        self.use_cci_filter = bool(self.use_cci_filter)
        self.cci_period = max(2, int(self.cci_period))
        self.cci_entry_threshold = float(self.cci_entry_threshold)
        self.cci_add_threshold = float(self.cci_add_threshold)
        self.pyramiding_enabled = bool(self.pyramiding_enabled)
        self._last_rsi: Dict[str, float] = {}
        self._grid_anchor: Dict[str, float] = {}
        self._entered_overbought: Dict[str, bool] = {}
        self._last_price: Dict[str, float] = {}
        self._had_position: Dict[str, bool] = {}
        self._sell_half_fired: Dict[str, bool] = {}
        self._sell_all_fired: Dict[str, bool] = {}
        self._grid_stage: Dict[str, int] = {}
        self._atr_trackers: Dict[str, _AtrTracker] = {}
        self._peak_price: Dict[str, float] = {}
        self._entry_price: Dict[str, float] = {}
        self._adx_trackers: Dict[str, AdxTracker] = {}
        self._cci_trackers: Dict[str, CciTracker] = {}

    def on_rsi_update(self, code: str, rsi: float, price: int, position_qty: int, high: int = None, low: int = None) -> List[TradeSignal]:
        """RSI 갱신 시 매수/매도 신호를 생성한다."""
        if not self.market_hours.is_open(self.cooldown.now()):
            self._last_rsi[code] = rsi
            self._last_price[code] = float(price)
            return []

        atr = None
        adx = None
        cci = None
        if high is not None and low is not None:
            tracker = self._atr_trackers.get(code)
            if tracker is None:
                tracker = _AtrTracker(period=self.atr_period)
                self._atr_trackers[code] = tracker
            atr = tracker.update(float(high), float(low), float(price))
            if self.use_adx_filter:
                adx_tracker = self._adx_trackers.get(code)
                if adx_tracker is None:
                    adx_tracker = AdxTracker(period=self.adx_period)
                    self._adx_trackers[code] = adx_tracker
                adx_values = adx_tracker.update(float(high), float(low), float(price))
                if adx_values is not None:
                    adx = adx_values[0]
            if self.use_cci_filter:
                cci_tracker = self._cci_trackers.get(code)
                if cci_tracker is None:
                    cci_tracker = CciTracker(period=self.cci_period)
                    self._cci_trackers[code] = cci_tracker
                cci = cci_tracker.update(float(high), float(low), float(price))

        prev = self._last_rsi.get(code)
        prev_price = self._last_price.get(code)
        self._last_rsi[code] = rsi
        in_position = position_qty > 0
        had_position = bool(self._had_position.get(code, False))
        # 포지션 사이클(보유 -> 미보유) 종료 시점에만 진입 상태를 초기화한다.
        if had_position and not in_position:
            # 포지션 사이클이 종료되면 진입 상태를 초기화해 다음 과매수 진입을 허용한다.
            self._entered_overbought.pop(code, None)
            self._grid_anchor.pop(code, None)
            self._sell_half_fired.pop(code, None)
            self._sell_all_fired.pop(code, None)
            self._grid_stage.pop(code, None)
            self._peak_price.pop(code, None)
            self._entry_price.pop(code, None)
        self._had_position[code] = in_position
        if in_position:
            self._peak_price[code] = max(float(price), float(self._peak_price.get(code, float(price))))
            self._entry_price.setdefault(code, float(price))

        signals: List[TradeSignal] = []
        basic_buy_sent = False

        if rsi >= self.overbought:  # RSI가 과매수 기준 이상이면 최초 1회 매수를 평가
            entered = self._entered_overbought.get(code, False)
            # 기본 매수는 RSI >= 과매수 기준일 때 최초 1회만 발생한다. (상향 돌파 조건 제거)
            adx_ok = (not self.use_adx_filter) or (adx is not None and float(adx) >= float(self.adx_threshold))
            cci_ok = (not self.use_cci_filter) or (cci is not None and float(cci) >= float(self.cci_entry_threshold))
            entry_atr_ok = True
            if self.entry_atr_mult > 0:
                entry_atr_ok = (
                    prev_price is not None
                    and atr is not None
                    and atr > 0
                    and float(price) >= (float(prev_price) + (float(atr) * float(self.entry_atr_mult)))
                )
            if not entered and adx_ok and cci_ok and entry_atr_ok and self.cooldown.allow(code):
                base_cash = int(max(0.0, float(self.buy_cash) * float(self.stage_multipliers[0])))
                qty = self.order_sizer.buy_quantity(base_cash, price)
                if qty > 0:
                    adx_reason = f" ADX {float(adx):.1f}" if self.use_adx_filter and adx is not None else ""
                    cci_reason = f" CCI {float(cci):.1f}" if self.use_cci_filter and cci is not None else ""
                    atr_reason = f" ATR {float(atr):.2f}x{self.entry_atr_mult:.2f}" if self.entry_atr_mult > 0 and atr is not None else ""
                    signals.append(
                        TradeSignal(
                            code=code,
                            side="BUY",
                            quantity=qty,
                            reason=f"RSI ENTRY_STAGE_0 {rsi:.2f} {self.overbought:.0f}이상 매수{adx_reason}{cci_reason}{atr_reason}",
                            price=price,
                            tag="rsi:ENTRY_STAGE_0",
                        )
                    )
                    self.cooldown.mark(code)
                    basic_buy_sent = True
                    self._entered_overbought[code] = True
                    # 기본 매수가 발생한 시점 가격을 그리드 앵커로 갱신한다.
                    self._grid_anchor[code] = float(price)
                    self._grid_stage[code] = 0
                    self._peak_price[code] = float(price)
                    self._entry_price[code] = float(price)

        # 동일 업데이트에서 기본 매수와 그리드 매수가 동시에 발생하지 않도록 제한한다.
        if (
            prev is not None
            and
            not basic_buy_sent
            and self.pyramiding_enabled
            and self.grid_step_percent > 0
            and self._entered_overbought.get(code, False)
        ):
            anchor = self._grid_anchor.get(code, 0.0)
            if anchor <= 0:
                anchor = float(price)
            step_ratio = 1.0 + (self.grid_step_percent / 100.0)
            current_stage = int(self._grid_stage.get(code, 0))
            next_stage = current_stage + 1
            grid_trigger = float(anchor) * step_ratio
            atr_trigger_ok = True
            cci_add_ok = (not self.use_cci_filter) or (cci is not None and float(cci) >= float(self.cci_add_threshold))
            if self.add_atr_mult > 0:
                atr_trigger_ok = atr is not None and atr > 0 and float(price) >= (float(anchor) + (float(atr) * float(self.add_atr_mult)))
            if next_stage < len(self.stage_multipliers) and float(price) >= grid_trigger and atr_trigger_ok and cci_add_ok:
                stage_cash = int(max(0.0, float(self.buy_cash) * float(self.stage_multipliers[next_stage])))
                qty = self.order_sizer.buy_quantity(stage_cash, price)
                if qty > 0:
                    cci_reason = f" CCI {float(cci):.1f}" if self.use_cci_filter and cci is not None else ""
                    atr_reason = f" ATR {float(atr):.2f}x{self.add_atr_mult:.2f}" if self.add_atr_mult > 0 and atr is not None else ""
                    signals.append(
                        TradeSignal(
                            code=code,
                            side="BUY",
                            quantity=qty,
                            reason=f"RSI ADD_STAGE_{next_stage}{cci_reason}{atr_reason}",
                            price=price,
                            tag=f"rsi:ADD_STAGE_{next_stage}",
                        )
                    )
                    self._grid_anchor[code] = float(price)
                    self._grid_stage[code] = next_stage
                    self._peak_price[code] = max(float(price), float(self._peak_price.get(code, float(price))))

        sell_all_fired = bool(self._sell_all_fired.get(code, False))
        sell_half_fired = bool(self._sell_half_fired.get(code, False))

        atr_exit_signal: Optional[TradeSignal] = None
        if prev is None:
            return signals

        if prev >= self.sell_all and rsi < self.sell_all and not sell_all_fired: # 과매수 구간에서 하향 돌파
            qty = self.order_sizer.sell_quantity(position_qty, 1.0)
            if qty > 0:
                signals.append(
                    TradeSignal(
                        code=code,
                        side="SELL",
                        quantity=qty,
                        reason=f"RSI {rsi:.2f} 전량 매도",
                        price=price,
                    )
                )
                self._sell_all_fired[code] = True
                self._sell_half_fired[code] = True
        elif prev >= self.sell_half and rsi < self.sell_half and not sell_half_fired and not sell_all_fired: # 중간 매도 구간에서 하향 돌파
            if self.cooldown.allow(code):
                qty = self.order_sizer.sell_quantity(position_qty, 0.5)
                if qty > 0:
                    signals.append(
                        TradeSignal(
                            code=code,
                            side="SELL",
                            quantity=qty,
                            reason=f"RSI {rsi:.2f} 50% 매도",
                            price=price,
                        )
                    )
                    self.cooldown.mark(code)
                    self._sell_half_fired[code] = True

        # ATR 트레일링은 RSI 부분청산 이후 또는 수익권 진입 후 남은 물량을 정리하는 최종 방어선이다.
        sell_half_armed = bool(self._sell_half_fired.get(code, False))
        sell_all_done = bool(self._sell_all_fired.get(code, False))
        entry_price = float(self._entry_price.get(code, float(price)))
        profit_protect_armed = False
        if (
            self.profit_protect_atr_mult > 0
            and entry_price > 0
            and atr is not None
            and atr > 0
        ):
            peak = float(self._peak_price.get(code, float(price)))
            arm_price = entry_price + (float(atr) * float(self.profit_protect_atr_mult))
            profit_protect_armed = peak >= arm_price and float(price) >= entry_price
        if (
            not signals
            and in_position
            and (sell_half_armed or profit_protect_armed)
            and not sell_all_done
            and self.atr_trailing_mult > 0
            and atr is not None
            and atr > 0
        ):
            peak = float(self._peak_price.get(code, float(price)))
            effective_mult = float(self.atr_trailing_mult) + float(self.atr_buffer_mult)
            stop_price = peak - (float(atr) * effective_mult)
            if float(price) <= stop_price:
                qty = self.order_sizer.sell_quantity(position_qty, 1.0)
                if qty > 0:
                    atr_exit_signal = TradeSignal(
                        code=code,
                        side="SELL",
                        quantity=qty,
                        reason=f"RSI EXIT_ATR {effective_mult:.2f}",
                        price=price,
                        tag="rsi:EXIT_ATR",
                    )
                    self._sell_all_fired[code] = True
                    self._sell_half_fired[code] = True

        if atr_exit_signal is not None:
            signals.append(atr_exit_signal)
        self._last_price[code] = float(price)
        return signals

    def reset_code(self, code: str) -> None:
        """특정 종목의 RSI 상태를 초기화한다."""
        self._last_rsi.pop(code, None)
        self._last_price.pop(code, None)
        self._grid_anchor.pop(code, None)
        self._entered_overbought.pop(code, None)
        self._had_position.pop(code, None)
        self._sell_half_fired.pop(code, None)
        self._sell_all_fired.pop(code, None)
        self._grid_stage.pop(code, None)
        self._atr_trackers.pop(code, None)
        self._peak_price.pop(code, None)
        self._entry_price.pop(code, None)
        self._adx_trackers.pop(code, None)
        self._cci_trackers.pop(code, None)


@dataclass
class AdaptiveStrategy:
    """변동성과 추세 강도에 따라 RSI 그리드, Failure Swing, ADX 전략을 동적으로 조합하는 전략.
    
    - 변동성: ATR 기반 상대 변동성 (%ATR / 가격)
    - 추세 강도: ADX 값
    - 전략 선택:
      * ADX > 25 (강한 추세): ADX 우선 + RSI/FS 보조
      * 변동성 높음 (>1.5%): RSI 그리드 우선 (여러 번 매수)
      * 변동성 낮음 (<=1.5%): Failure Swing 우선 (큰 반전 노림)
    """

    rsi_strategy: RsiStrategy
    failure_swing_strategy: FailureSwingStrategy
    volatility_period: int = 14
    volatility_threshold: float = 1.7
    adx_period: int = 14
    adx_threshold: float = 28.0
    scalp_lookback: int = 10
    scalp_breakout_buffer_pct: float = 0.10
    scalp_min_momentum_bars: int = 2
    scalp_min_volatility_pct: float = 0.08
    scalp_max_chase_atr_mult: float = 2.5
    scalp_stop_atr_mult: float = 1.4
    scalp_trailing_atr_mult: float = 2.0
    scalp_trailing_arm_atr_mult: float = 1.0
    scalp_take_profit_atr_mult: float = 2.6
    scalp_take_profit_pct: float = 1.6
    name: str = field(init=False, default="adaptive")
    label: str = field(init=False, default="적응형 하이브리드")
    requires_rsi: bool = field(init=False, default=True)

    def __post_init__(self) -> None:
        """변동성 및 추세 추적 초기화."""
        self.volatility_period = max(2, int(self.volatility_period))
        self.scalp_lookback = max(2, int(self.scalp_lookback))
        self.scalp_min_momentum_bars = max(1, int(self.scalp_min_momentum_bars))
        self.scalp_breakout_buffer_pct = max(0.0, float(self.scalp_breakout_buffer_pct))
        self.scalp_min_volatility_pct = max(0.0, float(self.scalp_min_volatility_pct))
        self.scalp_max_chase_atr_mult = max(0.0, float(self.scalp_max_chase_atr_mult))
        self.scalp_stop_atr_mult = max(0.0, float(self.scalp_stop_atr_mult))
        self.scalp_trailing_atr_mult = max(0.0, float(self.scalp_trailing_atr_mult))
        self.scalp_trailing_arm_atr_mult = max(0.0, float(self.scalp_trailing_arm_atr_mult))
        self.scalp_take_profit_atr_mult = max(0.0, float(self.scalp_take_profit_atr_mult))
        self.scalp_take_profit_pct = max(0.0, float(self.scalp_take_profit_pct))
        self._price_history: Dict[str, list] = {}
        self._high_history: Dict[str, list] = {}
        self._low_history: Dict[str, list] = {}
        self._atr_trackers: Dict[str, _AtrTracker] = {}
        self._adx_trackers: Dict[str, AdxTracker] = {}
        self._scalp_entry_price: Dict[str, float] = {}
        self._scalp_peak_price: Dict[str, float] = {}
        self._adx_strategy = AdxDmiStrategy(
            adx_period=self.adx_period,
            adx_threshold=self.adx_threshold,
            buy_cash=self.rsi_strategy.buy_cash if hasattr(self.rsi_strategy, 'buy_cash') else 0,
            cooldown=self.rsi_strategy.cooldown if hasattr(self.rsi_strategy, 'cooldown') else CooldownTracker(),
            order_sizer=self.rsi_strategy.order_sizer if hasattr(self.rsi_strategy, 'order_sizer') else OrderSizer(),
            market_hours=self.rsi_strategy.market_hours if hasattr(self.rsi_strategy, 'market_hours') else MarketHours(),
        )

    def on_rsi_update(self, code: str, rsi: float, price: int, position_qty: int, high: int = None, low: int = None) -> List[TradeSignal]:
        """변동성과 추세 강도를 분석하여 최적의 전략을 선택하고 신호를 생성한다."""
        # ATR과 ADX 계산 (변동성, 추세 강도 측정)
        atr, adx = self._update_indicators(code, price, high, low)
        volatility = self._calculate_volatility(code, price, atr)
        self._update_scalp_history(code, price, high, low)

        scalp_exit = self._build_scalp_exit_signal(code, price, position_qty, atr)
        if scalp_exit is not None:
            return [scalp_exit]

        scalp_entry = self._build_scalp_entry_signal(code, price, position_qty, atr, adx, volatility)
        if scalp_entry is not None:
            return [scalp_entry]
        
        # 1. 강한 추세 진행 중: ADX 전략 우선
        if adx is not None and adx >= self.adx_threshold:
            adx_signals = self._filter_buy_signals(
                self._adx_strategy.on_rsi_update(code, rsi, price, position_qty, high=high, low=low),
                position_qty,
                adx,
                volatility
            )
            if adx_signals:
                return adx_signals
        
        # 2. ADX 신호가 없거나 약한 추세: 변동성 기반 선택
        rsi_signals = self.rsi_strategy.on_rsi_update(code, rsi, price, position_qty, high=high, low=low)
        fs_signals = self.failure_swing_strategy.on_rsi_update(code, rsi, price, position_qty, high=high, low=low)
        
        # 변동성이 높으면 RSI 그리드 우선 (여러 번 매수 활용)
        if volatility >= self.volatility_threshold:
            combined = self._merge_signals(rsi_signals, fs_signals, prefer_rsi=True)
        else:
            # 변동성이 낮으면 Failure Swing 우선 (큰 움직임 노림)
            combined = self._merge_signals(rsi_signals, fs_signals, prefer_rsi=False)
        
        return combined

    def reset_code(self, code: str) -> None:
        """상태를 초기화한다."""
        self.rsi_strategy.reset_code(code)
        self.failure_swing_strategy.reset_code(code)
        self._adx_strategy.reset_code(code)
        self._price_history.pop(code, None)
        self._high_history.pop(code, None)
        self._low_history.pop(code, None)
        self._atr_trackers.pop(code, None)
        self._adx_trackers.pop(code, None)
        self._scalp_entry_price.pop(code, None)
        self._scalp_peak_price.pop(code, None)

    def _update_indicators(self, code: str, price: int, high: Optional[int], low: Optional[int]) -> tuple:
        """ATR과 ADX를 업데이트하고 반환한다."""
        atr = None
        adx = None
        
        if high is not None and low is not None:
            # ATR 계산
            tracker = self._atr_trackers.get(code)
            if tracker is None:
                tracker = _AtrTracker(period=self.volatility_period)
                self._atr_trackers[code] = tracker
            atr = tracker.update(float(high), float(low), float(price))
            
            # ADX 계산
            adx_tracker = self._adx_trackers.get(code)
            if adx_tracker is None:
                adx_tracker = AdxTracker(period=self.adx_period)
                self._adx_trackers[code] = adx_tracker
            result = adx_tracker.update(float(high), float(low), float(price))
            if result is not None:
                adx = result[0]
        
        return atr, adx

    def _calculate_volatility(self, code: str, price: int, atr: Optional[float]) -> float:
        """ATR 기반 상대 변동성(%)을 계산한다.
        
        변동성 = ATR / 가격 * 100 (%)
        - ATR이 없으면 가격 변화율 평균 사용
        """
        if atr is not None and atr > 0 and price > 0:
            return (float(atr) / float(price)) * 100.0
        
        # ATR 없을 때 대체: 가격 변화율 평균
        hist = self._price_history.get(code, [])
        hist.append(price)
        if len(hist) > self.volatility_period:
            hist.pop(0)
        self._price_history[code] = hist
        
        if len(hist) < 2:
            return 0.0
        changes = [
            abs(hist[i] - hist[i-1]) / hist[i-1] * 100.0 
            for i in range(1, len(hist)) if hist[i-1] > 0
        ]
        return sum(changes) / len(changes) if changes else 0.0

    def _update_scalp_history(self, code: str, price: int, high: Optional[int], low: Optional[int]) -> None:
        """스켈핑 판단에 쓸 최근 고가/저가를 짧게 유지한다."""
        high_value = int(high) if high is not None else int(price)
        low_value = int(low) if low is not None else int(price)
        max_len = max(self.volatility_period, self.scalp_lookback + self.scalp_min_momentum_bars + 2)
        highs = self._high_history.get(code, [])
        lows = self._low_history.get(code, [])
        highs.append(high_value)
        lows.append(low_value)
        if len(highs) > max_len:
            highs.pop(0)
        if len(lows) > max_len:
            lows.pop(0)
        self._high_history[code] = highs
        self._low_history[code] = lows

    def _build_scalp_entry_signal(
        self,
        code: str,
        price: int,
        position_qty: int,
        atr: Optional[float],
        adx: Optional[float],
        volatility: float,
    ) -> Optional[TradeSignal]:
        """KOSPI 스켈핑용 빠른 돌파 진입 신호를 만든다."""
        if position_qty > 0 or not self.rsi_strategy.market_hours.is_open(self.rsi_strategy.cooldown.now()):
            return None
        highs = self._high_history.get(code, [])
        lows = self._low_history.get(code, [])
        prices = self._price_history.get(code, [])
        if len(highs) <= self.scalp_lookback or len(prices) <= self.scalp_min_momentum_bars:
            return None

        previous_high = max(highs[-self.scalp_lookback - 1 : -1])
        breakout_price = float(previous_high) * (1.0 + (self.scalp_breakout_buffer_pct / 100.0))
        if atr is not None and atr > 0:
            breakout_price = max(breakout_price, float(previous_high) + (float(atr) * 0.15))
        if float(price) < breakout_price:
            return None

        recent_prices = prices[-(self.scalp_min_momentum_bars + 1) :]
        momentum_ok = all(recent_prices[i] < recent_prices[i + 1] for i in range(len(recent_prices) - 1))
        if not momentum_ok:
            return None
        if volatility < self.scalp_min_volatility_pct:
            return None
        if atr is not None and atr > 0 and self.scalp_max_chase_atr_mult > 0:
            recent_low = min(lows[-self.scalp_lookback:]) if lows else float(price)
            if float(price) > float(recent_low) + (float(atr) * self.scalp_max_chase_atr_mult):
                return None
        if adx is not None and adx < max(10.0, float(self.adx_threshold) * 0.45):
            return None
        if not self.rsi_strategy.cooldown.allow(code):
            return None

        qty = self.rsi_strategy.order_sizer.buy_quantity(self.rsi_strategy.buy_cash, price)
        if qty <= 0:
            return None
        self.rsi_strategy.cooldown.mark(code)
        self._scalp_entry_price[code] = float(price)
        self._scalp_peak_price[code] = float(price)
        return TradeSignal(
            code=code,
            side="BUY",
            quantity=qty,
            reason=f"ADAPTIVE SCALP 돌파 {price} >= {breakout_price:.0f} 변동성 {volatility:.2f}%",
            price=price,
            tag="adaptive:SCALP_ENTRY",
        )

    def _build_scalp_exit_signal(
        self,
        code: str,
        price: int,
        position_qty: int,
        atr: Optional[float],
    ) -> Optional[TradeSignal]:
        """스켈핑 포지션을 짧게 보호하는 청산 신호를 만든다."""
        if position_qty <= 0:
            self._scalp_entry_price.pop(code, None)
            self._scalp_peak_price.pop(code, None)
            return None

        entry_price = float(self._scalp_entry_price.get(code, float(price)))
        peak_price = max(float(price), float(self._scalp_peak_price.get(code, float(price))))
        self._scalp_entry_price.setdefault(code, entry_price)
        self._scalp_peak_price[code] = peak_price

        if atr is not None and atr > 0:
            stop_price = entry_price - (float(atr) * self.scalp_stop_atr_mult)
            trail_price = peak_price - (float(atr) * self.scalp_trailing_atr_mult)
            trail_arm_price = entry_price + (float(atr) * self.scalp_trailing_arm_atr_mult)
            take_profit_price = entry_price + (float(atr) * self.scalp_take_profit_atr_mult)
        else:
            stop_price = entry_price * 0.990
            trail_price = peak_price * 0.990
            trail_arm_price = entry_price * (1.0 + (self.scalp_take_profit_pct / 200.0))
            take_profit_price = entry_price * (1.0 + (self.scalp_take_profit_pct / 100.0))

        pct_take_profit_price = entry_price * (1.0 + (self.scalp_take_profit_pct / 100.0))
        take_profit_price = max(take_profit_price, pct_take_profit_price)
        reason = ""
        if float(price) <= stop_price:
            reason = f"ADAPTIVE SCALP 손절 {price} <= {stop_price:.0f}"
        elif peak_price >= trail_arm_price and float(price) <= trail_price:
            reason = f"ADAPTIVE SCALP 트레일링 {price} <= {trail_price:.0f}"
        elif float(price) >= take_profit_price:
            reason = f"ADAPTIVE SCALP 익절 {price} >= {take_profit_price:.0f}"
        if not reason:
            return None

        qty = self.rsi_strategy.order_sizer.sell_quantity(position_qty, 1.0)
        if qty <= 0:
            return None
        return TradeSignal(
            code=code,
            side="SELL",
            quantity=qty,
            reason=reason,
            price=price,
            tag="adaptive:SCALP_EXIT",
        )

    def _filter_buy_signals(self, signals: List[TradeSignal], position_qty: int, adx: float, volatility: float) -> List[TradeSignal]:
        """ADX 신호를 필터링한다.
        
        ADX가 충분히 강하면 보유 중 추가 매수 제한 (추세 추종에 집중)
        """
        if position_qty > 0:
            # 포지션 보유 중엔 매도/손절만 허용 (추세 추종 유지)
            return [s for s in signals if s.side == "SELL"]
        
        # 매도 신호와 강한 매수 신호만 반환
        sells = [s for s in signals if s.side == "SELL"]
        buys = [s for s in signals if s.side == "BUY"]
        
        return sells + buys

    def _merge_signals(self, rsi_signals: List[TradeSignal], fs_signals: List[TradeSignal], prefer_rsi: bool) -> List[TradeSignal]:
        """RSI와 Failure Swing 신호를 지능형으로 병합한다.
        
        - 매도 신호는 모두 포함 (손절, 익절 우선)
        - 매수 신호는 우선순위에 따라 선택
        - prefer_rsi=True: RSI 그리드 매수 우선
        - prefer_rsi=False: FS 매수 우선
        """
        rsi_sells = [s for s in rsi_signals if s.side == "SELL"]
        fs_sells = [s for s in fs_signals if s.side == "SELL"]
        rsi_buys = [s for s in rsi_signals if s.side == "BUY"]
        fs_buys = [s for s in fs_signals if s.side == "BUY"]
        
        # 매도 신호는 모두 포함 (수익 실현, 손절 우선)
        sells = rsi_sells + fs_sells
        
        # 매수 신호는 우선순위에 따라 선택
        if prefer_rsi:
            # 변동성 높음: RSI 그리드 매수 우선 (여러 단계 진입)
            buys = rsi_buys + fs_buys
        else:
            # 변동성 낮음: Failure Swing 매수 우선 (큰 반전 후 진입)
            buys = fs_buys + rsi_buys
        
        # 중복 제거: 같은 side의 신호는 최대 1개만 (동일 업데이트에서 여러 신호 방지)
        filtered = sells
        if buys:
            filtered.append(buys[0])  # 최우선 매수만 선택
        
        return filtered



@dataclass
class AdxDmiStrategy:
    """Wilder ADX + DMI 규칙 기반 전략.

    고급 규칙:
    - ADX >= 20: 트렌드 강도 확인
    - ADX >= threshold (기본 25): 강한 트렌드 진입
    - ADX < 20: 약한 트렌드, 기존 포지션 청산 권장
    - ADX 하락 중: 매수 신호 억제
    - 다이버전스: DI 차이 감소 + ADX 하락 → 추세 전환 신호
    """

    adx_period: int
    adx_threshold: float
    buy_cash: int
    cooldown: CooldownTracker
    order_sizer: OrderSizer
    market_hours: MarketHours
    adx_weak_threshold: float = field(default=18.0)  # ADX <= 18: 약한 트렌드
    adx_exit_falling_bars: int = field(default=3)  # ADX 연속 하락 청산 캔들 수
    atr_trailing_mult: float = field(default=2.5)  # ATR 트레일링 스탑 배수
    adx_use_weak_exit: bool = field(default=False)  # ADX 약세 강제청산 사용 여부
    name: str = field(init=False, default="adx_dmi")
    label: str = field(init=False, default="ADX + DMI")
    requires_rsi: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self.adx_exit_falling_bars = max(1, int(self.adx_exit_falling_bars))
        self.atr_trailing_mult = max(0.0, float(self.atr_trailing_mult))
        # per-code ADX trackers to avoid cross-symbol state pollution
        self._adx_trackers: Dict[str, AdxTracker] = {}
        self._prev_di_plus: Dict[str, float] = {}
        self._prev_di_minus: Dict[str, float] = {}
        self._prev_di_diff: Dict[str, float] = {}  # DI+ - DI- 의 이전값
        self._prev_adx: Dict[str, Optional[float]] = {}  # ADX 이전값
        self._in_position: Dict[str, bool] = {}  # 포지션 여부
        self._peak_price: Dict[str, float] = {}
        self._adx_falling_count: Dict[str, int] = {}

    def on_rsi_update(self, code: str, rsi: float, price: int, position_qty: int, high: int = None, low: int = None) -> List[TradeSignal]:
        """RSI 업데이트 훅을 이용해 캔들 (또는 틱봉) HIGH/LOW/CLOSE 기준으로 ADX/DMI 신호를 생성한다.

        high/low 캔들 데이터가 제공되면 정확한 ADX 계산을 수행하고,
        없으면 price를 high/low/close 모두로 대체해 근사 계산을 수행한다.
        """
        if not self.market_hours.is_open(self.cooldown.now()):
            return []

        tracker = self._adx_trackers.get(code)
        if tracker is None:
            tracker = AdxTracker(period=self.adx_period)
            self._adx_trackers[code] = tracker

        # high/low가 제공되지 않으면 price로 근사
        if high is None:
            high = price
        if low is None:
            low = price

        res = tracker.update(high, low, price)
        if res is None:
            return []
        adx, di_plus, di_minus = res

        # 초기값 처리: 첫 호출 시 prev 값이 current 값으로 설정되도록
        if code not in self._prev_di_plus:
            self._prev_di_plus[code] = di_plus
            self._prev_di_minus[code] = di_minus
            self._prev_di_diff[code] = di_plus - di_minus
            self._prev_adx[code] = adx
        
        prev_plus = self._prev_di_plus[code]
        prev_minus = self._prev_di_minus[code]

        signals: List[TradeSignal] = []

        # DI 교차 판정
        crossed_up = (prev_plus <= prev_minus) and (di_plus > di_minus)
        crossed_down = (prev_minus <= prev_plus) and (di_minus > di_plus)

        # DI 차이 계산
        di_diff = di_plus - di_minus

        # ADX 추세 정보
        prev_adx = self._prev_adx.get(code, adx)
        adx_falling = prev_adx is not None and adx is not None and adx < prev_adx
        atr = tracker.get_atr()

        # 포지션 상태 업데이트
        in_position = position_qty > 0
        self._in_position[code] = in_position

        # 포지션이 없으면 추적 상태를 초기화한다.
        if not in_position:
            self._peak_price.pop(code, None)
            self._adx_falling_count[code] = 0
        else:
            peak = self._peak_price.get(code, float(price))
            if price > peak:
                peak = float(price)
            self._peak_price[code] = peak
            if adx_falling:
                self._adx_falling_count[code] = int(self._adx_falling_count.get(code, 0)) + 1
            else:
                self._adx_falling_count[code] = 0

            # 1) DI- 상향교차 청산 (기본 추세 종료)
            if crossed_down and not signals:
                qty = self.order_sizer.sell_quantity(position_qty, 1.0)
                if qty > 0:
                    signals.append(
                        TradeSignal(
                            code=code,
                            side="SELL",
                            quantity=qty,
                            reason=f"DI- 상향 교차 ADX {adx:.1f} 청산",
                            price=price,
                        )
                    )

            # 2) ADX 약세/연속 하락 강제청산 (옵션)
            if (
                self.adx_use_weak_exit
                and adx is not None
                and not signals
            ):
                weak_exit = adx <= self.adx_weak_threshold
                falling_exit = self._adx_falling_count.get(code, 0) >= self.adx_exit_falling_bars
                if weak_exit or falling_exit:
                    qty = self.order_sizer.sell_quantity(position_qty, 1.0)
                    if qty > 0:
                        reason = (
                            f"ADX 약세 {adx:.1f} (<= {self.adx_weak_threshold}) 청산"
                            if weak_exit
                            else f"ADX {self.adx_exit_falling_bars}봉 연속 하락 청산"
                        )
                        signals.append(
                            TradeSignal(
                                code=code,
                                side="SELL",
                                quantity=qty,
                                reason=reason,
                                price=price,
                            )
                        )

            # 3) ATR 트레일링 스탑 청산
            if (
                not signals
                and atr is not None
                and atr > 0
                and float(self.atr_trailing_mult) > 0
            ):
                stop_price = float(self._peak_price.get(code, float(price))) - (float(self.atr_trailing_mult) * float(atr))
                if float(price) <= stop_price:
                    qty = self.order_sizer.sell_quantity(position_qty, 1.0)
                    if qty > 0:
                        signals.append(
                            TradeSignal(
                                code=code,
                                side="SELL",
                                quantity=qty,
                                reason=f"ATR 트레일링 스탑(배수 {self.atr_trailing_mult:.2f}) 청산",
                                price=price,
                            )
                        )

        # === 매수/매도 신호 (포지션이 없을 때만 발생) ===
        if adx is not None and not signals and not in_position:
            # 추세추종 진입:
            # - ADX 기준 이상 + ADX 상승
            # - DI+ 우위 상태이며(방향성 유지), 상향교차 직후 또는 이미 우위가 유지된 구간
            adx_rising = prev_adx is not None and adx > prev_adx
            bullish_regime = di_plus > di_minus and (crossed_up or prev_plus > prev_minus)
            should_buy = bullish_regime and adx >= self.adx_threshold and adx_rising

            if should_buy and self.cooldown.allow(code):
                qty = self.order_sizer.buy_quantity(self.buy_cash, price)
                if qty > 0:
                    signals.append(
                        TradeSignal(
                            code=code,
                            side="BUY",
                            quantity=qty,
                            reason=f"DI+ 우위 + ADX 상승({prev_adx:.1f}->{adx:.1f}) 매수",
                            price=price,
                        )
                    )
                    self.cooldown.mark(code)
                    self._peak_price[code] = float(price)

        # 상태 업데이트
        self._prev_di_plus[code] = di_plus
        self._prev_di_minus[code] = di_minus
        self._prev_di_diff[code] = di_diff
        self._prev_adx[code] = adx

        return signals

    def reset_code(self, code: str) -> None:
        """종목 관련 ADX 내부 상태를 초기화한다."""
        self._adx_trackers.pop(code, None)
        self._prev_di_plus.pop(code, None)
        self._prev_di_minus.pop(code, None)
        self._prev_di_diff.pop(code, None)
        self._prev_adx.pop(code, None)
        self._in_position.pop(code, None)
        self._peak_price.pop(code, None)
        self._adx_falling_count.pop(code, None)



@dataclass
class FailureSwingStrategy:
    """RSI Failure Swing 매매 전략."""

    buy_threshold: float
    sell_threshold: float
    buy_cash: int
    cooldown: CooldownTracker
    order_sizer: OrderSizer
    market_hours: MarketHours
    name: str = field(init=False, default="rsi_failure_swing")
    label: str = field(init=False, default="RSI 실패 스윙")
    requires_rsi: bool = field(init=False, default=True)

    def __post_init__(self) -> None:
        self._bottom_state: Dict[str, dict] = {}
        self._top_state: Dict[str, dict] = {}

    def on_rsi_update(self, code: str, rsi: float, price: int, position_qty: int, high: int = None, low: int = None) -> List[TradeSignal]:
        """RSI 갱신 시 매수/매도 신호를 생성한다."""
        if not self.market_hours.is_open(self.cooldown.now()):
            return []

        signals: List[TradeSignal] = []
        if self._should_buy(code, rsi):
            if self.cooldown.allow(code):
                qty = self.order_sizer.buy_quantity(self.buy_cash, price)
                if qty > 0:
                    signals.append(
                        TradeSignal(
                            code=code,
                            side="BUY",
                            quantity=qty,
                            reason=f"RSI {rsi:.2f} Failure Swing 매수",
                            price=price,
                        )
                    )
                    self.cooldown.mark(code)

        if self._should_sell(code, rsi):
            qty = self.order_sizer.sell_quantity(position_qty, 1.0)
            if qty > 0:
                signals.append(
                    TradeSignal(
                        code=code,
                        side="SELL",
                        quantity=qty,
                        reason=f"RSI {rsi:.2f} Failure Swing 매도",
                        price=price,
                    )
                )

        return signals

    def reset_code(self, code: str) -> None:
        self._bottom_state.pop(code, None)
        self._top_state.pop(code, None)

    def _should_buy(self, code: str, rsi: float) -> bool:
        """Bottom Failure Swing 매수 신호를 판정한다."""
        state = self._bottom_state.get(code)
        if state is None:
            state = {"stage": "idle", "l1": 0.0, "fp": 0.0, "l2": 0.0}
        stage = state["stage"]

        if stage == "idle":
            if rsi <= self.buy_threshold:
                state["l1"] = rsi
                state["stage"] = "l1"
        elif stage == "l1":
            if rsi < state["l1"]:
                state["l1"] = rsi
            elif rsi > state["l1"]:
                state["fp"] = rsi
                state["stage"] = "fp"
        elif stage == "fp":
            if rsi > state["fp"]:
                state["fp"] = rsi
            elif rsi < state["fp"]:
                state["l2"] = rsi
                state["stage"] = "l2"
        elif stage == "l2":
            if rsi < state["l2"]:
                state["l2"] = rsi
            if state["l2"] <= state["l1"]:
                if rsi <= self.buy_threshold:
                    state["l1"] = rsi
                    state["fp"] = 0.0
                    state["l2"] = 0.0
                    state["stage"] = "l1"
                else:
                    state = {"stage": "idle", "l1": 0.0, "fp": 0.0, "l2": 0.0}
            elif rsi > state["fp"]:
                self._bottom_state.pop(code, None)
                return True

        self._bottom_state[code] = state
        return False

    def _should_sell(self, code: str, rsi: float) -> bool:
        """Top Failure Swing 매도 신호를 판정한다."""
        state = self._top_state.get(code)
        if state is None:
            state = {"stage": "idle", "h1": 0.0, "fp": 0.0, "h2": 0.0}
        stage = state["stage"]

        if stage == "idle":
            if rsi >= self.sell_threshold:
                state["h1"] = rsi
                state["stage"] = "h1"
        elif stage == "h1":
            if rsi > state["h1"]:
                state["h1"] = rsi
            elif rsi < state["h1"]:
                state["fp"] = rsi
                state["stage"] = "fp"
        elif stage == "fp":
            if rsi < state["fp"]:
                state["fp"] = rsi
            elif rsi > state["fp"]:
                state["h2"] = rsi
                state["stage"] = "h2"
        elif stage == "h2":
            if rsi > state["h2"]:
                state["h2"] = rsi
            if state["h2"] >= state["h1"]:
                if rsi >= self.sell_threshold:
                    state["h1"] = rsi
                    state["fp"] = 0.0
                    state["h2"] = 0.0
                    state["stage"] = "h1"
                else:
                    state = {"stage": "idle", "h1": 0.0, "fp": 0.0, "h2": 0.0}
            elif rsi < state["fp"]:
                self._top_state.pop(code, None)
                return True

        self._top_state[code] = state
        return False


@dataclass
class DonchianBreakoutStrategy:
    """Donchian 채널 돌파 기반 추세추종 전략."""

    breakout_period: int
    exit_period: int
    buy_cash: int
    cooldown: CooldownTracker
    order_sizer: OrderSizer
    market_hours: MarketHours
    name: str = field(init=False, default="donchian_breakout")
    label: str = field(init=False, default="돈치안 돌파")
    requires_rsi: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self.breakout_period = max(2, int(self.breakout_period))
        self.exit_period = max(2, int(self.exit_period))
        self._high_hist: Dict[str, List[int]] = {}
        self._low_hist: Dict[str, List[int]] = {}

    def on_rsi_update(
        self,
        code: str,
        rsi: float,
        price: int,
        position_qty: int,
        high: int = None,
        low: int = None,
    ) -> List[TradeSignal]:
        if not self.market_hours.is_open(self.cooldown.now()):
            return []

        if high is None:
            high = price
        if low is None:
            low = price

        highs = self._high_hist.setdefault(code, [])
        lows = self._low_hist.setdefault(code, [])
        signals: List[TradeSignal] = []

        entry_high = max(highs[-self.breakout_period:]) if len(highs) >= self.breakout_period else None
        exit_low = min(lows[-self.exit_period:]) if len(lows) >= self.exit_period else None
        in_position = position_qty > 0

        # 현재 캔들을 히스토리에 넣기 전에 이전 캔들 기준으로 돌파를 판정한다.
        if not in_position and entry_high is not None and price > entry_high and self.cooldown.allow(code):
            qty = self.order_sizer.buy_quantity(self.buy_cash, price)
            if qty > 0:
                signals.append(
                    TradeSignal(
                        code=code,
                        side="BUY",
                        quantity=qty,
                        reason=f"Donchian {self.breakout_period} 돌파 매수",
                        price=price,
                    )
                )
                self.cooldown.mark(code)

        if in_position and exit_low is not None and price < exit_low:
            qty = self.order_sizer.sell_quantity(position_qty, 1.0)
            if qty > 0:
                signals.append(
                    TradeSignal(
                        code=code,
                        side="SELL",
                        quantity=qty,
                        reason=f"Donchian {self.exit_period} 하향이탈 청산",
                        price=price,
                    )
                )

        highs.append(int(high))
        lows.append(int(low))
        max_len = max(self.breakout_period, self.exit_period) * 4
        if len(highs) > max_len:
            del highs[:-max_len]
        if len(lows) > max_len:
            del lows[:-max_len]
        return signals

    def reset_code(self, code: str) -> None:
        self._high_hist.pop(code, None)
        self._low_hist.pop(code, None)


@dataclass
class LivermorePyramidStrategy:
    """리버모어식 Donchian + ATR 피라미딩 추세추종 전략."""

    breakout_period: int
    exit_period: int
    add_atr_mult: float
    atr_trailing_mult: float
    atr_buffer_mult: float
    exit_confirm_bars: int
    donchian_exit_ratio: float
    stage_multipliers: List[float]
    buy_cash: int
    cooldown: CooldownTracker
    order_sizer: OrderSizer
    market_hours: MarketHours
    pyramiding_enabled: bool = True
    add_min_hoga_gap: int = 5
    atr_period: int = 14
    use_adx_filter: bool = False
    adx_period: int = 14
    adx_threshold: float = 25.0
    use_cci_filter: bool = False
    cci_period: int = 20
    cci_entry_threshold: float = 100.0
    cci_add_threshold: float = 100.0
    entry_mode: str = "breakout"
    pullback_retrace_atr_mult: float = 0.8
    pullback_rebreak_buffer_atr_mult: float = 0.2
    pullback_invalidate_atr_mult: float = 0.5
    pullback_max_bars: int = 6
    name: str = field(init=False, default="livermore_pyramid")
    label: str = field(init=False, default="리버모어 돌파 피라미딩")
    requires_rsi: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self.breakout_period = max(2, int(self.breakout_period))
        self.exit_period = max(2, int(self.exit_period))
        self.atr_period = max(2, int(self.atr_period))
        self.add_atr_mult = max(0.0, float(self.add_atr_mult))
        self.add_min_hoga_gap = max(0, int(self.add_min_hoga_gap))
        self.atr_trailing_mult = max(0.0, float(self.atr_trailing_mult))
        self.atr_buffer_mult = max(0.0, float(self.atr_buffer_mult))
        self.exit_confirm_bars = max(1, int(self.exit_confirm_bars))
        self.donchian_exit_ratio = min(1.0, max(0.0, float(self.donchian_exit_ratio)))
        self.pyramiding_enabled = bool(self.pyramiding_enabled)
        self.use_cci_filter = bool(self.use_cci_filter)
        self.cci_period = max(2, int(self.cci_period))
        self.cci_entry_threshold = float(self.cci_entry_threshold)
        self.cci_add_threshold = float(self.cci_add_threshold)
        self.entry_mode = str(self.entry_mode or "breakout").strip().lower()
        if self.entry_mode not in {"breakout", "pullback_rebreakout"}:
            self.entry_mode = "breakout"
        self.pullback_retrace_atr_mult = max(0.0, float(self.pullback_retrace_atr_mult))
        self.pullback_rebreak_buffer_atr_mult = max(0.0, float(self.pullback_rebreak_buffer_atr_mult))
        self.pullback_invalidate_atr_mult = max(0.0, float(self.pullback_invalidate_atr_mult))
        self.pullback_max_bars = max(1, int(self.pullback_max_bars))
        multipliers = [float(x) for x in list(self.stage_multipliers or [])]
        if not multipliers:
            multipliers = [1.0, 1.0, 0.8, 0.6, 0.4]
        self.stage_multipliers = multipliers

        self._high_hist: Dict[str, List[int]] = {}
        self._low_hist: Dict[str, List[int]] = {}
        self._atr_trackers: Dict[str, _AtrTracker] = {}
        self._adx_trackers: Dict[str, AdxTracker] = {}
        self._cci_trackers: Dict[str, CciTracker] = {}

        self._last_sell_time: Dict[str, datetime.datetime] = {}

        self._entry_price: Dict[str, float] = {}
        self._last_add_price: Dict[str, float] = {}
        self._peak_price: Dict[str, float] = {}
        self._stage: Dict[str, int] = {}
        self._pending_stage: Dict[str, int] = {}
        self._pending_price: Dict[str, float] = {}
        self._pending_qty: Dict[str, int] = {}
        self._pending_base_qty: Dict[str, int] = {}
        self._retry_count: Dict[str, int] = {}
        self._last_signal_candle: Dict[str, int] = {}
        self._candle_seq: Dict[str, int] = {}
        self._last_position_qty: Dict[str, int] = {}
        self._had_position: Dict[str, bool] = {}
        self._exit_confirm_donchian: Dict[str, int] = {}
        self._exit_confirm_atr: Dict[str, int] = {}
        self._donchian_exit_used: Dict[str, bool] = {}
        self._setup_breakout_level: Dict[str, float] = {}
        self._setup_peak: Dict[str, float] = {}
        self._setup_pullback_seen: Dict[str, bool] = {}
        self._setup_pullback_marker: Dict[str, int] = {}
        self._setup_age: Dict[str, int] = {}

    def _next_candle_marker(self, code: str) -> int:
        seq = int(self._candle_seq.get(code, 0)) + 1
        self._candle_seq[code] = seq
        return seq

    def _tag_prefix(self) -> str:
        name = str(getattr(self, "name", "") or "")
        if name == "livermore_pullback_pyramid":
            return "livermore_pullback"
        if name == "pullback_trend":
            return "pullback"
        return "livermore"

    def _reset_pullback_setup(self, code: str) -> None:
        self._setup_breakout_level.pop(code, None)
        self._setup_peak.pop(code, None)
        self._setup_pullback_seen.pop(code, None)
        self._setup_pullback_marker.pop(code, None)
        self._setup_age.pop(code, None)

    def _build_entry_reason(self, base_reason: str, adx: Optional[float], cci: Optional[float]) -> str:
        reason_str = base_reason
        if self.use_adx_filter and adx is not None:
            reason_str += f" (ADX {adx:.1f})"
        if self.use_cci_filter and cci is not None:
            reason_str += f" (CCI {cci:.1f})"
        return reason_str

    def on_rsi_update(
        self,
        code: str,
        rsi: float,
        price: int,
        position_qty: int,
        high: int = None,
        low: int = None,
    ) -> List[TradeSignal]:
        if not self.market_hours.is_open(self.cooldown.now()):
            return []

        if high is None:
            high = price
        if low is None:
            low = price

        marker = self._next_candle_marker(code)
        tracker = self._atr_trackers.get(code)
        if tracker is None:
            tracker = _AtrTracker(period=self.atr_period)
            self._atr_trackers[code] = tracker
        atr = tracker.update(float(high), float(low), float(price))

        adx = None
        if self.use_adx_filter:
            adx_t = self._adx_trackers.get(code)
            if adx_t is None:
                adx_t = AdxTracker(period=self.adx_period)
                self._adx_trackers[code] = adx_t
            res = adx_t.update(float(high), float(low), float(price))
            if res is not None:
                adx, _, _ = res

        cci = None
        if self.use_cci_filter:
            cci_t = self._cci_trackers.get(code)
            if cci_t is None:
                cci_t = CciTracker(period=self.cci_period)
                self._cci_trackers[code] = cci_t
            cci = cci_t.update(float(high), float(low), float(price))

        in_position = int(position_qty) > 0
        had_position = bool(self._had_position.get(code, False))
        prev_qty = int(self._last_position_qty.get(code, 0))

        pending_stage = self._pending_stage.get(code)
        if pending_stage is not None and in_position:
            pending_qty = int(self._pending_qty.get(code, 0))
            base_qty = int(self._pending_base_qty.get(code, prev_qty))
            if pending_qty > 0 and int(position_qty) >= base_qty + pending_qty:
                self.on_order_filled(
                    code=code,
                    side="BUY",
                    stage=int(pending_stage),
                    price=float(self._pending_price.get(code, float(price))),
                )

        if had_position and not in_position:
            self.reset_code(code)
            in_position = False
        elif in_position:
            if code not in self._entry_price:
                self._entry_price[code] = float(price)
                self._last_add_price[code] = float(price)
                self._stage[code] = max(0, int(self._stage.get(code, 0)))
            self._peak_price[code] = max(self._peak_price.get(code, float(price)), float(price))
            self._reset_pullback_setup(code)

        highs = self._high_hist.setdefault(code, [])
        lows = self._low_hist.setdefault(code, [])
        entry_high = max(highs[-self.breakout_period:]) if len(highs) >= self.breakout_period else None
        exit_low = min(lows[-self.exit_period:]) if len(lows) >= self.exit_period else None
        signals: List[TradeSignal] = []

        if in_position:
            now = self.cooldown.now()
            last_sell = self._last_sell_time.get(code)
            can_sell = last_sell is None or (now - last_sell).total_seconds() >= 5.0

            exit_confirm_needed = int(self.exit_confirm_bars)
            donchian_trigger = exit_low is not None and float(price) <= float(exit_low)
            if donchian_trigger:
                self._exit_confirm_donchian[code] = int(self._exit_confirm_donchian.get(code, 0)) + 1
            else:
                self._exit_confirm_donchian[code] = 0

            atr_trigger = False
            stop_price = None
            if (
                atr is not None
                and atr > 0
                and self.atr_trailing_mult > 0
            ):
                peak = float(self._peak_price.get(code, float(price)))
                effective_mult = float(self.atr_trailing_mult) + float(self.atr_buffer_mult)
                stop_price = peak - (float(atr) * float(effective_mult))
                if float(price) <= stop_price:
                    atr_trigger = True

            if atr_trigger:
                self._exit_confirm_atr[code] = int(self._exit_confirm_atr.get(code, 0)) + 1
            else:
                self._exit_confirm_atr[code] = 0

            donchian_ratio = float(self.donchian_exit_ratio)
            donchian_available = not bool(self._donchian_exit_used.get(code, False))
            if can_sell and donchian_available and donchian_ratio > 0.0 and self._exit_confirm_donchian.get(code, 0) >= exit_confirm_needed:
                qty = self.order_sizer.sell_quantity(int(position_qty), donchian_ratio)
                if qty <= 0 and int(position_qty) > 0:
                    qty = 1
                if qty > 0:
                    signals.append(
                        TradeSignal(
                            code=code,
                            side="SELL",
                            quantity=qty,
                            reason=f"EXIT_DONCHIAN {self.exit_period} CONFIRM {exit_confirm_needed} PARTIAL {donchian_ratio:.2f}",
                            price=price,
                            tag=f"{self._tag_prefix()}:EXIT_DONCHIAN",
                        )
                    )
                    self._last_sell_time[code] = now
                    self._donchian_exit_used[code] = True
            elif can_sell and self._exit_confirm_atr.get(code, 0) >= exit_confirm_needed:
                qty = self.order_sizer.sell_quantity(int(position_qty), 1.0)
                if qty > 0:
                    effective_mult = float(self.atr_trailing_mult) + float(self.atr_buffer_mult)
                    signals.append(
                        TradeSignal(
                            code=code,
                            side="SELL",
                            quantity=qty,
                            reason=f"EXIT_ATR {effective_mult:.2f} CONFIRM {exit_confirm_needed}",
                            price=price,
                            tag=f"{self._tag_prefix()}:EXIT_ATR",
                        )
                    )
                    self._last_sell_time[code] = now

            if not signals:
                current_stage = int(self._stage.get(code, 0))
                next_stage = current_stage + 1
                if (
                    self.pyramiding_enabled
                    and
                    self._pending_stage.get(code) is None
                    and next_stage < len(self.stage_multipliers)
                    and atr is not None
                    and atr > 0
                ):
                    base = float(self._last_add_price.get(code, float(price)))
                    trigger = base + (float(atr) * float(self.add_atr_mult))
                    min_gap_price = self._shift_price_by_hoga(base, int(self.add_min_hoga_gap))
                    cci_add_ok = (not self.use_cci_filter) or (cci is not None and float(cci) >= self.cci_add_threshold)
                    if float(price) >= trigger and float(price) >= min_gap_price and cci_add_ok and self.cooldown.allow(code):
                        cash = int(max(0.0, float(self.buy_cash) * float(self.stage_multipliers[next_stage])))
                        qty = self.order_sizer.buy_quantity(cash, price)
                        if qty > 0:
                            reason_str = f"ADD_STAGE_{next_stage}"
                            if self.use_cci_filter and cci is not None:
                                reason_str += f" (CCI {cci:.1f})"
                            signals.append(
                                TradeSignal(
                                    code=code,
                                    side="BUY",
                                    quantity=qty,
                                    reason=reason_str,
                                    price=price,
                                    tag=f"{self._tag_prefix()}:ADD_STAGE_{next_stage}",
                                )
                            )
                            self.cooldown.mark(code)
                            self._pending_stage[code] = next_stage
                            self._pending_price[code] = float(price)
                            self._pending_qty[code] = int(qty)
                            self._pending_base_qty[code] = int(position_qty)
                            self._retry_count[code] = 0
                            self._last_signal_candle[code] = marker
        else:
            can_entry = True
            if self.use_adx_filter:
                can_entry = adx is not None and adx >= self.adx_threshold
            if self.use_cci_filter:
                can_entry = can_entry and cci is not None and cci >= self.cci_entry_threshold

            if self._pending_stage.get(code) is None and entry_high is not None:
                if self.entry_mode == "pullback_rebreakout":
                    if atr is None or atr <= 0:
                        self._reset_pullback_setup(code)
                    else:
                        setup_level = self._setup_breakout_level.get(code)
                        if setup_level is None:
                            if float(price) > float(entry_high) and can_entry:
                                self._setup_breakout_level[code] = float(entry_high)
                                self._setup_peak[code] = max(float(high), float(price))
                                self._setup_pullback_seen[code] = False
                                self._setup_pullback_marker.pop(code, None)
                                self._setup_age[code] = 0
                        else:
                            self._setup_age[code] = int(self._setup_age.get(code, 0)) + 1
                            breakout_level = float(setup_level)
                            peak = max(
                                float(self._setup_peak.get(code, breakout_level)),
                                float(high),
                                float(price),
                            )
                            self._setup_peak[code] = peak
                            invalidate_price = breakout_level - (float(atr) * float(self.pullback_invalidate_atr_mult))
                            if float(low) < invalidate_price or int(self._setup_age.get(code, 0)) > int(self.pullback_max_bars):
                                self._reset_pullback_setup(code)
                            else:
                                retrace_price = peak - (float(atr) * float(self.pullback_retrace_atr_mult))
                                if (
                                    not bool(self._setup_pullback_seen.get(code, False))
                                    and float(low) <= retrace_price
                                ):
                                    self._setup_pullback_seen[code] = True
                                    self._setup_pullback_marker[code] = int(marker)

                                rebreak_level = breakout_level + (float(atr) * float(self.pullback_rebreak_buffer_atr_mult))
                                pullback_marker = int(self._setup_pullback_marker.get(code, -1))
                                if (
                                    bool(self._setup_pullback_seen.get(code, False))
                                    and int(marker) > pullback_marker
                                    and float(price) > rebreak_level
                                    and can_entry
                                    and self.cooldown.allow(code)
                                ):
                                    cash = int(max(0.0, float(self.buy_cash) * float(self.stage_multipliers[0])))
                                    qty = self.order_sizer.buy_quantity(cash, price)
                                    if qty > 0:
                                        reason_str = self._build_entry_reason(
                                            f"PULLBACK_REBREAK {self.breakout_period}",
                                            adx,
                                            cci,
                                        )
                                        signals.append(
                                            TradeSignal(
                                                code=code,
                                                side="BUY",
                                                quantity=qty,
                                                reason=reason_str,
                                                price=price,
                                                tag=f"{self._tag_prefix()}:ENTRY_STAGE_0",
                                            )
                                        )
                                        self.cooldown.mark(code)
                                        self._pending_stage[code] = 0
                                        self._pending_price[code] = float(price)
                                        self._pending_qty[code] = int(qty)
                                        self._pending_base_qty[code] = int(position_qty)
                                        self._retry_count[code] = 0
                                        self._last_signal_candle[code] = marker
                                        self._entry_price.setdefault(code, float(price))
                                        self._peak_price[code] = max(self._peak_price.get(code, float(price)), float(price))
                                        self._reset_pullback_setup(code)
                elif (
                    float(price) > float(entry_high)
                    and can_entry
                    and self.cooldown.allow(code)
                ):
                    cash = int(max(0.0, float(self.buy_cash) * float(self.stage_multipliers[0])))
                    qty = self.order_sizer.buy_quantity(cash, price)
                    if qty > 0:
                        reason_str = self._build_entry_reason(f"ENTRY {self.breakout_period}", adx, cci)
                        signals.append(
                            TradeSignal(
                                code=code,
                                side="BUY",
                                quantity=qty,
                                reason=reason_str,
                                price=price,
                                tag=f"{self._tag_prefix()}:ENTRY_STAGE_0",
                            )
                        )
                        self.cooldown.mark(code)
                        self._pending_stage[code] = 0
                        self._pending_price[code] = float(price)
                        self._pending_qty[code] = int(qty)
                        self._pending_base_qty[code] = int(position_qty)
                        self._retry_count[code] = 0
                        self._last_signal_candle[code] = marker
                        self._entry_price.setdefault(code, float(price))
                        self._peak_price[code] = max(self._peak_price.get(code, float(price)), float(price))

        if signals and any(sig.side == "SELL" for sig in signals):
            self._pending_stage.pop(code, None)
            self._pending_price.pop(code, None)
            self._pending_qty.pop(code, None)
            self._pending_base_qty.pop(code, None)
            self._retry_count.pop(code, None)

        highs.append(int(high))
        lows.append(int(low))
        keep = max(self.breakout_period, self.exit_period) * 4
        if len(highs) > keep:
            del highs[:-keep]
        if len(lows) > keep:
            del lows[:-keep]

        self._last_position_qty[code] = int(position_qty)
        self._had_position[code] = in_position
        return signals

    def on_order_retry(self, code: str, stage: int) -> None:
        self._retry_count[code] = int(self._retry_count.get(code, 0)) + 1
        self._pending_stage[code] = int(stage)

    def on_order_retry_exhausted(self, code: str, stage: int) -> None:
        current = self._pending_stage.get(code)
        if current is not None and int(current) == int(stage):
            self._pending_stage.pop(code, None)
            self._pending_price.pop(code, None)
            self._pending_qty.pop(code, None)
            self._pending_base_qty.pop(code, None)

    def on_order_filled(self, code: str, side: str, stage: Optional[int] = None, price: Optional[float] = None) -> None:
        side_u = str(side or "").upper()
        if side_u == "SELL":
            self.reset_code(code)
            return

        if side_u != "BUY":
            return
        resolved_stage = stage
        if resolved_stage is None:
            resolved_stage = self._pending_stage.get(code)
        if resolved_stage is None:
            return
        stage_i = int(resolved_stage)
        self._stage[code] = max(int(self._stage.get(code, -1)), stage_i)
        fill_price = float(price) if price is not None and float(price) > 0 else float(
            self._pending_price.get(code, self._last_add_price.get(code, 0.0))
        )
        if fill_price > 0:
            self._entry_price.setdefault(code, fill_price)
            self._last_add_price[code] = fill_price
            self._peak_price[code] = max(self._peak_price.get(code, fill_price), fill_price)
        self._pending_stage.pop(code, None)
        self._pending_price.pop(code, None)
        self._pending_qty.pop(code, None)
        self._pending_base_qty.pop(code, None)
        self._retry_count[code] = 0

    def reset_code(self, code: str) -> None:
        self._high_hist.pop(code, None)
        self._low_hist.pop(code, None)
        self._atr_trackers.pop(code, None)
        self._adx_trackers.pop(code, None)
        self._cci_trackers.pop(code, None)
        self._last_sell_time.pop(code, None)
        self._entry_price.pop(code, None)
        self._last_add_price.pop(code, None)
        self._peak_price.pop(code, None)
        self._stage.pop(code, None)
        self._pending_stage.pop(code, None)
        self._pending_price.pop(code, None)
        self._pending_qty.pop(code, None)
        self._pending_base_qty.pop(code, None)
        self._retry_count.pop(code, None)
        self._last_signal_candle.pop(code, None)
        self._candle_seq.pop(code, None)
        self._last_position_qty.pop(code, None)
        self._had_position.pop(code, None)
        self._exit_confirm_donchian.pop(code, None)
        self._exit_confirm_atr.pop(code, None)
        self._donchian_exit_used.pop(code, None)
        self._reset_pullback_setup(code)

    @staticmethod
    def _shift_price_by_hoga(base_price: float, steps: int) -> float:
        """기준가를 호가 단위로 지정 단계만큼 위로 이동한다."""
        price = max(1, int(round(float(base_price))))
        for _ in range(max(0, int(steps))):
            price += LivermorePyramidStrategy._get_hoga_unit(price)
        return float(price)

    @staticmethod
    def _get_hoga_unit(price: int) -> int:
        """가격대별 호가 단위를 반환한다."""
        if price < 2_000:
            return 1
        if price < 5_000:
            return 5
        if price < 20_000:
            return 10
        if price < 50_000:
            return 50
        if price < 200_000:
            return 100
        if price < 500_000:
            return 500
        return 1_000


    def seed_history(self, code: str, highs: List[int], lows: List[int], closes: List[int]) -> None:
        """이전 캔들 데이터 배열을 받아 초기 상태(고점/저점, ATR, ADX)를 워밍업한다."""
        self.reset_code(code)
        
        hist_h = []
        hist_l = []
        keep = max(self.breakout_period, self.exit_period) * 4
        
        tracker = _AtrTracker(period=self.atr_period)
        self._atr_trackers[code] = tracker

        adx_t = None
        if self.use_adx_filter:
            adx_t = AdxTracker(period=self.adx_period)
            self._adx_trackers[code] = adx_t
        cci_t = None
        if self.use_cci_filter:
            cci_t = CciTracker(period=self.cci_period)
            self._cci_trackers[code] = cci_t

        for h, l, c in zip(highs, lows, closes):
            hist_h.append(int(h))
            hist_l.append(int(l))
            tracker.update(float(h), float(l), float(c))
            if adx_t is not None:
                adx_t.update(float(h), float(l), float(c))
            if cci_t is not None:
                cci_t.update(float(h), float(l), float(c))

        if len(hist_h) > keep:
            hist_h = hist_h[-keep:]
        if len(hist_l) > keep:
            hist_l = hist_l[-keep:]

        self._high_hist[code] = hist_h
        self._low_hist[code] = hist_l


@dataclass
class PullbackTrendStrategy(LivermorePyramidStrategy):
    """눌림 이후 재돌파만 진입하는 보수형 추세추종 전략."""

    name: str = field(init=False, default="pullback_trend")
    label: str = field(init=False, default="눌림목 추세추종")

    def __post_init__(self) -> None:
        self.entry_mode = "pullback_rebreakout"
        self.donchian_exit_ratio = 1.0
        self.pyramiding_enabled = False
        self.stage_multipliers = [1.0]
        super().__post_init__()


@dataclass
class LivermorePullbackPyramidStrategy(LivermorePyramidStrategy):
    """눌림 후 재돌파로만 진입하는 Livermore 변형 전략."""

    name: str = field(init=False, default="livermore_pullback_pyramid")
    label: str = field(init=False, default="리버모어 눌림목 피라미딩")

    def __post_init__(self) -> None:
        self.entry_mode = "pullback_rebreakout"
        super().__post_init__()


def list_strategies() -> List[dict]:
    """전략 목록을 반환한다."""
    return [
        {"name": RsiStrategy.name, "label": RsiStrategy.label},
        {"name": FailureSwingStrategy.name, "label": FailureSwingStrategy.label},
        {"name": AdaptiveStrategy.name, "label": AdaptiveStrategy.label},
        {"name": AdxDmiStrategy.name, "label": AdxDmiStrategy.label},
        {"name": DonchianBreakoutStrategy.name, "label": DonchianBreakoutStrategy.label},
        {"name": PullbackTrendStrategy.name, "label": PullbackTrendStrategy.label},
        {"name": LivermorePyramidStrategy.name, "label": LivermorePyramidStrategy.label},
        {"name": LivermorePullbackPyramidStrategy.name, "label": LivermorePullbackPyramidStrategy.label},
    ]


def create_strategy(
    name: str,
    settings,
    cooldown: CooldownTracker,
    order_sizer: OrderSizer,
    market_hours: MarketHours,
):
    """전략 인스턴스를 생성한다."""
    volatility_period = getattr(settings, "volatility_period", 14)
    volatility_threshold = getattr(settings, "volatility_threshold", 1.5)
    
    if name == AdaptiveStrategy.name:
        rsi = RsiStrategy(
            overbought=settings.rsi_overbought,
            sell_half=settings.rsi_sell_half,
            sell_all=settings.rsi_sell_all,
            buy_cash=settings.buy_cash,
            cooldown=cooldown,
            order_sizer=order_sizer,
            market_hours=market_hours,
            grid_step_percent=getattr(settings, "grid_step_percent", 1.3),
            stage_multipliers=list(getattr(settings, "rsi_stage_multipliers", [1.0, 1.0, 0.8, 0.6, 0.4, 0.2])),
            pyramiding_enabled=bool(getattr(settings, "rsi_pyramiding_enabled", True)),
            entry_atr_mult=float(getattr(settings, "rsi_entry_atr_mult", getattr(settings, "rsi_add_atr_mult", 0.0))),
            add_atr_mult=float(getattr(settings, "rsi_add_atr_mult", 0.0)),
            atr_trailing_mult=float(getattr(settings, "rsi_atr_trailing_mult", 0.0)),
            atr_buffer_mult=float(getattr(settings, "rsi_atr_buffer_mult", 0.0)),
            atr_period=int(getattr(settings, "rsi_atr_period", 14)),
            profit_protect_atr_mult=float(getattr(settings, "rsi_profit_protect_atr_mult", 0.0)),
            use_adx_filter=bool(getattr(settings, "rsi_use_adx_filter", False)),
            adx_period=int(getattr(settings, "rsi_adx_period", getattr(settings, "adx_period", 14))),
            adx_threshold=float(getattr(settings, "rsi_adx_threshold", getattr(settings, "adx_threshold", 25.0))),
            use_cci_filter=bool(getattr(settings, "rsi_use_cci_filter", False)),
            cci_period=int(getattr(settings, "rsi_cci_period", 20)),
            cci_entry_threshold=float(getattr(settings, "rsi_cci_entry_threshold", 0.0)),
            cci_add_threshold=float(getattr(settings, "rsi_cci_add_threshold", 100.0)),
        )
        fs = FailureSwingStrategy(
            buy_threshold=getattr(settings, "failure_buy_rsi", 30.0),
            sell_threshold=getattr(settings, "failure_sell_rsi", 60.0),
            buy_cash=settings.buy_cash,
            cooldown=cooldown,
            order_sizer=order_sizer,
            market_hours=market_hours,
        )
        return AdaptiveStrategy(
            rsi_strategy=rsi,
            failure_swing_strategy=fs,
            volatility_period=volatility_period,
            volatility_threshold=volatility_threshold,
            adx_period=getattr(settings, "adx_period", 14),
            adx_threshold=getattr(settings, "adx_threshold", 25.0),
            scalp_lookback=getattr(settings, "adaptive_scalp_lookback", 3),
            scalp_breakout_buffer_pct=getattr(settings, "adaptive_scalp_breakout_buffer_pct", 0.10),
            scalp_min_momentum_bars=getattr(settings, "adaptive_scalp_min_momentum_bars", 2),
            scalp_min_volatility_pct=getattr(settings, "adaptive_scalp_min_volatility_pct", 0.08),
            scalp_max_chase_atr_mult=getattr(settings, "adaptive_scalp_max_chase_atr_mult", 2.5),
            scalp_stop_atr_mult=getattr(settings, "adaptive_scalp_stop_atr_mult", 1.4),
            scalp_trailing_atr_mult=getattr(settings, "adaptive_scalp_trailing_atr_mult", 2.0),
            scalp_trailing_arm_atr_mult=getattr(settings, "adaptive_scalp_trailing_arm_atr_mult", 1.0),
            scalp_take_profit_atr_mult=getattr(settings, "adaptive_scalp_take_profit_atr_mult", 2.6),
            scalp_take_profit_pct=getattr(settings, "adaptive_scalp_take_profit_pct", 1.6),
        )
    elif name == AdxDmiStrategy.name:
        return AdxDmiStrategy(
            adx_period=getattr(settings, "adx_period", 14),
            adx_threshold=getattr(settings, "adx_threshold", 25.0),
            buy_cash=settings.buy_cash,
            cooldown=cooldown,
            order_sizer=order_sizer,
            market_hours=market_hours,
            adx_weak_threshold=getattr(settings, "adx_weak_threshold", 18.0),
            adx_exit_falling_bars=getattr(settings, "adx_exit_falling_bars", 3),
            atr_trailing_mult=getattr(settings, "atr_trailing_mult", 2.5),
            adx_use_weak_exit=bool(getattr(settings, "adx_use_weak_exit", False)),
        )
    elif name == DonchianBreakoutStrategy.name:
        return DonchianBreakoutStrategy(
            breakout_period=getattr(settings, "donchian_breakout_period", 20),
            exit_period=getattr(settings, "donchian_exit_period", 10),
            buy_cash=settings.buy_cash,
            cooldown=cooldown,
            order_sizer=order_sizer,
            market_hours=market_hours,
        )
    elif name == PullbackTrendStrategy.name:
        return PullbackTrendStrategy(
            breakout_period=getattr(settings, "donchian_breakout_period", 20),
            exit_period=getattr(settings, "donchian_exit_period", 10),
            add_atr_mult=float(getattr(settings, "livermore_add_atr_mult", 0.8)),
            add_min_hoga_gap=int(getattr(settings, "livermore_add_min_hoga_gap", 5)),
            atr_trailing_mult=float(getattr(settings, "atr_trailing_mult", getattr(settings, "livermore_atr_trailing_mult", 2.5))),
            atr_buffer_mult=float(getattr(settings, "livermore_atr_buffer_mult", 0.5)),
            exit_confirm_bars=int(getattr(settings, "livermore_exit_confirm_bars", 2)),
            donchian_exit_ratio=1.0,
            stage_multipliers=[1.0],
            buy_cash=settings.buy_cash,
            cooldown=cooldown,
            order_sizer=order_sizer,
            market_hours=market_hours,
            atr_period=int(getattr(settings, "adx_period", 14)),
            use_adx_filter=True,
            adx_period=int(getattr(settings, "adx_period", 14)),
            adx_threshold=float(getattr(settings, "adx_threshold", 25.0)),
            use_cci_filter=bool(getattr(settings, "livermore_use_cci_filter", False)),
            cci_period=int(getattr(settings, "livermore_cci_period", 20)),
            cci_entry_threshold=float(getattr(settings, "livermore_cci_entry_threshold", 100.0)),
            cci_add_threshold=float(getattr(settings, "livermore_cci_add_threshold", 100.0)),
            pullback_retrace_atr_mult=float(getattr(settings, "pullback_retrace_atr_mult", 0.8)),
            pullback_rebreak_buffer_atr_mult=float(getattr(settings, "pullback_rebreak_buffer_atr_mult", 0.2)),
            pullback_invalidate_atr_mult=float(getattr(settings, "pullback_invalidate_atr_mult", 0.5)),
            pullback_max_bars=int(getattr(settings, "pullback_max_bars", 6)),
        )
    elif name == LivermorePyramidStrategy.name:
        return LivermorePyramidStrategy(
            breakout_period=getattr(settings, "livermore_breakout_period", 20),
            exit_period=getattr(settings, "livermore_exit_period", 10),
            add_atr_mult=float(getattr(settings, "livermore_add_atr_mult", 0.8)),
            add_min_hoga_gap=int(getattr(settings, "livermore_add_min_hoga_gap", 5)),
            atr_trailing_mult=float(getattr(settings, "livermore_atr_trailing_mult", 2.5)),
            atr_buffer_mult=float(getattr(settings, "livermore_atr_buffer_mult", 0.5)),
            exit_confirm_bars=int(getattr(settings, "livermore_exit_confirm_bars", 2)),
            donchian_exit_ratio=float(getattr(settings, "livermore_donchian_exit_ratio", 0.5)),
            stage_multipliers=list(getattr(settings, "livermore_stage_multipliers", [1.0, 1.0, 0.8, 0.6, 0.4])),
            pyramiding_enabled=bool(getattr(settings, "livermore_pyramiding_enabled", True)),
            buy_cash=settings.buy_cash,
            cooldown=cooldown,
            order_sizer=order_sizer,
            market_hours=market_hours,
            atr_period=int(getattr(settings, "adx_period", 14)),
            use_adx_filter=bool(getattr(settings, "livermore_use_adx_filter", False)),
            adx_period=int(getattr(settings, "livermore_adx_period", getattr(settings, "adx_period", 14))),
            adx_threshold=float(getattr(settings, "livermore_adx_threshold", getattr(settings, "adx_threshold", 25.0))),
            use_cci_filter=bool(getattr(settings, "livermore_use_cci_filter", False)),
            cci_period=int(getattr(settings, "livermore_cci_period", 20)),
            cci_entry_threshold=float(getattr(settings, "livermore_cci_entry_threshold", 100.0)),
            cci_add_threshold=float(getattr(settings, "livermore_cci_add_threshold", 100.0)),
            pullback_retrace_atr_mult=float(getattr(settings, "pullback_retrace_atr_mult", 0.8)),
            pullback_rebreak_buffer_atr_mult=float(getattr(settings, "pullback_rebreak_buffer_atr_mult", 0.2)),
            pullback_invalidate_atr_mult=float(getattr(settings, "pullback_invalidate_atr_mult", 0.5)),
            pullback_max_bars=int(getattr(settings, "pullback_max_bars", 6)),
        )
    elif name == LivermorePullbackPyramidStrategy.name:
        return LivermorePullbackPyramidStrategy(
            breakout_period=getattr(settings, "livermore_breakout_period", 20),
            exit_period=getattr(settings, "livermore_exit_period", 10),
            add_atr_mult=float(getattr(settings, "livermore_add_atr_mult", 0.8)),
            add_min_hoga_gap=int(getattr(settings, "livermore_add_min_hoga_gap", 5)),
            atr_trailing_mult=float(getattr(settings, "livermore_atr_trailing_mult", 2.5)),
            atr_buffer_mult=float(getattr(settings, "livermore_atr_buffer_mult", 0.5)),
            exit_confirm_bars=int(getattr(settings, "livermore_exit_confirm_bars", 2)),
            donchian_exit_ratio=float(getattr(settings, "livermore_donchian_exit_ratio", 0.5)),
            stage_multipliers=list(getattr(settings, "livermore_stage_multipliers", [1.0, 1.0, 0.8, 0.6, 0.4])),
            pyramiding_enabled=bool(getattr(settings, "livermore_pyramiding_enabled", True)),
            buy_cash=settings.buy_cash,
            cooldown=cooldown,
            order_sizer=order_sizer,
            market_hours=market_hours,
            atr_period=int(getattr(settings, "adx_period", 14)),
            use_adx_filter=bool(getattr(settings, "livermore_use_adx_filter", False)),
            adx_period=int(getattr(settings, "livermore_adx_period", getattr(settings, "adx_period", 14))),
            adx_threshold=float(getattr(settings, "livermore_adx_threshold", getattr(settings, "adx_threshold", 25.0))),
            use_cci_filter=bool(getattr(settings, "livermore_use_cci_filter", False)),
            cci_period=int(getattr(settings, "livermore_cci_period", 20)),
            cci_entry_threshold=float(getattr(settings, "livermore_cci_entry_threshold", 100.0)),
            cci_add_threshold=float(getattr(settings, "livermore_cci_add_threshold", 100.0)),
            pullback_retrace_atr_mult=float(getattr(settings, "pullback_retrace_atr_mult", 0.8)),
            pullback_rebreak_buffer_atr_mult=float(getattr(settings, "pullback_rebreak_buffer_atr_mult", 0.2)),
            pullback_invalidate_atr_mult=float(getattr(settings, "pullback_invalidate_atr_mult", 0.5)),
            pullback_max_bars=int(getattr(settings, "pullback_max_bars", 6)),
        )
    elif name == FailureSwingStrategy.name:
        return FailureSwingStrategy(
            buy_threshold=getattr(settings, "failure_buy_rsi", 30.0),
            sell_threshold=getattr(settings, "failure_sell_rsi", 60.0),
            buy_cash=settings.buy_cash,
            cooldown=cooldown,
            order_sizer=order_sizer,
            market_hours=market_hours,
        )
    return RsiStrategy(
        overbought=settings.rsi_overbought,
        sell_half=settings.rsi_sell_half,
        sell_all=settings.rsi_sell_all,
        buy_cash=settings.buy_cash,
        cooldown=cooldown,
        order_sizer=order_sizer,
        market_hours=market_hours,
        grid_step_percent=getattr(settings, "grid_step_percent", 1.3),
        stage_multipliers=list(getattr(settings, "rsi_stage_multipliers", [1.0, 1.0, 0.8, 0.6, 0.4, 0.2])),
        pyramiding_enabled=bool(getattr(settings, "rsi_pyramiding_enabled", True)),
        entry_atr_mult=float(getattr(settings, "rsi_entry_atr_mult", getattr(settings, "rsi_add_atr_mult", 0.0))),
        add_atr_mult=float(getattr(settings, "rsi_add_atr_mult", 0.0)),
        atr_trailing_mult=float(getattr(settings, "rsi_atr_trailing_mult", 0.0)),
        atr_buffer_mult=float(getattr(settings, "rsi_atr_buffer_mult", 0.0)),
        atr_period=int(getattr(settings, "rsi_atr_period", 14)),
        profit_protect_atr_mult=float(getattr(settings, "rsi_profit_protect_atr_mult", 0.0)),
        use_adx_filter=bool(getattr(settings, "rsi_use_adx_filter", False)),
        adx_period=int(getattr(settings, "rsi_adx_period", getattr(settings, "adx_period", 14))),
        adx_threshold=float(getattr(settings, "rsi_adx_threshold", getattr(settings, "adx_threshold", 25.0))),
        use_cci_filter=bool(getattr(settings, "rsi_use_cci_filter", False)),
        cci_period=int(getattr(settings, "rsi_cci_period", 20)),
        cci_entry_threshold=float(getattr(settings, "rsi_cci_entry_threshold", 0.0)),
        cci_add_threshold=float(getattr(settings, "rsi_cci_add_threshold", 100.0)),
    )
