import datetime
import threading
import time
from types import SimpleNamespace

from app.settings import Settings
from app.status_bus import StatusBus
from domain.entities import Candle, TradeSignal
from use_cases.trading_engine import TradingEngine


class DummyClock:
    def __init__(self) -> None:
        self._now = datetime.datetime(2026, 2, 20, 10, 0, 0)

    def now(self) -> datetime.datetime:
        return self._now

    def advance(self, seconds: int) -> None:
        self._now = self._now + datetime.timedelta(seconds=seconds)


class DummyLogger:
    def info(self, message, *args) -> None:
        return None

    def warning(self, message, *args) -> None:
        return None

    def error(self, message, *args) -> None:
        return None

    def debug(self, message, *args) -> None:
        return None

    def exception(self, message, *args) -> None:
        return None


class DummyGateway:
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
                "code": code,
                "quantity": quantity,
                "order_type": order_type,
                "hoga_gb": hoga_gb,
            }
        )

    def get_master_code_name(self, code: str) -> str:
        return code


class SlowGateway(DummyGateway):
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
        time.sleep(0.05)
        super().send_order(rqname, screen, acc_no, order_type, code, quantity, price, hoga_gb, order_no)


def _create_engine():
    settings = Settings()
    settings.strategy_name = "livermore_pyramid"
    settings.buy_size_mode = "qty"
    settings.buy_qty = 1
    settings.livermore_retry_timeout_sec = 1.0
    settings.livermore_retry_max = 1
    clock = DummyClock()
    gateway = DummyGateway()
    engine = TradingEngine(settings, gateway, DummyLogger(), StatusBus(), clock)
    engine._allow_trading = True
    engine._account_no = "1234567890"
    return engine, gateway, clock


def _create_engine_with_gateway(gateway):
    settings = Settings()
    settings.strategy_name = "livermore_pyramid"
    settings.buy_size_mode = "qty"
    settings.buy_qty = 1
    settings.livermore_retry_timeout_sec = 1.0
    settings.livermore_retry_max = 1
    clock = DummyClock()
    engine = TradingEngine(settings, gateway, DummyLogger(), StatusBus(), clock)
    engine._allow_trading = True
    engine._account_no = "1234567890"
    return engine, gateway, clock


def test_livermore_pending_order_retries_once_then_stops():
    engine, gateway, clock = _create_engine()
    signal = TradeSignal(
        code="000001",
        side="BUY",
        quantity=1,
        reason="ENTRY 20",
        price=1000,
        tag="livermore:ENTRY_STAGE_0",
    )

    sent = engine._execute_signal(signal, candle_end="093000")
    assert sent is True
    assert len(gateway.orders) == 1
    assert len(engine._strategy_pending_orders) == 1

    clock.advance(2)
    engine._retry_pending_strategy_orders()
    assert len(gateway.orders) == 2
    assert len(engine._strategy_pending_orders) == 1

    clock.advance(2)
    engine._retry_pending_strategy_orders()
    # 최대 재시도(1회) 이후에는 pending이 삭제되고 추가 주문이 없다.
    assert len(gateway.orders) == 2
    assert len(engine._strategy_pending_orders) == 0


def test_livermore_buy_accept_status_disables_retry():
    engine, gateway, clock = _create_engine()
    signal = TradeSignal(
        code="000001",
        side="BUY",
        quantity=1,
        reason="ENTRY 20",
        price=1000,
        tag="livermore:ENTRY_STAGE_0",
    )

    sent = engine._execute_signal(signal, candle_end="093000")
    assert sent is True
    assert len(gateway.orders) == 1

    engine._handle_strategy_order_status(
        {
            "gubun": "0",
            "9001": "A000001",
            "907": "2",
            "913": "접수",
            "900": "1",
            "902": "1",
        }
    )

    clock.advance(2)
    engine._retry_pending_strategy_orders()

    assert len(gateway.orders) == 1
    assert len(engine._strategy_pending_orders) == 1


def test_livermore_buy_uses_signal_quantity_even_when_buy_mode_qty():
    engine, gateway, _clock = _create_engine()
    signal = TradeSignal(
        code="000001",
        side="BUY",
        quantity=7,
        reason="ADD_STAGE_2",
        price=1000,
        tag="livermore:ADD_STAGE_2",
    )

    engine._execute_signal(signal, candle_end="093005")
    assert len(gateway.orders) == 1
    assert gateway.orders[0]["quantity"] == 7


def test_livermore_buy_execution_clears_pending():
    engine, gateway, _clock = _create_engine()
    signal = TradeSignal(
        code="000001",
        side="BUY",
        quantity=1,
        reason="ADD_STAGE_1",
        price=1000,
        tag="livermore:ADD_STAGE_1",
    )

    engine._execute_signal(signal, candle_end="093001")
    assert len(engine._strategy_pending_orders) == 1

    execution = SimpleNamespace(code="000001", side="BUY", price=1005)
    engine._clear_pending_order_by_execution(execution)
    assert len(engine._strategy_pending_orders) == 0


def test_requires_rsi_false_strategy_runs_before_rsi_warmup():
    engine, _gateway, _clock = _create_engine()

    class DummyStrategy:
        name = "dummy_no_rsi"
        requires_rsi = False

        def __init__(self) -> None:
            self.calls = 0

        def on_rsi_update(self, code, rsi, price, position_qty, high=None, low=None):
            self.calls += 1
            return []

        def reset_code(self, code):
            return None

    dummy = DummyStrategy()
    engine._strategy = dummy
    engine._strategy_name = dummy.name

    candle = Candle(
        code="000001",
        open=1000,
        high=1005,
        low=995,
        close=1002,
        volume=10,
        tick_count=1,
        end_time="093010",
    )
    engine._handle_candle(candle)
    assert dummy.calls == 1


def test_same_livermore_signal_is_sent_once_even_when_processed_concurrently():
    gateway = SlowGateway()
    engine, gateway, _clock = _create_engine_with_gateway(gateway)
    signal = TradeSignal(
        code="000001",
        side="BUY",
        quantity=24,
        reason="ADD_STAGE_3",
        price=1000,
        tag="livermore:ADD_STAGE_3",
    )
    candle = Candle(
        code="000001",
        open=1000,
        high=1000,
        low=1000,
        close=1000,
        volume=1,
        tick_count=1,
        end_time="111802",
    )

    def worker() -> None:
        engine._process_strategy_signals(
            signals=[signal],
            candle=candle,
            rsi_for_strategy=50.0,
            candle_marker="minute:1:678",
            is_preview=False,
        )

    threads = [threading.Thread(target=worker), threading.Thread(target=worker)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(gateway.orders) == 1
