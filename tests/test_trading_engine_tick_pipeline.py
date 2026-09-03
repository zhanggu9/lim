import datetime

from app.settings import Settings
from app.status_bus import StatusBus
from use_cases.trading_engine import TradingEngine


class DummyClock:
    def __init__(self) -> None:
        self._now = datetime.datetime(2026, 2, 20, 10, 0, 0)

    def now(self) -> datetime.datetime:
        return self._now


class DummyLogger:
    def info(self, message, *args) -> None:
        return None

    def warning(self, message, *args) -> None:
        return None

    def error(self, message, *args) -> None:
        return None


class DummyGateway:
    def __init__(self) -> None:
        self._real_data = []

    def get_real_data(self):
        if self._real_data:
            return self._real_data.pop(0)
        return None

    def get_master_code_name(self, code: str) -> str:
        return code

    def set_real_reg(self, screen: str, codes, fids, opt_type: int) -> None:
        return None

    def disconnect_real(self, screen: str) -> None:
        return None


def test_realtime_ingest_and_compute_are_separated():
    settings = Settings()
    settings.ticks_per_candle = 1
    settings.rsi_period = 1
    gateway = DummyGateway()
    engine = TradingEngine(settings, gateway, DummyLogger(), StatusBus(), DummyClock())
    engine._last_watchlist = ["000001"]
    gateway._real_data = [
        {"code": "000001", "10": "1000", "15": "1", "20": "093001"},
        {"code": "000001", "10": "1010", "15": "1", "20": "093002"},
    ]

    engine.process_real_data_queue()
    assert engine._last_rsi_values == {}

    engine.process_tick_compute_queue()
    assert "000001" in engine._last_rsi_values


def test_same_code_is_processed_only_by_its_shard_fifo():
    settings = Settings()
    settings.ticks_per_candle = 2
    settings.rsi_period = 1
    settings.tick_compute_shard_count = 4
    settings.tick_queue_maxsize = 100
    gateway = DummyGateway()
    engine = TradingEngine(settings, gateway, DummyLogger(), StatusBus(), DummyClock())
    engine._last_watchlist = ["000001"]
    gateway._real_data = [
        {"code": "000001", "10": "1000", "15": "1", "20": "093001"},
        {"code": "000001", "10": "1010", "15": "1", "20": "093002"},
        {"code": "000001", "10": "1020", "15": "1", "20": "093003"},
        {"code": "000001", "10": "1030", "15": "1", "20": "093004"},
    ]

    engine.process_real_data_queue()
    shard = engine._tick_shard_index("000001")
    other_shard = (shard + 1) % len(engine._tick_shard_queues)

    engine.process_tick_compute_queue(shard_id=other_shard)
    assert "000001" not in engine._last_rsi_values

    engine.process_tick_compute_queue(shard_id=shard)
    assert "000001" in engine._last_rsi_values
    closes = [c.close for c in list(engine._recent_candles_by_code["000001"])]
    assert closes[-2:] == [1010, 1030]


def test_realtime_ingest_accepts_price_only_fid():
    settings = Settings()
    settings.real_fids = ["10"]
    settings.ticks_per_candle = 1
    settings.rsi_period = 1
    gateway = DummyGateway()
    engine = TradingEngine(settings, gateway, DummyLogger(), StatusBus(), DummyClock())
    engine._last_watchlist = ["000001"]
    gateway._real_data = [
        {"code": "000001", "10": "1000"},
        {"code": "000001", "10": "1010"},
    ]

    engine.process_real_data_queue()
    engine.process_tick_compute_queue()

    assert "000001" in engine._last_rsi_values
    assert engine._last_prices["000001"] == 1010
