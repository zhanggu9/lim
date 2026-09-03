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

    def __init__(self) -> None:
        self.messages = []

    def info(self, message, *args) -> None:
        self.messages.append(("info", message, args))

    def warning(self, message, *args) -> None:
        self.messages.append(("warning", message, args))

    def error(self, message, *args) -> None:
        self.messages.append(("error", message, args))


class FakeGateway:
    """Gateway stub for TradingEngine tests."""

    def __init__(self, holdings) -> None:
        self._holdings = holdings
        self.orders = []
        self.holdings_calls = 0

    def request_holdings(self, account_no: str, password: str):
        self.holdings_calls += 1
        return self._holdings

    def send_order(
        self,
        rqname: str,
        screen: str,
        acc_no: str,
        order_type: int,
        code: str,
        quantity: int,
        price: int,
        hoga_gb: str,
        order_no: str = "",
    ) -> None:
        self.orders.append(
            {
                "rqname": rqname,
                "screen": screen,
                "acc_no": acc_no,
                "order_type": order_type,
                "code": code,
                "quantity": quantity,
                "price": price,
                "hoga_gb": hoga_gb,
                "order_no": order_no,
            }
        )

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


def test_sell_all_uses_account_holdings_when_portfolio_empty():
    settings = Settings()
    gateway = FakeGateway(
        {
            "005930": {
                "qty": 12,
                "sellable": 0,
                "avg_price": 70000,
                "name": "TEST",
            }
        }
    )
    logger = DummyLogger()
    engine = TradingEngine(settings, gateway, logger, StatusBus(), DummyClock())
    engine._account_no = "12345678"
    engine._allow_trading = True

    engine.sell_all("005930")

    assert len(gateway.orders) == 1
    assert gateway.orders[0]["quantity"] == 12


def test_sell_all_skips_forced_holdings_when_recent():
    settings = Settings()
    settings.holdings_refresh_seconds = 30.0
    settings.holdings_force_min_interval_sec = 5.0
    gateway = FakeGateway({})
    logger = DummyLogger()
    clock = DummyClock()
    engine = TradingEngine(settings, gateway, logger, StatusBus(), clock)
    engine._account_no = "12345678"
    engine._allow_trading = True
    engine._last_holdings_refresh = clock.now()

    engine.sell_all("005930")

    assert gateway.holdings_calls == 0


def test_sell_all_uses_cached_qty_when_holdings_refresh_returns_empty():
    settings = Settings()
    gateway = FakeGateway({})
    logger = DummyLogger()
    engine = TradingEngine(settings, gateway, logger, StatusBus(), DummyClock())
    engine._account_no = "12345678"
    engine._allow_trading = True
    engine._portfolio.update_position("005930", qty=7, sellable=7, avg_price=70000)

    engine.sell_all("005930")

    assert len(gateway.orders) == 1
    assert gateway.orders[0]["quantity"] == 7


def test_sell_all_registers_pending_sync_trace_when_order_sent():
    settings = Settings()
    gateway = FakeGateway(
        {
            "005930": {
                "qty": 12,
                "sellable": 12,
                "avg_price": 70000,
                "name": "TEST",
            }
        }
    )
    logger = DummyLogger()
    engine = TradingEngine(settings, gateway, logger, StatusBus(), DummyClock())
    engine._account_no = "12345678"
    engine._allow_trading = True

    engine.sell_all("005930")

    pending = engine._manual_sell_pending.get("005930")
    assert pending is not None
    assert pending["requested_qty"] == 12
