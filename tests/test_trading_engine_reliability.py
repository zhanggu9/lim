import datetime

from app.settings import Settings
from app.status_bus import StatusBus
from domain.entities import TradeSignal
from domain.indicators import RsiTracker
from use_cases.trading_engine import TradingEngine


class DummyClock:
    """고정 시각을 반환하는 테스트용 시계."""

    def __init__(self) -> None:
        self._now = datetime.datetime(2026, 2, 20, 10, 0, 0)

    def now(self) -> datetime.datetime:
        return self._now


class DummyLogger:
    """로그 메시지를 수집하는 테스트용 로거."""

    def __init__(self) -> None:
        self.warning_messages = []

    def info(self, message, *args) -> None:
        return None

    def warning(self, message, *args) -> None:
        self.warning_messages.append((message, args))

    def error(self, message, *args) -> None:
        return None


class DummyGateway:
    """엔진 검증에 필요한 최소 게이트웨이 스텁."""

    def __init__(self) -> None:
        self.real_reg_calls = []
        self._real_condition_queue = []

    def get_tr_condition(self):
        return None

    def get_real_condition(self):
        if self._real_condition_queue:
            return self._real_condition_queue.pop(0)
        return None

    def set_real_reg(self, screen: str, codes, fids, opt_type: int) -> None:
        self.real_reg_calls.append((screen, list(codes), list(fids), opt_type))

    def disconnect_real(self, screen: str) -> None:
        return None

    def get_master_code_name(self, code: str) -> str:
        return code

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
        return None


def test_condition_queue_batches_real_reg_even_without_min_interval():
    """실시간 조건식 다건 이벤트를 한 루프에서 1회 SetRealReg로 반영한다."""
    settings = Settings()
    settings.real_reg_min_interval_sec = 0.0
    gateway = DummyGateway()
    gateway._real_condition_queue = [
        {"code": "000001", "type": "I"},
        {"code": "000002", "type": "I"},
    ]
    engine = TradingEngine(settings, gateway, DummyLogger(), StatusBus(), DummyClock())

    engine.process_condition_queues()

    assert len(gateway.real_reg_calls) == 1
    assert set(gateway.real_reg_calls[0][1]) == {"000001", "000002"}


def test_rsi_tracker_is_kept_on_untrack_by_default():
    """기본 설정에서는 일시 이탈 후 재편입을 위해 RSI 상태를 유지한다."""
    settings = Settings()
    gateway = DummyGateway()
    engine = TradingEngine(settings, gateway, DummyLogger(), StatusBus(), DummyClock())
    code = "000001"

    engine._watchlist.apply_condition_event(code, "I")
    engine._sync_real_registration()
    engine._rsi_trackers[code] = RsiTracker(period=14)

    engine._watchlist.apply_condition_event(code, "D")
    engine._sync_real_registration()

    assert code in engine._rsi_trackers


def test_order_price_uses_latest_tick_price_first():
    """주문 가격 계산은 신호 가격보다 최신 틱 가격을 우선한다."""
    settings = Settings()
    gateway = DummyGateway()
    engine = TradingEngine(settings, gateway, DummyLogger(), StatusBus(), DummyClock())
    code = "000001"
    engine._last_prices[code] = 1200
    signal = TradeSignal(code=code, side="BUY", quantity=1, reason="test", price=1000)

    price = engine._resolve_order_price(signal)

    assert price == 1205
