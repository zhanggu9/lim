from __future__ import annotations

import os
import threading
import time

from app.logging_config import configure_logging, configure_trade_logger, configure_chejan_logger
from app.settings import Settings
from app.status_bus import StatusBus
from infrastructure.kiwoom.kiwoom_gateway import PyKiwoomGateway
from infrastructure.ui.tk_status import StatusWindow
from interfaces.clock import SystemClock
from use_cases.trading_engine import TradingEngine


def _start_engine(engine: TradingEngine, stop_event: threading.Event) -> None:
    """엔진 루프를 실행한다."""
    while not stop_event.is_set():
        engine.process_condition_queues()
        engine.process_chejan_queue()
        time.sleep(0.05)


def _start_realtime(engine: TradingEngine, stop_event: threading.Event, sleep_sec: float) -> None:
    """실시간 체결 큐를 전용 스레드에서 처리한다."""
    interval = max(0.0, float(sleep_sec))
    while not stop_event.is_set():
        engine.process_real_data_queue()
        if interval > 0:
            time.sleep(interval)


def _start_tick_compute(
    engine: TradingEngine,
    stop_event: threading.Event,
    sleep_sec: float,
    shard_id: int,
) -> None:
    """내부 틱 큐를 소비해 캔들/RSI 연산을 수행한다."""
    interval = max(0.0, float(sleep_sec))
    while not stop_event.is_set():
        engine.process_tick_compute_queue(shard_id=shard_id)
        if interval > 0:
            time.sleep(interval)


def _start_account_refresh(engine: TradingEngine, stop_event: threading.Event, interval: float) -> None:
    """계좌/보유 갱신을 별도 스레드에서 수행한다."""
    while not stop_event.is_set():
        engine.refresh_account_info_periodic()
        time.sleep(interval)


def _start_condition_refresh(engine: TradingEngine, stop_event: threading.Event, interval: float) -> None:
    """조건식 스냅샷을 주기적으로 요청한다."""
    while not stop_event.is_set(): # 프로그램 종료 신호가 올 때까지
        engine.refresh_condition_snapshot() # 조건식 스냅샷 갱신
        time.sleep(interval)


