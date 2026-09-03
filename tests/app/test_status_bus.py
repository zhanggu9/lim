import datetime

from app.status_bus import StatusBus, StatusSnapshot


def _snapshot(last_signal: str) -> StatusSnapshot:
    return StatusSnapshot(
        server_mode="모의",
        account_no="1111111111",
        condition_index=0,
        condition_name="cond",
        strategy_name="rsi_grid",
        candle_source="tick",
        ticks_per_candle=60,
        minutes_per_candle=1,
        rsi_period=14,
        condition_version=0,
        strategy_version=0,
        candle_version=0,
        rsi_period_version=0,
        buy_order_version=0,
        exclude_version=0,
        buy_size_mode="cash",
        buy_size_value=1_000_000,
        excluded_codes_text="",
        excluded_items=[],
        watchlist_count=0,
        holding_count=0,
        last_signal=last_signal,
        last_rsi="-",
        last_update=datetime.datetime(2026, 2, 24, 10, 0, 0),
        realtime_status="-",
        realtime_status_level="ok",
        real_ingress_queue_size=0,
        tick_compute_queue_size=0,
        tick_compute_queue_capacity=10000,
        tick_drop_count=0,
        tr_limit_wait_ms_1s=0.0,
        order_limit_wait_ms_1s=0.0,
        watchlist_names="-",
        holdings_summary="-",
        rsi_summary="-",
        rsi_items=[],
        account_summary="-",
        daily_trade_details="-",
        daily_trade_items=[],
        condition_items=[],
        strategy_items=[],
        holdings_items=[],
    )


def test_try_get_returns_latest_snapshot_when_queue_backlog_exists():
    bus = StatusBus()
    bus.publish(_snapshot("first"))
    bus.publish(_snapshot("second"))
    bus.publish(_snapshot("latest"))

    snapshot = bus.try_get()

    assert snapshot is not None
    assert snapshot.last_signal == "latest"
    assert bus.try_get() is None


def test_try_get_returns_none_when_empty():
    bus = StatusBus()

    assert bus.try_get() is None
