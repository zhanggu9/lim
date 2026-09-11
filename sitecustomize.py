from __future__ import annotations

import json
from pathlib import Path


def _patch_adaptive_scalp_adx() -> None:
    try:
        from use_cases.strategy import AdaptiveStrategy
    except Exception:
        return
    threshold = 20.0
    try:
        data = json.loads((Path.cwd() / "settings.json").read_text(encoding="utf-8-sig"))
        threshold = float(data.get("adaptive_scalp_adx_threshold", 20.0))
    except Exception:
        pass
    original = getattr(AdaptiveStrategy, "_build_scalp_entry_signal", None)
    if original is None or getattr(original, "_adaptive_adx_guard", False):
        return
    def guarded(self, code, price, position_qty, atr, adx, volatility):
        if adx is None or float(adx) < threshold:
            return None
        return original(self, code, price, position_qty, atr, adx, volatility)
    guarded._adaptive_adx_guard = True
    AdaptiveStrategy._build_scalp_entry_signal = guarded


def _patch_engine() -> None:
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
            else:
                self._settings.candle_source = "minute"
                self._settings.minutes_per_candle = value
                self._aggregator = TimeAggregator(minutes_per_candle=value)
            with self._rsi_trackers_lock:
                self._rsi_trackers.clear()
                self._last_rsi_values.clear()
        self._last_rsi = "-"
        self._rebuild_strategy(self._strategy_name)
        self._bump_ui_version("candle")
        self._publish_status()

    def change_rsi_period(self, period):
        period = int(period)
        if period <= 0 or int(getattr(self._settings, "rsi_period", 14)) == period:
            return
        self._settings.rsi_period = period
        with self._rsi_trackers_lock:
            self._rsi_trackers.clear()
            self._last_rsi_values.clear()
        self._last_rsi = "-"
        self._rebuild_strategy(self._strategy_name)
        self._bump_ui_version("rsi_period")
        self._publish_status()

    change_candle_config._isolated = True
    change_rsi_period._isolated = True
    TradingEngine.change_candle_config = change_candle_config
    TradingEngine.change_rsi_period = change_rsi_period


_patch_adaptive_scalp_adx()
_patch_engine()
