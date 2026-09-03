import datetime

from app.settings import Settings
from app.status_bus import StatusBus
from use_cases.trading_engine import TradingEngine


class DummyClock:
    """Controllable clock for tests."""

    def __init__(self) -> None:
        self._now = datetime.datetime(2026, 2, 10, 10, 0, 0)

    def now(self) -> datetime.datetime:
        return self._now

    def advance(self, seconds: int) -> None:
        self._now += datetime.timedelta(seconds=seconds)


class DummyLogger:
    """Simple logger stub for tests."""

    def info(self, message, *args) -> None:
        return None

    def warning(self, message, *args) -> None:
        return None

    def error(self, message, *args) -> None:
        return None


class HoldingsGateway:
    """Gateway stub that tracks holdings requests."""

    def __init__(self) -> None:
        self.calls = 0
        self.deposit_calls = 0

    def request_holdings(self, account_no: str, password: str):
        self.calls += 1
        return {"000001": {"qty": 1, "sellable": 1, "avg_price": 1000}}

    def get_master_code_name(self, code: str) -> str:
        return code

    def get_account_numbers(self):
        return ["123"]

    def get_server_gubun(self):
        return "1"

    def request_deposit(self, account_no: str, password: str):
        self.deposit_calls += 1
        return {}

    def request_account_summary(self, account_no: str, password: str):
        return {}

    def set_real_reg(self, screen: str, codes, fids, opt_type: int) -> None:
        return None

    def disconnect_real(self, screen: str) -> None:
        return None

    def get_real_data(self):
        return None

    def get_chejan_data(self):
        return None

    def get_condition_name_list(self):
        return ""

    def send_condition(self, screen: str, cond_name: str, index: int, search: int) -> None:
        return None

    def stop_condition(self, screen: str, cond_name: str, index: int) -> None:
        return None

    def get_tr_condition(self):
        return None

    def get_real_condition(self):
        return None


def test_holdings_refresh_respects_interval():
    settings = Settings()
    settings.holdings_refresh_seconds = 10.0
    clock = DummyClock()
    gateway = HoldingsGateway()
    engine = TradingEngine(settings, gateway, DummyLogger(), StatusBus(), clock)
    engine._account_no = "123"

    engine._refresh_holdings(force=False)
    engine._refresh_holdings(force=False)

    assert gateway.calls == 1

    clock.advance(11)
    engine._refresh_holdings(force=False)

    assert gateway.calls == 2


def test_manual_holdings_refresh_forces_server_request():
    settings = Settings()
    settings.holdings_refresh_seconds = 60.0
    clock = DummyClock()
    gateway = HoldingsGateway()
    engine = TradingEngine(settings, gateway, DummyLogger(), StatusBus(), clock)
    engine._account_no = "123"

    engine._refresh_holdings(force=False)
    engine.refresh_holdings_now()

    assert gateway.calls == 2
    assert gateway.deposit_calls >= 1
