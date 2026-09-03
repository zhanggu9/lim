import datetime

from app.settings import Settings
from app.status_bus import StatusBus
from use_cases.trading_engine import TradingEngine


class DummyClock:
    """테스트용 고정 시계."""

    def __init__(self) -> None:
        self._now = datetime.datetime(2026, 2, 24, 10, 0, 0)

    def now(self) -> datetime.datetime:
        return self._now


class DummyLogger:
    """테스트용 무출력 로거."""

    def info(self, message, *args) -> None:
        return None

    def warning(self, message, *args) -> None:
        return None

    def error(self, message, *args) -> None:
        return None


class DrainGateway:
    """drain_real_data 기반 수신 경로 검증용 게이트웨이."""

    def __init__(self) -> None:
        self.last_batch = 0

    def drain_real_data(self, max_items: int):
        self.last_batch = max_items
        return [
            {"code": "000001", "10": "1000", "15": "1", "20": "093001"},
            {"code": "000001", "10": "1010", "15": "1", "20": "093002"},
        ]

    def get_master_code_name(self, code: str) -> str:
        return code

    def set_real_reg(self, screen: str, codes, fids, opt_type: int) -> None:
        return None

    def disconnect_real(self, screen: str) -> None:
        return None


def test_realtime_queue_uses_gateway_drain_batch():
    settings = Settings()
    settings.ticks_per_candle = 1
    settings.rsi_period = 1
    settings.real_ingress_drain_batch = 2
    gateway = DrainGateway()
    engine = TradingEngine(settings, gateway, DummyLogger(), StatusBus(), DummyClock())
    engine._last_watchlist = ["000001"]

    engine.process_real_data_queue()
    engine.process_tick_compute_queue()

    assert gateway.last_batch == 2
    assert "000001" in engine._last_rsi_values
