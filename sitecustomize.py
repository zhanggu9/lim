from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path


def _load_setting(name: str, default: float) -> float:
    try:
        data = json.loads((Path.cwd() / "settings.json").read_text(encoding="utf-8-sig"))
        return float(data.get(name, default))
    except Exception:
        return float(default)


def _patch_settings_persistence() -> None:
    """Never drop settings that are not explicitly listed by the legacy serializer."""
    try:
        from app.settings import Settings
    except Exception:
        return

    if getattr(Settings, "_safe_persistence_patch", False):
        return

    trend_defaults = {
        "trend_breakout_period": 10,
        "trend_exit_period": 5,
        "trend_momentum_bars": 3,
        "trend_adx_period": 14,
        "trend_adx_threshold": 20.0,
        "trend_atr_period": 14,
        "trend_stop_atr_mult": 1.0,
        "trend_trailing_atr_mult": 1.5,
        "trend_max_chase_atr_mult": 1.5,
        "trend_take_profit_pct": 1.2,
        "trend_pyramiding_enabled": False,
        "trend_add_atr_mult": 1.2,
        "trend_max_adds": 1,
    }

    original_load = Settings.load

    @classmethod
    def patched_load(cls, path: str):
        settings = original_load.__func__(cls, path)
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                for name, default in trend_defaults.items():
                    setattr(settings, name, data.get(name, default))
        except Exception:
            for name, default in trend_defaults.items():
                if not hasattr(settings, name):
                    setattr(settings, name, default)
        return settings

    def patched_to_dict(self):
        # Serialize every dataclass field so newly added strategy parameters
        # cannot disappear when the UI saves settings after a strategy change.
        result = {field.name: getattr(self, field.name) for field in fields(self)}
        for name, default in trend_defaults.items():
            result[name] = getattr(self, name, default)
        return result

    def patched_save(self, path: str) -> None:
        # Preserve unknown/future keys already present in the JSON file, then
        # overwrite only the values represented by the current Settings object.
        target = Path(path)
        existing = {}
        try:
            if target.exists():
                existing = json.loads(target.read_text(encoding="utf-8-sig"))
                if not isinstance(existing, dict):
                    existing = {}
        except Exception:
            existing = {}
        existing.update(patched_to_dict(self))
        target.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    Settings.load = patched_load
    Settings.to_dict = patched_to_dict
    Settings.save = patched_save
    Settings._safe_persistence_patch = True


def _patch_strategy_factory() -> None:
    """Add the unified trend strategy without modifying the legacy strategy implementations."""
    try:
        import use_cases.strategy as strategy_module
        import use_cases.trading_engine as engine_module
        from use_cases.trend_orchestrator import TrendOrchestrator
    except Exception:
        return

    original_factory = getattr(strategy_module, "create_strategy", None)
    if original_factory is None or getattr(original_factory, "_trend_combo_factory", False):
        return

    def create_strategy(name, settings, cooldown, order_sizer, market_hours):
        if str(name).lower() == TrendOrchestrator.name:
            return TrendOrchestrator(settings, cooldown, order_sizer, market_hours)
        return original_factory(name, settings, cooldown, order_sizer, market_hours)

    create_strategy._trend_combo_factory = True
    strategy_module.create_strategy = create_strategy
    engine_module.create_strategy = create_strategy

    original_list = getattr(strategy_module, "list_strategies", None)
    if original_list is not None and not getattr(original_list, "_trend_combo_list", False):
        def list_strategies():
            items = list(original_list())
            if not any(str(item.get("name", "")) == TrendOrchestrator.name for item in items):
                items.append({"name": TrendOrchestrator.name, "label": TrendOrchestrator.label})
            return items
        list_strategies._trend_combo_list = True
        strategy_module.list_strategies = list_strategies
        engine_module.list_strategies = list_strategies


