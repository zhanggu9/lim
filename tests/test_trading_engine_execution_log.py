import datetime

from app.settings import Settings
from app.status_bus import StatusBus
from use_cases.trading_engine import TradingEngine


class DummyClock:
    def __init__(self) -> None:
        self._now = datetime.datetime(2026, 2, 10, 10, 0, 0)

    def now(self) -> datetime.datetime:
        return self._now


class DummyLogger:
    def __init__(self) -> None:
        self.messages = []

    def info(self, message, *args) -> None:
        self.messages.append(("info", message, args))

    def warning(self, message, *args) -> None:
        self.messages.append(("warning", message, args))

    def error(self, message, *args) -> None:
        self.messages.append(("error", message, args))


class DummyGateway:
    def __init__(self, chejan_event) -> None:
        self._chejan_event = chejan_event
        self._called = False

    def get_chejan_data(self):
        if self._called:
            return None
        self._called = True
        return self._chejan_event

    def get_master_code_name(self, code: str) -> str:
        return "TEST"


def test_execution_event_logs_on_receive():
    settings = Settings()
    logger = DummyLogger()
    event = {
        "gubun": "0",
        "9001": "A005930",
        "907": "2",
        "911": "10",
        "910": "70000",
        "900": "10",
        "902": "0",
        "908": "101010",
        "302": "삼성전자",
    }
    engine = TradingEngine(settings, DummyGateway(event), logger, StatusBus(), DummyClock())

    engine.process_chejan_queue()

    assert any("체결수신" in msg for _, msg, _ in logger.messages)
