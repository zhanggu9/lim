import datetime

from app.settings import Settings
from app.status_bus import StatusBus
from use_cases.trading_engine import TradingEngine


class DummyClock:
    """Fixed time clock for tests."""

    def __init__(self) -> None:
        self._now = datetime.datetime(2026, 2, 10, 10, 0, 0)

    def now(self) -> datetime.datetime:
        return self._now


class DummyLogger:
    """Simple logger stub for tests."""

    def info(self, message, *args) -> None:
        return None

    def warning(self, message, *args) -> None:
        return None

    def error(self, message, *args) -> None:
        return None


class DummyGateway:
    """Minimal gateway stub."""

    def __init__(self) -> None:
        self.calls = 0
        self.sent = []
        self.stopped = []

    def get_master_code_name(self, code: str) -> str:
        return code

    def get_condition_name_list(self):
        self.calls += 1
        if self.calls == 1:
            return "0^COND_A;1^COND_B;"
        return "2^COND_A;1^COND_B;"

    def send_condition(self, screen: str, cond_name: str, index: int, search: int) -> None:
        self.sent.append((screen, cond_name, index, search))

    def stop_condition(self, screen: str, cond_name: str, index: int) -> None:
        self.stopped.append((screen, cond_name, index))


def test_condition_items_in_snapshot():
    settings = Settings()
    bus = StatusBus()
    engine = TradingEngine(settings, DummyGateway(), DummyLogger(), bus, DummyClock())
    engine._try_setup_condition(retry_seconds=0)
    engine._publish_status()

    snapshot = bus.try_get()
    assert snapshot is not None
    assert snapshot.condition_items
    assert snapshot.condition_items[0]["index"] == 0


def test_refresh_condition_list_updates_index_by_name():
    settings = Settings()
    bus = StatusBus()
    gateway = DummyGateway()
    engine = TradingEngine(settings, gateway, DummyLogger(), bus, DummyClock())
    engine._try_setup_condition(retry_seconds=0)
    engine._condition_started = True

    engine.refresh_condition_list()

    assert engine._settings.condition_index == 2
    assert gateway.stopped
    assert gateway.sent


def test_refresh_condition_list_updates_name_when_index_same():
    class NameChangeGateway(DummyGateway):
        def get_condition_name_list(self):
            self.calls += 1
            if self.calls == 1:
                return "0^COND_A;1^COND_B;"
            return "0^COND_C;1^COND_B;"

    settings = Settings()
    bus = StatusBus()
    gateway = NameChangeGateway()
    engine = TradingEngine(settings, gateway, DummyLogger(), bus, DummyClock())
    engine._try_setup_condition(retry_seconds=0)
    engine._condition_started = True

    engine.refresh_condition_list()

    assert engine._settings.condition_index == 0
    assert engine._condition_name == "COND_C"
    assert gateway.sent
