import datetime

from app.settings import Settings
from app.status_bus import StatusBus
from domain.entities import TradeSignal
from use_cases.trading_engine import TradingEngine


class DummyClock:
    """테스트용 고정 시계."""

    def now(self) -> datetime.datetime:
        return datetime.datetime(2026, 2, 13, 10, 0, 0)


class DummyLogger:
    """테스트용 로거."""

    def info(self, message, *args) -> None:
        return None

    def warning(self, message, *args) -> None:
        return None

    def error(self, message, *args) -> None:
        return None


class DummyGateway:
    """주문 파라미터를 캡처하는 게이트웨이 스텁."""

    def __init__(self) -> None:
        self.orders = []

    def request_holdings(self, account_no: str, password: str):
        return {}

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
        return code


def _create_engine():
    settings = Settings()
    settings.buy_size_mode = "qty"
    settings.buy_qty = 1
    gateway = DummyGateway()
    engine = TradingEngine(settings, gateway, DummyLogger(), StatusBus(), DummyClock())
    engine._allow_trading = True
    engine._account_no = "1234567890"
    return engine, gateway


def test_buy_order_uses_market_order():
    engine, gateway = _create_engine()
    signal = TradeSignal(code="000001", side="BUY", quantity=1, reason="test", price=1000)

    engine._execute_signal(signal)

    assert len(gateway.orders) == 1
    assert gateway.orders[0]["hoga_gb"] == "03"
    assert gateway.orders[0]["price"] == 0


def test_sell_order_uses_market_order():
    engine, gateway = _create_engine()
    engine._portfolio.update_position("000001", qty=10, sellable=10, avg_price=1000)
    signal = TradeSignal(code="000001", side="SELL", quantity=3, reason="test", price=1000)

    engine._execute_signal(signal)

    assert len(gateway.orders) == 1
    assert gateway.orders[0]["hoga_gb"] == "03"
    assert gateway.orders[0]["price"] == 0


def test_sell_all_uses_market_order():
    engine, gateway = _create_engine()
    engine._last_holdings_refresh = engine._clock.now()
    engine._portfolio.update_position("000001", qty=3, sellable=3, avg_price=1000)
    engine._last_prices["000001"] = 1000

    engine.sell_all("000001")

    assert len(gateway.orders) == 1
    assert gateway.orders[0]["hoga_gb"] == "03"
    assert gateway.orders[0]["price"] == 0
