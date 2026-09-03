import datetime

from app.settings import Settings
from app.status_bus import StatusBus
from use_cases.trading_engine import TradingEngine


class DummyClock:
    """테스트용 고정 시계."""

    def now(self) -> datetime.datetime:
        return datetime.datetime(2026, 2, 10, 10, 0, 0)


class DummyLogger:
    def info(self, message, *args) -> None:
        return None

    def warning(self, message, *args) -> None:
        return None

    def error(self, message, *args) -> None:
        return None


class RefreshGateway:
    """계좌 갱신 호출 횟수를 추적하는 테스트 더블."""

    def __init__(self) -> None:
        self.deposit_calls = 0
        self.summary_calls = 0

    def request_deposit(self, account_no: str, password: str):
        self.deposit_calls += 1
        return {"deposit": 1_000_000, "orderable": 900_000}

    def request_account_summary(self, account_no: str, password: str):
        self.summary_calls += 1
        return {"total_profit": 1_000, "total_profit_rate": 1.0}

    def get_master_code_name(self, code: str) -> str:
        return code


def test_account_refresh_uses_only_deposit_tr():
    settings = Settings()
    engine = TradingEngine(settings, RefreshGateway(), DummyLogger(), StatusBus(), DummyClock())
    engine._account_no = "1234567890"

    engine._refresh_account_info(force=True)

    gateway = engine._gateway
    assert gateway.deposit_calls == 1
    assert gateway.summary_calls == 0
