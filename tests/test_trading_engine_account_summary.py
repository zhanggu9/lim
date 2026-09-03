import datetime

from app.settings import Settings
from app.status_bus import StatusBus
from use_cases.trading_engine import TradingEngine


class DummyClock:
    """Fixed time clock for tests."""

    def now(self) -> datetime.datetime:
        return datetime.datetime(2026, 2, 10, 10, 0, 0)


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


def test_account_summary_applies_fee_rate():
    settings = Settings()
    settings.fee_rate = 0.001
    engine = TradingEngine(settings, DummyGateway(), DummyLogger(), StatusBus(), DummyClock())

    engine._portfolio.update_position("000001", qty=10, sellable=10, avg_price=1000)
    engine._last_prices["000001"] = 1100
    engine._account_info = {
        "deposit": 5_000_000,
        "orderable": 4_900_000,
        "total_profit": 123_456,
        "total_profit_rate": 1.23,
    }

    summary = engine._build_account_summary()

    assert "수수료" in summary
    assert "9.78" in summary


def test_account_summary_includes_today_realized_pnl():
    settings = Settings()
    settings.fee_rate = 0.001
    engine = TradingEngine(settings, DummyGateway(), DummyLogger(), StatusBus(), DummyClock())

    engine._daily_tracker.record(code="000001", side="BUY", qty=10, price=1000, avg_price=0, name="TEST")
    engine._daily_tracker.record(code="000001", side="SELL", qty=10, price=1100, avg_price=1000, name="TEST")

    summary = engine._build_account_summary()

    assert "당일 실현손익 +979원" in summary
    assert "당일 실현수익률 9.79%" in summary