def main() -> None:
    """애플리케이션 진입점."""
    settings_path = "settings.json"
    settings = Settings.load(settings_path)
    settings.save(settings_path)

    simple_log_enabled = bool(getattr(settings, "simple_log_enabled", False))
    logger = configure_logging(
        settings.log_file,
        settings.log_level,
        simple_enabled=simple_log_enabled,
        simple_level=getattr(settings, "simple_log_level", "WARNING"),
        max_bytes=int(getattr(settings, "log_max_bytes", 1_000_000)),
        backup_count=int(getattr(settings, "log_backup_count", 3)),
    )
    trade_logger = configure_trade_logger(
        settings.daily_trade_log_file,
        max_bytes=int(getattr(settings, "log_max_bytes", 1_000_000)),
        backup_count=int(getattr(settings, "log_backup_count", 3)),
    )
    chejan_logger = configure_chejan_logger(
        os.path.join(os.path.dirname(settings.log_file), "chejan_logs"),
        enabled=bool(getattr(settings, "chejan_log_enabled", True)) and not simple_log_enabled,
        max_bytes=int(getattr(settings, "log_max_bytes", 1_000_000)),
        backup_count=int(getattr(settings, "log_backup_count", 3)),
    )
    logger.info("자동매매 프로그램 시작")

    gateway = PyKiwoomGateway(logger, settings)
    status_bus = StatusBus()
    clock = SystemClock(settings.market_timezone)
    engine = TradingEngine(
        settings, gateway, logger, status_bus, clock, trade_logger=trade_logger, chejan_logger=chejan_logger
    )
    engine.initialize()

    stop_event = threading.Event()
    engine_thread = threading.Thread(target=_start_engine, args=(engine, stop_event), daemon=True)
    refresh_thread = threading.Thread(
        target=_start_condition_refresh,
        args=(engine, stop_event, settings.condition_refresh_seconds),
        daemon=True,
    )
    realtime_thread = threading.Thread(
        target=_start_realtime,
        args=(engine, stop_event, settings.realtime_poll_sleep_sec),
        daemon=True,
    )
    # 코드 샤드별 전용 worker를 생성한다(같은 코드의 순서 보장).
    tick_compute_threads = []
    worker_count = max(
        1,
        int(
            getattr(
                engine,
                "_tick_compute_shard_count",
                getattr(
                    settings,
                    "tick_compute_shard_count",
                    getattr(settings, "tick_compute_worker_count", 20),
                ),
            ),
        ),
    )
    tick_compute_sleep = getattr(settings, "tick_compute_sleep_sec", 0.001)
    for shard_id in range(worker_count):
        t = threading.Thread(
            target=_start_tick_compute,
            args=(engine, stop_event, tick_compute_sleep, shard_id),
            daemon=True,
        )
        tick_compute_threads.append(t)
    account_poll_interval = max(
        0.2,
        min(settings.account_refresh_seconds, settings.holdings_refresh_seconds, 1.0),
    )
    account_thread = threading.Thread(
        target=_start_account_refresh,
        args=(engine, stop_event, account_poll_interval),
        daemon=True,
    )
    engine_thread.start()
    refresh_thread.start()
    realtime_thread.start()
    for t in tick_compute_threads:
        t.start()
    account_thread.start()

    if settings.ui_enabled:
        def on_change_condition(index: int) -> None:
            """조건식 인덱스 변경을 반영한다."""
            settings.condition_index = index
            settings.save(settings_path)
            engine.change_condition_index(index)

        def on_refresh_conditions() -> None:
            """조건식 목록을 새로고침한다."""
            engine.refresh_condition_list()
            settings.save(settings_path)

        def on_change_strategy(name: str) -> None:
            """매매 전략 변경을 반영한다."""
            settings.strategy_name = name
            settings.save(settings_path)
            engine.change_strategy(name)

        def on_change_candle(source: str, value: int) -> None:
            """캔들 기준 변경을 반영한다."""
            engine.change_candle_config(source, value)
            settings.save(settings_path)

        def on_change_rsi_period(period: int) -> None:
            """RSI 기간 변경을 반영한다."""
            try:
                new_period = int(period)
            except (TypeError, ValueError):
                return
            if new_period <= 0:
                return
            engine.change_rsi_period(new_period)
            settings.save(settings_path)

        def on_change_rsi_thresholds(overbought: float, sell_half: float, sell_all: float) -> None:
            """RSI 매수/매도 기준값 변경을 반영한다."""
            try:
                overbought_value = float(overbought)
                sell_half_value = float(sell_half)
                sell_all_value = float(sell_all)
            except (TypeError, ValueError):
                return
            engine.change_rsi_thresholds(overbought_value, sell_half_value, sell_all_value)
            settings.save(settings_path)

        def on_change_order_config(buy_mode: str, buy_value: int) -> None:
            """매수 주문 금액/수량 설정 변경을 반영한다."""
            settings.buy_size_mode = buy_mode
            if buy_mode == "cash":
                settings.buy_cash = int(buy_value)
            else:
                settings.buy_qty = int(buy_value)
            settings.save(settings_path)
            engine.change_order_size_config(buy_mode, int(buy_value))

        def on_change_excluded_codes(value: str) -> None:
            """감시/자동매매 제외 종목 코드를 반영한다."""
            try:
                engine.change_excluded_codes(value)
                settings.excluded_codes = list(getattr(settings, "excluded_codes", []))
                settings.save(settings_path)
            except Exception as e:
                logger.error("제외 종목 변경 실패: %s", e)

        def on_change_pyramiding(strategy_name: str, enabled: bool) -> None:
            """전략별 피라미딩 on/off를 반영한다."""
            engine.change_pyramiding_config(strategy_name, bool(enabled))
            settings.save(settings_path)

        def on_change_cci_filter(strategy_name: str, enabled: bool) -> None:
            """전략별 CCI 필터 on/off를 반영한다."""
            engine.change_cci_filter_config(strategy_name, bool(enabled))
            settings.save(settings_path)

        def on_change_cci_threshold(strategy_name: str, entry_threshold: float, add_threshold: float) -> None:
            """전략별 CCI 기준값을 반영한다."""
            engine.change_cci_threshold_config(strategy_name, float(entry_threshold), float(add_threshold))
            settings.save(settings_path)

        def on_refresh_holdings() -> None:
            """보유 종목을 서버 기준으로 즉시 다시 조회한다."""
            engine.refresh_holdings_now()

        ui = StatusWindow(
            on_sell_all=engine.sell_all,
            on_refresh_holdings=on_refresh_holdings,
            on_change_condition=on_change_condition,
            on_refresh_conditions=on_refresh_conditions,
            on_change_strategy=on_change_strategy,
            on_change_candle=on_change_candle,
            on_change_rsi_period=on_change_rsi_period,
            on_change_rsi_thresholds=on_change_rsi_thresholds,
            on_change_order_config=on_change_order_config,
            on_change_excluded_codes=on_change_excluded_codes,
            on_change_pyramiding=on_change_pyramiding,
            on_change_cci_filter=on_change_cci_filter,
            on_change_cci_threshold=on_change_cci_threshold,
        )
        try:
            ui.run(status_bus, settings.ui_refresh_ms)
        finally:
            stop_event.set()
    else:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            stop_event.set()


if __name__ == "__main__":
    main()
