import datetime
from collections import deque

from app.settings import Settings
from app.status_bus import StatusBus
from domain.entities import Candle, Tick, TradeSignal
from domain.indicators import RsiTracker
from use_cases.trading_engine import TradingEngine
from use_cases.time_aggregator import TimeAggregator
from use_cases.tick_aggregator import TickAggregator


class DummyClock:
    def __init__(self) -> None:
        self._now = datetime.datetime(2026, 2, 10, 10, 0, 0)

    def now(self) -> datetime.datetime:
        return self._now


class DummyLogger:
    def __init__(self) -> None:
        self.errors = []

    def info(self, message, *args) -> None:
        return None

    def warning(self, message, *args) -> None:
        return None

    def error(self, message, *args) -> None:
        self.errors.append((message, args))


class DummyGateway:
    def get_master_code_name(self, code: str) -> str:
        return code


class MinuteHistoryGateway(DummyGateway):
    def request_minute_history(self, code: str, interval: int = 1, count: int = 20):
        records = []
        for i in range(count):
            records.append(
                {
                    "체결시간": f"10{i:02d}00",
                    "시가": 1000 + i,
                    "고가": 1005 + i,
                    "저가": 995 + i,
                    "현재가": 1002 + i,
                    "거래량": 100 + i,
                }
            )
        return records


class OrderGateway(DummyGateway):
    def __init__(self) -> None:
        self.orders = []

    def send_order(
        self,
        rqname: str,
        screen: str,
        acc_no: str,
        order_type: int,
        code: str,
        quantity: int,
        price: int,
        hoga_gb: str,
        order_no: str = "",
    ) -> None:
        self.orders.append((code, quantity, order_type))


def test_change_candle_config_switches_aggregator():
    settings = Settings()
    engine = TradingEngine(settings, DummyGateway(), DummyLogger(), StatusBus(), DummyClock())

    engine.change_candle_config("minute", 3)

    assert settings.candle_source == "minute"
    assert settings.minutes_per_candle == 3
    assert isinstance(engine._aggregator, TimeAggregator)

    engine.change_candle_config("tick", 20)

    assert settings.candle_source == "tick"
    assert settings.ticks_per_candle == 20
    assert isinstance(engine._aggregator, TickAggregator)


def test_change_rsi_period_updates_setting_and_resets_state():
    settings = Settings()
    engine = TradingEngine(settings, DummyGateway(), DummyLogger(), StatusBus(), DummyClock())
    engine._rsi_trackers["000001"] = object()
    engine._last_rsi_values["000001"] = 55.0
    engine._last_rsi = "테스트 RSI 55.00"

    engine.change_rsi_period(7)

    assert settings.rsi_period == 7
    assert settings.minute_default_livermore_period == 7
    assert settings.livermore_breakout_period == 7
    assert settings.livermore_exit_period == 7
    assert settings.livermore_adx_period == 7
    assert settings.donchian_breakout_period == 7
    assert settings.donchian_exit_period == 7
    assert settings.rsi_adx_period == 7
    assert engine._rsi_trackers == {}
    assert engine._last_rsi_values == {}
    assert engine._last_rsi == "-"


def test_change_rsi_period_rebuilds_current_strategy_with_new_periods():
    settings = Settings()
    settings.strategy_name = "livermore_pyramid"
    engine = TradingEngine(settings, DummyGateway(), DummyLogger(), StatusBus(), DummyClock())

    engine.change_rsi_period(6)

    assert getattr(engine._strategy, "breakout_period", None) == 6
    assert getattr(engine._strategy, "exit_period", None) == 6
    assert getattr(engine._strategy, "adx_period", None) == 6


def test_change_rsi_period_rejects_non_positive_value():
    settings = Settings()
    logger = DummyLogger()
    engine = TradingEngine(settings, DummyGateway(), logger, StatusBus(), DummyClock())

    engine.change_rsi_period(0)

    assert settings.rsi_period == 14
    assert logger.errors


def test_change_rsi_thresholds_updates_settings_and_strategy():
    settings = Settings()
    engine = TradingEngine(settings, DummyGateway(), DummyLogger(), StatusBus(), DummyClock())

    engine.change_rsi_thresholds(72.5, 42.0, 31.0)

    assert settings.rsi_overbought == 72.5
    assert settings.rsi_sell_half == 42.0
    assert settings.rsi_sell_all == 31.0
    assert getattr(engine._strategy, "overbought", None) == 72.5
    assert getattr(engine._strategy, "sell_half", None) == 42.0
    assert getattr(engine._strategy, "sell_all", None) == 31.0


def test_change_rsi_thresholds_rejects_out_of_range_values():
    settings = Settings()
    logger = DummyLogger()
    engine = TradingEngine(settings, DummyGateway(), logger, StatusBus(), DummyClock())

    engine.change_rsi_thresholds(101.0, 42.0, 31.0)

    assert settings.rsi_overbought == 70.0
    assert logger.errors


def test_change_candle_config_minute_applies_default_rsi_values():
    settings = Settings()
    settings.rsi_period = 14
    settings.rsi_overbought = 70.0
    settings.rsi_sell_half = 35.0
    settings.rsi_sell_all = 25.0
    engine = TradingEngine(settings, DummyGateway(), DummyLogger(), StatusBus(), DummyClock())

    engine.change_candle_config("minute", 1)

    assert settings.candle_source == "minute"
    assert settings.rsi_period == settings.minute_default_rsi_period
    assert settings.rsi_overbought == 70.0
    assert settings.rsi_sell_half == 59.0
    assert settings.rsi_sell_all == 39.0
    assert getattr(engine._strategy, "overbought", 0.0) == 70.0


