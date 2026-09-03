import datetime

from app.settings import Settings
from app.status_bus import StatusBus
from use_cases.trading_engine import TradingEngine


class DummyClock:
    """테스트용 고정 시계."""

    def __init__(self) -> None:
        self._now = datetime.datetime(2026, 2, 23, 10, 0, 0)

    def now(self) -> datetime.datetime:
        return self._now


class DummyLogger:
    """테스트용 로거."""

    def info(self, message, *args) -> None:
        return None

    def warning(self, message, *args) -> None:
        return None

    def error(self, message, *args) -> None:
        return None


class DummyGateway:
    """엔진 테스트 최소 게이트웨이 스텁."""

    def get_master_code_name(self, code: str) -> str:
        return code

    def get_condition_name_list(self):
        return "0^COND_A;1^COND_B;"

    def stop_condition(self, screen: str, cond_name: str, index: int) -> None:
        return None

    def send_condition(self, screen: str, cond_name: str, index: int, search: int) -> None:
        return None


def _drain_last_snapshot(bus: StatusBus):
    last = None
    while True:
        snap = bus.try_get()
        if snap is None:
            break
        last = snap
    return last


def test_ui_versions_initially_zero():
    settings = Settings()
    bus = StatusBus()
    engine = TradingEngine(settings, DummyGateway(), DummyLogger(), bus, DummyClock())

    engine._publish_status()
    snapshot = _drain_last_snapshot(bus)

    assert snapshot is not None
    assert snapshot.condition_version == 0
    assert snapshot.strategy_version == 0
    assert snapshot.candle_version == 0
    assert snapshot.rsi_period_version == 0
    assert snapshot.buy_order_version == 0
    assert snapshot.exclude_version == 0


def test_ui_versions_bump_on_successful_changes():
    settings = Settings()
    bus = StatusBus()
    engine = TradingEngine(settings, DummyGateway(), DummyLogger(), bus, DummyClock())

    engine.change_strategy("rsi_failure_swing")
    snapshot = _drain_last_snapshot(bus)
    assert snapshot is not None
    assert snapshot.strategy_version == 1

    engine.change_candle_config("tick", 30)
    snapshot = _drain_last_snapshot(bus)
    assert snapshot is not None
    assert snapshot.candle_version == 1

    engine.change_rsi_period(7)
    snapshot = _drain_last_snapshot(bus)
    assert snapshot is not None
    assert snapshot.rsi_period_version == 1

    engine.change_order_size_config("cash", 2_000_000)
    snapshot = _drain_last_snapshot(bus)
    assert snapshot is not None
    assert snapshot.buy_order_version == 1

    engine.change_excluded_codes("005930, 000660")
    snapshot = _drain_last_snapshot(bus)
    assert snapshot is not None
    assert snapshot.exclude_version == 1


def test_condition_version_bumps_on_condition_change():
    settings = Settings()
    settings.condition_index = 0
    bus = StatusBus()
    engine = TradingEngine(settings, DummyGateway(), DummyLogger(), bus, DummyClock())
    engine._condition_name = "COND_A"
    engine._condition_started = True

    engine.change_condition_index(1)
    snapshot = _drain_last_snapshot(bus)

    assert snapshot is not None
    assert snapshot.condition_version == 1


def test_change_pyramiding_config_rebuilds_current_strategy_and_bumps_version():
    settings = Settings()
    settings.strategy_name = "rsi_grid"
    bus = StatusBus()
    engine = TradingEngine(settings, DummyGateway(), DummyLogger(), bus, DummyClock())

    engine.change_pyramiding_config("rsi_grid", False)
    snapshot = _drain_last_snapshot(bus)

    assert snapshot is not None
    assert snapshot.strategy_version == 1
    assert settings.rsi_pyramiding_enabled is False
    assert bool(getattr(engine._strategy, "pyramiding_enabled", True)) is False


def test_change_cci_filter_config_rebuilds_current_strategy_and_bumps_version():
    settings = Settings()
    settings.strategy_name = "rsi_grid"
    bus = StatusBus()
    engine = TradingEngine(settings, DummyGateway(), DummyLogger(), bus, DummyClock())

    engine.change_cci_filter_config("rsi_grid", True)
    snapshot = _drain_last_snapshot(bus)

    assert snapshot is not None
    assert snapshot.strategy_version == 1
    assert settings.rsi_use_cci_filter is True
    assert bool(getattr(engine._strategy, "use_cci_filter", False)) is True


def test_change_cci_threshold_config_rebuilds_current_strategy_and_bumps_version():
    settings = Settings()
    settings.strategy_name = "rsi_grid"
    bus = StatusBus()
    engine = TradingEngine(settings, DummyGateway(), DummyLogger(), bus, DummyClock())

    engine.change_cci_threshold_config("rsi_grid", 15.0, 110.0)
    snapshot = _drain_last_snapshot(bus)

    assert snapshot is not None
    assert snapshot.strategy_version == 1
    assert settings.rsi_cci_entry_threshold == 15.0
    assert settings.rsi_cci_add_threshold == 110.0
    assert float(getattr(engine._strategy, "cci_entry_threshold", 0.0)) == 15.0
    assert float(getattr(engine._strategy, "cci_add_threshold", 0.0)) == 110.0
