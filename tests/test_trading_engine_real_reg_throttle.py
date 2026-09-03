import datetime

from app.settings import Settings
from app.status_bus import StatusBus
from use_cases.trading_engine import TradingEngine


class DummyClock:
    def __init__(self) -> None:
        self._now = datetime.datetime(2026, 2, 10, 10, 0, 0)

    def now(self) -> datetime.datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now = self._now + datetime.timedelta(seconds=seconds)


class DummyLogger:
    def info(self, message, *args) -> None:
        return None

    def warning(self, message, *args) -> None:
        return None

    def error(self, message, *args) -> None:
        return None


class DummyGateway:
    def __init__(self) -> None:
        self.reg_calls = []
        self.disconnect_calls = 0

    def set_real_reg(self, screen: str, codes, fids, opt_type: int) -> None:
        self.reg_calls.append((screen, list(codes), list(fids), opt_type))

    def disconnect_real(self, screen: str) -> None:
        self.disconnect_calls += 1

    def get_master_code_name(self, code: str) -> str:
        return code


def test_real_reg_throttles_and_flushes():
    settings = Settings()
    settings.real_reg_min_interval_sec = 1.0
    clock = DummyClock()
    gateway = DummyGateway()
    engine = TradingEngine(settings, gateway, DummyLogger(), StatusBus(), clock)

    engine._watchlist.update_holdings({"000001"})
    engine._sync_real_registration()
    assert len(gateway.reg_calls) == 1

    engine._watchlist.update_holdings({"000002"})
    engine._sync_real_registration()
    assert len(gateway.reg_calls) == 1

    clock.advance(1.1)
    engine._flush_real_registration_if_due()
    assert len(gateway.reg_calls) == 2
