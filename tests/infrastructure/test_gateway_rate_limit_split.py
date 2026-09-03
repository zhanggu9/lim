import importlib
import sys
import types

from app.settings import Settings


class DummyManager:
    """게이트웨이 테스트용 KiwoomManager 스텁."""

    def __init__(self) -> None:
        self.orders = []
        self.methods = []

    def put_method(self, payload) -> None:
        self.methods.append(payload)

    def get_method(self):
        return ["1111111111"]

    def put_order(self, payload) -> None:
        self.orders.append(payload)


class SpyLimiter:
    """acquire 호출 횟수와 대기 통계를 기록하는 레이트리미터 스파이."""

    def __init__(self, wait_ms: float = 0.0) -> None:
        self.acquire_count = 0
        self.wait_ms = float(wait_ms)

    def acquire(self) -> None:
        self.acquire_count += 1

    def get_wait_ms_last_sec(self, window_sec: float = 1.0) -> float:
        return self.wait_ms


def _load_gateway_module(monkeypatch):
    fake_pykiwoom = types.SimpleNamespace(KiwoomManager=DummyManager)
    monkeypatch.setitem(sys.modules, "pykiwoom", fake_pykiwoom)
    module = importlib.import_module("infrastructure.kiwoom.kiwoom_gateway")
    return importlib.reload(module)


def test_gateway_splits_tr_and_order_limiters(monkeypatch):
    module = _load_gateway_module(monkeypatch)
    settings = Settings()
    gateway = module.PyKiwoomGateway(logger=None, settings=settings)
    gateway._dispatcher._tr_limiter = SpyLimiter()
    gateway._dispatcher._order_limiter = SpyLimiter()
    gateway._dispatcher._global_limiter = SpyLimiter()

    gateway.get_account_numbers()
    gateway.send_order(
        rqname="test",
        screen="6000",
        acc_no="1111111111",
        order_type=1,
        code="000001",
        quantity=1,
        price=1000,
        hoga_gb="00",
        order_no="",
    )

    assert gateway._dispatcher._tr_limiter.acquire_count == 1
    assert gateway._dispatcher._order_limiter.acquire_count == 1
    assert gateway._dispatcher._global_limiter.acquire_count == 2


def test_gateway_wait_stats_returns_tr_and_order(monkeypatch):
    module = _load_gateway_module(monkeypatch)
    settings = Settings()
    gateway = module.PyKiwoomGateway(logger=None, settings=settings)
    gateway._dispatcher._tr_limiter = SpyLimiter(wait_ms=123.0)
    gateway._dispatcher._order_limiter = SpyLimiter(wait_ms=45.0)
    gateway._dispatcher._global_limiter = SpyLimiter(wait_ms=250.0)

    stats = gateway.get_rate_limit_wait_ms()

    assert stats["tr"] == 123.0
    assert stats["order"] == 45.0
    assert stats["global"] == 250.0
