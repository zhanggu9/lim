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

    def get_master_code_name(self, code: str) -> str:
        return code


def test_rsi_summary_shows_watchlist_with_placeholders():
    settings = Settings()
    engine = TradingEngine(settings, DummyGateway(), DummyLogger(), StatusBus(), DummyClock())

    engine._last_rsi_values = {"000001": 55.0}
    engine._watchlist.update_holdings({"000001", "000002"})

    summary = engine._build_rsi_summary()

    assert "000001" in summary
    assert "000002" in summary
    assert "000002 -" in summary