def test_change_candle_config_minute_seeds_rsi_from_recent_ticks():
    settings = Settings()
    settings.rsi_period = 5
    engine = TradingEngine(settings, DummyGateway(), DummyLogger(), StatusBus(), DummyClock())
    code = "000001"
    engine._watchlist.apply_condition_snapshot({code})
    minute_history = deque(maxlen=engine._recent_tick_buffer_size)
    for i in range(20):
        minute_history.append(
            Candle(
                code=code,
                open=1000 + i,
                high=1005 + i,
                low=995 + i,
                close=1000 + i,
                volume=100 + i,
                tick_count=20,
                end_time=f"100{i:02d}00",
            )
        )
    engine._recent_minute_candles_by_code[code] = minute_history

    engine.change_candle_config("minute", 1)

    assert code in engine._rsi_trackers
    assert engine._last_rsi_values.get(code) is not None


def test_warm_up_rsi_prefers_minute_history_when_minute_mode():
    settings = Settings()
    settings.candle_source = "minute"
    settings.minutes_per_candle = 1
    settings.rsi_period = 5
    settings.minute_backfill_candle_count = 20
    engine = TradingEngine(settings, MinuteHistoryGateway(), DummyLogger(), StatusBus(), DummyClock())

    engine._warm_up_rsi("000001")

    assert "000001" in engine._rsi_trackers
    assert engine._last_rsi_values.get("000001") is not None


def test_in_progress_minute_candle_runs_strategy_preview_realtime():
    settings = Settings()
    settings.candle_source = "minute"
    settings.minutes_per_candle = 1
    gateway = OrderGateway()
    engine = TradingEngine(settings, gateway, DummyLogger(), StatusBus(), DummyClock())
    engine._allow_trading = True
    engine._account_no = "12345678"

    class PreviewStrategy:
        requires_rsi = False
        name = "preview_test"

        def __deepcopy__(self, memo):
            return self

        def on_rsi_update(self, code, rsi, price, position_qty, high=None, low=None):
            return [
                TradeSignal(
                    code=code,
                    side="BUY",
                    quantity=1,
                    reason="preview buy",
                    price=price,
                    tag="preview:test",
                )
            ]

        def reset_code(self, code):
            return None

    engine._strategy = PreviewStrategy()
    engine._strategy_name = "preview_test"
    tick = Tick(code="000001", price=1000, volume=10, time="101500")
    engine._last_watchset = {"000001"}
    engine._watchlist.apply_condition_snapshot({"000001"})

    lock = engine._get_aggregator_lock_for("000001")
    with lock:
        engine._aggregator.update(tick)
    engine._evaluate_in_progress_candle("000001")

    assert len(gateway.orders) == 1


def test_in_progress_minute_livermore_preview_sends_orders_realtime():
    settings = Settings()
    settings.candle_source = "minute"
    settings.minutes_per_candle = 1
    gateway = OrderGateway()
    engine = TradingEngine(settings, gateway, DummyLogger(), StatusBus(), DummyClock())
    engine._allow_trading = True
    engine._account_no = "12345678"

    class PreviewLivermoreStrategy:
        requires_rsi = False
        name = "livermore_pyramid"

        def __deepcopy__(self, memo):
            return self

        def on_rsi_update(self, code, rsi, price, position_qty, high=None, low=None):
            return [
                TradeSignal(
                    code=code,
                    side="BUY",
                    quantity=1,
                    reason="preview livermore buy",
                    price=price,
                    tag="livermore:ENTRY_STAGE_0",
                )
            ]

        def reset_code(self, code):
            return None

    engine._strategy = PreviewLivermoreStrategy()
    engine._strategy_name = "livermore_pyramid"
    engine._last_watchset = {"000001"}
    engine._watchlist.apply_condition_snapshot({"000001"})

    lock = engine._get_aggregator_lock_for("000001")
    with lock:
        engine._aggregator.update(Tick(code="000001", price=1000, volume=0, time="101500"))
    engine._evaluate_in_progress_candle("000001")

    assert len(gateway.orders) == 1


def test_in_progress_minute_rsi_grid_preview_does_not_send_orders_until_candle_confirms():
    settings = Settings()
    settings.candle_source = "minute"
    settings.minutes_per_candle = 1
    gateway = OrderGateway()
    engine = TradingEngine(settings, gateway, DummyLogger(), StatusBus(), DummyClock())
    engine._allow_trading = True
    engine._account_no = "12345678"

    class PreviewRsiStrategy:
        requires_rsi = True
        name = "rsi_grid"

        def __deepcopy__(self, memo):
            return self

        def on_rsi_update(self, code, rsi, price, position_qty, high=None, low=None):
            return [
                TradeSignal(
                    code=code,
                    side="BUY",
                    quantity=1,
                    reason="preview rsi buy",
                    price=price,
                    tag="rsi:preview:test",
                )
            ]

        def reset_code(self, code):
            return None

    tracker = RsiTracker(period=1)
    assert tracker.update(1000) is None
    assert tracker.update(1010) is not None

    engine._strategy = PreviewRsiStrategy()
    engine._strategy_name = "rsi_grid"
    engine._rsi_trackers["000001"] = tracker
    engine._last_watchset = {"000001"}
    engine._watchlist.apply_condition_snapshot({"000001"})

    lock = engine._get_aggregator_lock_for("000001")
    with lock:
        engine._aggregator.update(Tick(code="000001", price=1020, volume=10, time="101500"))
    engine._evaluate_in_progress_candle("000001")

    assert len(gateway.orders) == 0

    candle = Candle(
        code="000001",
        open=1000,
        high=1020,
        low=1000,
        close=1020,
        volume=10,
        tick_count=1,
        end_time="101500",
    )
    engine._handle_candle(candle)

    assert len(gateway.orders) == 1