def _patch_adaptive_scalp() -> None:
    try:
        from use_cases.strategy import AdaptiveStrategy
    except Exception:
        return

    adx_threshold = _load_setting("adaptive_scalp_adx_threshold", 20.0)
    original_entry = getattr(AdaptiveStrategy, "_build_scalp_entry_signal", None)
    if original_entry is not None and not getattr(original_entry, "_adaptive_adx_guard", False):
        def guarded_entry(self, code, price, position_qty, atr, adx, volatility):
            if adx is None or float(adx) < adx_threshold:
                return None
            return original_entry(self, code, price, position_qty, atr, adx, volatility)
        guarded_entry._adaptive_adx_guard = True
        AdaptiveStrategy._build_scalp_entry_signal = guarded_entry

    original_history = getattr(AdaptiveStrategy, "_update_scalp_history", None)
    if original_history is not None and not getattr(original_history, "_price_history_fix", False):
        def patched_history(self, code, price, high, low):
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
        self._rebuild_strategy(self._strategy_name)
        self._logger.info("캔들 기준 변경: %s (전략별 파라미터 유지)", label)
        self._bump_ui_version("candle")
        self._publish_status()

    def change_rsi_period(self, period):
        period = int(period)
        if period <= 0:
            return
        self._settings.rsi_period = period
        with self._rsi_trackers_lock:
            self._rsi_trackers.clear()
            self._last_rsi_values.clear()
        self._last_rsi = "-"
        self._rebuild_strategy(self._strategy_name)
        self._logger.info("RSI 기간 변경: %d (다른 전략 기간 유지)", period)
        self._bump_ui_version("rsi_period")
        self._publish_status()

    change_candle_config._isolated = True
    change_rsi_period._isolated = True
    TradingEngine.change_candle_config = change_candle_config
    TradingEngine.change_rsi_period = change_rsi_period


def _patch_order_intent_guard() -> None:
    """Block duplicate BUY/SELL submissions while the same order intent is unresolved."""
    try:
        from use_cases.order_intent_guard import OrderIntentGuard
        from use_cases.trading_engine import TradingEngine
    except Exception:
        return

    if getattr(TradingEngine, "_order_intent_guard_patch", False):
        return

    original_init = TradingEngine.__init__
    original_execute = TradingEngine._execute_signal
    original_clear_execution = getattr(TradingEngine, "_clear_pending_order_by_execution", None)
    original_order_status = getattr(TradingEngine, "_handle_strategy_order_status", None)

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._order_intent_guard = OrderIntentGuard()

    def patched_execute(self, signal, *args, **kwargs):
        guard = getattr(self, "_order_intent_guard", None)
        if guard is None:
            return original_execute(self, signal, *args, **kwargs)
        code = str(getattr(signal, "code", "") or "")
        side = str(getattr(signal, "side", "") or "").upper()
        if guard.is_pending(code, side):
            self._logger.info("미체결 주문 중복 차단: %s %s", self._get_name(code), side)
            return False
        if not guard.claim(code, side, self._clock.now()):
            return False
        try:
            sent = original_execute(self, signal, *args, **kwargs)
        except Exception:
            guard.release(code, side)
            raise
        if not sent:
            guard.release(code, side)
        return sent

    def patched_clear_execution(self, execution):
        result = None
        try:
            if original_clear_execution is not None:
                result = original_clear_execution(self, execution)
        finally:
            guard = getattr(self, "_order_intent_guard", None)
            if guard is not None:
                guard.release(
                    str(getattr(execution, "code", "") or ""),
                    str(getattr(execution, "side", "") or "").upper(),
                )
        return result

    def patched_order_status(self, data):
        if original_order_status is not None:
            result = original_order_status(self, data)
        else:
            result = None
        status = str(self._chejan_field(data, "913") or "").strip()
        if status and ("거부" in status or "취소" in status):
            guard = getattr(self, "_order_intent_guard", None)
            if guard is not None:
                guard.release(
                    self._normalize_chejan_code(data),
                    "SELL" if clean_int(self._chejan_field(data, "907")) == 1 else "BUY",
                )
        return result

    TradingEngine.__init__ = patched_init
    TradingEngine._execute_signal = patched_execute
    if original_clear_execution is not None:
        TradingEngine._clear_pending_order_by_execution = patched_clear_execution
    if original_order_status is not None:
        TradingEngine._handle_strategy_order_status = patched_order_status
    TradingEngine._order_intent_guard_patch = True


_patch_settings_persistence()
_patch_strategy_factory()
_patch_adaptive_scalp()
_patch_engine_ui_isolation()
_patch_order_intent_guard()
