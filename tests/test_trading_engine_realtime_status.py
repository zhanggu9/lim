import datetime

from app.settings import Settings
from app.status_bus import StatusBus
from use_cases.trading_engine import TradingEngine


class DummyClock:
    def __init__(self) -> None:
        self._now = datetime.datetime(2026, 2, 24, 10, 0, 0)

    def now(self) -> datetime.datetime:
        return self._now


class DummyLogger:
    def info(self, message, *args) -> None:
        return None

    def warning(self, message, *args) -> None:
        return None

    def error(self, message, *args) -> None:
        return None


class StatusGateway:
    def __init__(self, ingress_size: int, tr_wait_ms: float, order_wait_ms: float) -> None:
        self.ingress_size = ingress_size
        self.tr_wait_ms = tr_wait_ms
        self.order_wait_ms = order_wait_ms

    def get_master_code_name(self, code: str) -> str:
        return code

    def get_real_ingress_size(self) -> int:
        return self.ingress_size

    def get_real_ingress_drop_count(self) -> int:
        return 0

    def get_rate_limit_wait_ms(self):
        return {"tr": self.tr_wait_ms, "order": self.order_wait_ms}


def _drain_last_snapshot(bus: StatusBus):
    snapshot = None
    while True:
        item = bus.try_get()
        if item is None:
            break
        snapshot = item
    return snapshot


def test_realtime_status_warns_when_threshold_exceeded():
    settings = Settings()
    settings.tick_queue_maxsize = 10
    settings.tick_compute_shard_count = 1
    settings.ui_realtime_warn_queue_ratio = 0.7
    settings.ui_realtime_warn_drop_count = 1
    settings.ui_realtime_warn_limit_wait_ms = 200.0
    bus = StatusBus()
    gateway = StatusGateway(ingress_size=120, tr_wait_ms=250.0, order_wait_ms=0.0)
    engine = TradingEngine(settings, gateway, DummyLogger(), bus, DummyClock())

    for _ in range(8):
        engine._tick_queue.put_nowait(object())
    engine._tick_drop_count = 1

    engine._publish_status()
    snapshot = _drain_last_snapshot(bus)

    assert snapshot is not None
    assert snapshot.realtime_status_level == "warn"
    assert "120" in snapshot.realtime_status
    assert "8/10" in snapshot.realtime_status
    assert "샤드최대" in snapshot.realtime_status
    assert snapshot.tr_limit_wait_ms_1s == 250.0


def test_realtime_status_ok_when_metrics_are_stable():
    settings = Settings()
    settings.tick_queue_maxsize = 10
    settings.tick_compute_shard_count = 1
    settings.ui_realtime_warn_queue_ratio = 0.7
    settings.ui_realtime_warn_drop_count = 1
    settings.ui_realtime_warn_limit_wait_ms = 200.0
    bus = StatusBus()
    gateway = StatusGateway(ingress_size=2, tr_wait_ms=10.0, order_wait_ms=10.0)
    engine = TradingEngine(settings, gateway, DummyLogger(), bus, DummyClock())

    engine._publish_status()
    snapshot = _drain_last_snapshot(bus)

    assert snapshot is not None
    assert snapshot.realtime_status_level == "ok"
