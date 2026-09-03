import datetime

from app.settings import Settings
from app.status_bus import StatusBus
from domain.entities import TradeSignal
from use_cases.trading_engine import TradingEngine


class DummyClock:
    """테스트용 고정 시계."""

    def __init__(self) -> None:
        self._now = datetime.datetime(2026, 2, 21, 10, 0, 0)

    def now(self) -> datetime.datetime:
        return self._now


class DummyLogger:
    """테스트용 로거."""

    def info(self, message, *args) -> None:
        return None

    def warning(self, message, *args) -> None:
        return None

    def error(self, message, *args) -> None:
        return None


class DummyGateway:
    """주문 파라미터를 수집하는 게이트웨이 스텁."""

    def __init__(self) -> None:
        self.orders = []

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

    def request_holdings(self, account_no: str, password: str):
        return {}


def _create_engine(settings: Settings | None = None):
    cfg = settings or Settings()
    gateway = DummyGateway()
    engine = TradingEngine(cfg, gateway, DummyLogger(), StatusBus(), DummyClock())
    engine._allow_trading = True
    engine._account_no = "12345678"
    return engine, gateway


def test_buy_order_uses_cash_mode_quantity():
    settings = Settings()
    settings.buy_size_mode = "cash"
    settings.buy_cash = 10_000
    engine, gateway = _create_engine(settings)

    engine._execute_signal(TradeSignal(code="000001", side="BUY", quantity=1, reason="test", price=1000))

    assert len(gateway.orders) == 1
    assert gateway.orders[0]["quantity"] == 9


def test_buy_order_uses_fixed_qty_mode():
    settings = Settings()
    settings.buy_size_mode = "qty"
    settings.buy_qty = 7
    settings.buy_cash = 10_000
    engine, gateway = _create_engine(settings)

    engine._execute_signal(TradeSignal(code="000001", side="BUY", quantity=1, reason="test", price=1000))

    assert len(gateway.orders) == 1
    assert gateway.orders[0]["quantity"] == 7


def test_sell_signal_keeps_strategy_quantity():
    engine, gateway = _create_engine(Settings())
    engine._portfolio.update_position("000001", qty=10, sellable=10, avg_price=1000)

    engine._execute_signal(TradeSignal(code="000001", side="SELL", quantity=3, reason="test", price=1000))

    assert len(gateway.orders) == 1
    assert gateway.orders[0]["quantity"] == 3


def test_strategy_signal_is_blocked_for_excluded_code():
    settings = Settings()
    settings.excluded_codes = ["000001"]
    engine, gateway = _create_engine(settings)

    engine._execute_signal(TradeSignal(code="000001", side="BUY", quantity=1, reason="test", price=1000))

    assert len(gateway.orders) == 0


def test_strategy_sell_signal_is_blocked_for_excluded_code():
    settings = Settings()
    settings.excluded_codes = ["000001"]
    engine, gateway = _create_engine(settings)
    engine._portfolio.update_position("000001", qty=3, sellable=3, avg_price=1000)

    engine._execute_signal(TradeSignal(code="000001", side="SELL", quantity=3, reason="test", price=1000))

    assert len(gateway.orders) == 0


def test_sell_all_blocks_excluded_code_for_manual_exit():
    settings = Settings()
    settings.excluded_codes = ["000001"]
    engine, gateway = _create_engine(settings)
    engine._last_holdings_refresh = engine._clock.now()
    engine._portfolio.update_position("000001", qty=3, sellable=3, avg_price=1000)
    engine._last_prices["000001"] = 1000

    engine.sell_all("000001")

    assert len(gateway.orders) == 0
