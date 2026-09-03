import datetime

from app.settings import Settings
from app.status_bus import StatusBus
from domain.entities import Tick
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


class DummyGateway:
    def get_master_code_name(self, code: str) -> str:
        return code

    def get_real_ingress_size(self) -> int:
        return 0

    def get_real_ingress_drop_count(self) -> int:
        return 0

    def get_rate_limit_wait_ms(self):
        return {"tr": 0.0, "order": 0.0}


def _make_engine() -> TradingEngine:
    settings = Settings()
    settings.tick_compute_shard_count = 1
    settings.tick_queue_maxsize = 20
    settings.tick_queue_soft_ratio = 0.8
    settings.tick_queue_hard_ratio = 0.95
    settings.tick_queue_overload_wait_ms = 0.0
    settings.tick_queue_emergency_drop_batch = 5
    settings.queue_policy_mode = "hybrid"
    engine = TradingEngine(settings, DummyGateway(), DummyLogger(), StatusBus(), DummyClock())
    return engine


def test_tick_queue_hybrid_policy_has_no_drop_under_normal_load():
    engine = _make_engine()
    for i in range(10):
        engine._enqueue_tick(Tick(code="000001", price=1000 + i, volume=1, time=f"0930{i:02d}"))

    assert engine._tick_drop_count == 0
    assert engine._tick_queue.qsize() == 10


def test_tick_queue_hybrid_policy_drops_only_when_over_hard_threshold():
    engine = _make_engine()
    engine._settings.tick_queue_soft_ratio = 0.2
    engine._settings.tick_queue_hard_ratio = 0.3
    engine._tick_queue_soft_ratio = 0.2
    engine._tick_queue_hard_ratio = 0.3
    engine._tick_queue_overload_wait_sec = 0.0
    engine._tick_queue_emergency_drop_batch = 3

    for i in range(100):
        engine._enqueue_tick(Tick(code="000001", price=1100 + i, volume=1, time=f"0931{i % 60:02d}"))

    assert engine._tick_drop_count > 0
    assert engine._tick_queue.qsize() <= engine._tick_queue.maxsize


def test_tick_queue_hybrid_policy_preemptively_drops_at_hard_threshold():
    engine = _make_engine()
    engine._tick_queue_soft_ratio = 0.8
    engine._tick_queue_hard_ratio = 0.95
    engine._tick_queue_overload_wait_sec = 0.0
    engine._tick_queue_emergency_drop_batch = 1

    for i in range(19):
        engine._enqueue_tick(Tick(code="000001", price=1200 + i, volume=1, time=f"0932{i % 60:02d}"))

    assert engine._tick_queue.qsize() == 19

    engine._enqueue_tick(Tick(code="000001", price=1300, volume=1, time="093300"))

    assert engine._tick_drop_count > 0
    assert engine._tick_queue.qsize() <= int(engine._tick_queue.maxsize * engine._tick_queue_soft_ratio) + 1


def test_realtime_status_includes_ingress_drop_in_total_drop_count():
    class DropGateway(DummyGateway):
        def get_real_ingress_drop_count(self) -> int:
            return 3

    settings = Settings()
    settings.tick_compute_shard_count = 1
    bus = StatusBus()
    engine = TradingEngine(settings, DropGateway(), DummyLogger(), bus, DummyClock())

    engine._publish_status()
    snapshot = bus.try_get()

    assert snapshot is not None
    assert snapshot.tick_drop_count == 3
    assert "T0/R3" in snapshot.realtime_status
