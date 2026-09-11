from __future__ import annotations

import json
from pathlib import Path


def _load_setting(name: str, default: float) -> float:
    try:
        data = json.loads((Path.cwd() / "settings.json").read_text(encoding="utf-8-sig"))
        return float(data.get(name, default))
    except Exception:
        return float(default)


def _patch_adaptive_scalp() -> None:
    try:
        from use_cases.strategy import AdaptiveStrategy
    except Exception:
        return

    adx_threshold = _load_setting("adaptive_scalp_adx_threshold", 20.0)

    original_entry = getattr(AdaptiveStrategy, "_build_scalp_entry_signal", None)
    if original_entry is not None and not getattr(original_entry, "_adaptive_adx_guard", False):
        def guarded_entry(self, code, price, position_qty, atr, adx, volatility):
            # Dedicated scalp ADX floor. This is independent of the global ADX threshold.
            if adx is None or float(adx) < adx_threshold:
                return None
            return original_entry(self, code, price, position_qty, atr, adx, volatility)
        guarded_entry._adaptive_adx_guard = True
        AdaptiveStrategy._build_scalp_entry_signal = guarded_entry

    original_history = getattr(AdaptiveStrategy, "_update_scalp_history", None)
    if original_history is not None and not getattr(original_history, "_price_history_fix", False):
        def patched_history(self, code, price, high, low):
            # The original scalp logic checks recent price momentum, but the price
            # history was not populated once ATR became available. Keep it populated
            # on every candle so the momentum gate can actually pass.
            prices = self._price_history.get(code, [])
            prices.append(int(price))
            max_len = max(
                int(getattr(self, "volatility_period", 14)),
                int(getattr(self, "scalp_lookback", 5))
                + int(getattr(self, "scalp_min_momentum_bars", 3))
                + 2,
            )
            if len(prices) > max_len:
                del prices[:-max_len]
            self._price_history[code] = prices
            original_history(self, code, price, high, low)
        patched_history._price_history_fix = True
        AdaptiveStrategy._update_scalp_history = patched_history


def _patch_engine_ui_isolation() -> None:
    try:
        from use_cases.trading_engine import TradingEngine
        from use_cases.tick_aggregator import TickAggregator
        from use_cases.time_aggregator import TimeAggregator
    except Exception:
        return

    def change_candle_config(self, source, value):
        source = str(source or "").lower()
        value = int(value)
        if source not in ("tick", "minute") or value <= 0:
            return
        with self._aggregator_lock:
            if source == "tick":
                self._settings.candle_source = "tick"
                self._settings.ticks_per_candle = value
                self._aggregator = TickAggregator(ticks_per_candle=value)
                label = f"{value}틱봉"
            else:
                self._settings.candle_source = "minute"
                self._settings.minutes_per_candle = value
                self._aggregator = TimeAggregator(minutes_per_candle=value)
                label = f"{value}분봉"
            with self._rsi_trackers_lock:
                self._rsi_trackers.clear()
                self._last_rsi_values.clear()
        self._last_rsi = "-"
        # Candle selection changes only the aggregation timeframe.
        # RSI/ADX/Donchian/Livermore parameters remain untouched.
        self._rebuild_strategy(self._strategy_name)
        self._logger.info("캔들 기준 변경: %s (기타 전략 설정 유지)", label)
        self._bump_ui_version("candle")
        self._publish_status()

    def change_rsi_period(self, period):
        period = int(period)
        if period <= 0:
            return
        if int(getattr(self._settings, "rsi_period", 14)) == period:
            return
        self._settings.rsi_period = period
        with self._rsi_trackers_lock:
            self._rsi_trackers.clear()
            self._last_rsi_values.clear()
        self._last_rsi = "-"
        # RSI period changes only RSI period; do not copy it into other strategies.
        self._rebuild_strategy(self._strategy_name)
        self._logger.info("RSI 기간 변경: %d (기타 전략 기간 유지)", period)
        self._bump_ui_version("rsi_period")
        self._publish_status()

    change_candle_config._isolated = True
    change_rsi_period._isolated = True
    TradingEngine.change_candle_config = change_candle_config
    TradingEngine.change_rsi_period = change_rsi_period


_patch_adaptive_scalp()
_patch_engine_ui_isolation()
