import datetime

from app.settings import Settings
from app.status_bus import StatusBus
from use_cases.trading_engine import TradingEngine


class DummyClock:
    """테스트용 고정 시계."""

    def __init__(self) -> None:
        self._now = datetime.datetime(2026, 2, 10, 10, 0, 0)

    def now(self) -> datetime.datetime:
        return self._now


class DummyLogger:
    """테스트용 로거."""

    def __init__(self) -> None:
        self.messages = []

    def info(self, message, *args) -> None:
        self.messages.append(("info", message, args))

    def warning(self, message, *args) -> None:
        self.messages.append(("warning", message, args))

    def error(self, message, *args) -> None:
        self.messages.append(("error", message, args))


class ChejanSyncGateway:
    """체결 수신 뒤 보유조회 호출 여부를 확인하는 게이트웨이 스텁."""

    def __init__(self) -> None:
        self._events = [
            {
                "gubun": "0",
                "9001": "A005930",
                "907": "1",
                "911": "5",
                "910": "70000",
                "900": "5",
                "902": "0",
                "908": "101010",
                "302": "삼성전자",
            }
        ]
        self.holdings_calls = 0

    def get_chejan_data(self):
        if not self._events:
            return None
        return self._events.pop(0)

    def request_holdings(self, account_no: str, password: str):
        self.holdings_calls += 1
        return {}

    def get_master_code_name(self, code: str) -> str:
        return "TEST"

    def get_account_numbers(self):
        return ["12345678"]

    def get_server_gubun(self):
        return "1"

    def request_deposit(self, account_no: str, password: str):
        return {}

    def request_account_summary(self, account_no: str, password: str):
        return {}

    def set_real_reg(self, screen: str, codes, fids, opt_type: int) -> None:
        return None

    def disconnect_real(self, screen: str) -> None:
        return None

    def get_real_data(self):
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


def test_full_execution_without_balance_event_triggers_holdings_refresh():
    """체결 완료 시 주기적 갱신 스레드에서 보유 정보를 갱신하도록 플래그를 설정한다."""
    settings = Settings()
    gateway = ChejanSyncGateway()
    engine = TradingEngine(settings, gateway, DummyLogger(), StatusBus(), DummyClock())
    engine._account_no = "12345678"
    engine._portfolio.update_position("005930", qty=5, sellable=5, avg_price=70000)

    engine.process_chejan_queue()

    # 체결 완료 후 강제 갱신 플래그가 설정되어야 함 (메인 스레드 블로킹 방지)
    assert engine._force_account_refresh is True
    # 포트폴리오는 즉시 업데이트됨
    assert engine._portfolio.get_qty("005930") == 0


def test_sell_execution_without_balance_event_updates_portfolio_immediately():
    class NoBalanceButStaleHoldingsGateway(ChejanSyncGateway):
        """잔고 체결이 누락되고 TR 보유조회도 즉시 반영되지 않는 상황을 모사한다."""

        def request_holdings(self, account_no: str, password: str):
            self.holdings_calls += 1
            return {
                "005930": {
                    "qty": 5,
                    "sellable": 5,
                    "avg_price": 70000,
                    "name": "삼성전자",
                }
            }

    settings = Settings()
    gateway = NoBalanceButStaleHoldingsGateway()
    engine = TradingEngine(settings, gateway, DummyLogger(), StatusBus(), DummyClock())
    engine._account_no = "12345678"
    engine._portfolio.update_position("005930", qty=5, sellable=5, avg_price=70000)

    engine.process_chejan_queue()

    assert engine._portfolio.get_qty("005930") == 0


def test_pending_manual_sell_logs_order_status_when_fill_not_parsed():
    class PendingStatusGateway(ChejanSyncGateway):
        """체결량이 없어 parse 실패하는 접수 이벤트를 모사한다."""

        def __init__(self) -> None:
            super().__init__()
            self._events = [
                {
                    "gubun": "0",
                    "9001": "A005930",
                    "913": "접수",
                    "900": "5",
                    "902": "5",
                    "302": "삼성전자",
                }
            ]

    settings = Settings()
    gateway = PendingStatusGateway()
    logger = DummyLogger()
    clock = DummyClock()
    engine = TradingEngine(settings, gateway, logger, StatusBus(), clock)
    engine._manual_sell_pending["005930"] = {
        "requested_qty": 5,
        "requested_at": clock.now(),
        "last_trace_at": None,
    }

    engine.process_chejan_queue()

    assert any("주문상태(수동매도)" in msg for level, msg, _ in logger.messages if level == "info")
