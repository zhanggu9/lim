import json

from app.settings import Settings


def test_settings_roundtrip_keeps_buy_order_fields(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings()
    settings.buy_size_mode = "qty"
    settings.buy_qty = 11

    settings.save(str(path))
    loaded = Settings.load(str(path))

    assert loaded.buy_size_mode == "qty"
    assert loaded.buy_qty == 11


def test_settings_load_keeps_legacy_sell_fields(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "buy_size_mode": "cash",
                "buy_qty": 0,
                "sell_size_mode": "cash",
                "sell_cash": 3000000,
                "sell_qty": 2,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    loaded = Settings.load(str(path))

    assert loaded.sell_size_mode == "cash"
    assert loaded.sell_cash == 3_000_000
    assert loaded.sell_qty == 2


def test_settings_save_omits_sell_fields(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings()
    settings.sell_size_mode = "cash"
    settings.sell_cash = 3_000_000
    settings.sell_qty = 2

    settings.save(str(path))
    data = json.loads(path.read_text(encoding="utf-8"))

    assert "sell_size_mode" not in data
    assert "sell_cash" not in data
    assert "sell_qty" not in data


def test_settings_load_maps_legacy_api_rate_limit_to_tr_limit(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "api_rate_limit_per_sec": 3,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    loaded = Settings.load(str(path))

    assert loaded.tr_rate_limit_per_sec == 3


def test_settings_roundtrip_keeps_realtime_threshold_fields(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings()
    settings.real_ingress_buffer_maxsize = 7000
    settings.real_ingress_drain_batch = 700
    settings.ui_realtime_warn_queue_ratio = 0.8
    settings.ui_realtime_warn_drop_count = 2
    settings.ui_realtime_warn_limit_wait_ms = 350.0

    settings.save(str(path))
    loaded = Settings.load(str(path))

    assert loaded.real_ingress_buffer_maxsize == 7000
    assert loaded.real_ingress_drain_batch == 700
    assert loaded.ui_realtime_warn_queue_ratio == 0.8
    assert loaded.ui_realtime_warn_drop_count == 2
    assert loaded.ui_realtime_warn_limit_wait_ms == 350.0


def test_settings_roundtrip_keeps_simple_log_fields(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings()
    settings.simple_log_enabled = True
    settings.simple_log_level = "ERROR"
    settings.log_max_bytes = 123456
    settings.log_backup_count = 2
    settings.chejan_log_enabled = False

    settings.save(str(path))
    loaded = Settings.load(str(path))

    assert loaded.simple_log_enabled is True
    assert loaded.simple_log_level == "ERROR"
    assert loaded.log_max_bytes == 123456
    assert loaded.log_backup_count == 2
    assert loaded.chejan_log_enabled is False


def test_settings_roundtrip_keeps_global_rate_limit(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings()
    settings.global_rate_limit_per_sec = 4
    settings.tr_rate_limit_per_sec = 4
    settings.order_rate_limit_per_sec = 4

    settings.save(str(path))
    loaded = Settings.load(str(path))

    assert loaded.global_rate_limit_per_sec == 4


def test_settings_roundtrip_keeps_excluded_codes(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings()
    settings.excluded_codes = ["005930", "000660"]

    settings.save(str(path))
    loaded = Settings.load(str(path))

    assert loaded.excluded_codes == ["005930", "000660"]


def test_settings_roundtrip_keeps_livermore_fields(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings()
    settings.strategy_name = "livermore_pyramid"
    settings.livermore_breakout_period = 21
    settings.livermore_exit_period = 11
    settings.livermore_add_atr_mult = 0.9
    settings.livermore_atr_trailing_mult = 2.7
    settings.livermore_atr_buffer_mult = 0.6
    settings.livermore_exit_confirm_bars = 2
    settings.livermore_stage_multipliers = [1.0, 0.9, 0.7]
    settings.livermore_retry_timeout_sec = 17.0
    settings.livermore_retry_max = 2

    settings.save(str(path))
    loaded = Settings.load(str(path))

    assert loaded.strategy_name == "livermore_pyramid"
    assert loaded.livermore_breakout_period == 21
    assert loaded.livermore_exit_period == 11
    assert loaded.livermore_add_atr_mult == 0.9
    assert loaded.livermore_atr_trailing_mult == 2.7
    assert loaded.livermore_atr_buffer_mult == 0.6
    assert loaded.livermore_exit_confirm_bars == 2
    assert loaded.livermore_stage_multipliers == [1.0, 0.9, 0.7]
    assert loaded.livermore_retry_timeout_sec == 17.0
    assert loaded.livermore_retry_max == 2


def test_settings_roundtrip_keeps_queue_policy_fields(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings()
    settings.tick_compute_shard_count = 8
    settings.queue_policy_mode = "hybrid"
    settings.tick_queue_soft_ratio = 0.75
    settings.tick_queue_hard_ratio = 0.93
    settings.tick_queue_overload_wait_ms = 4.0
    settings.tick_queue_emergency_drop_batch = 33
    settings.real_ingress_soft_ratio = 0.77
    settings.real_ingress_hard_ratio = 0.96
    settings.legacy_single_queue = True

    settings.save(str(path))
    loaded = Settings.load(str(path))

    assert loaded.tick_compute_shard_count == 8
    assert loaded.queue_policy_mode == "hybrid"
    assert loaded.tick_queue_soft_ratio == 0.75
    assert loaded.tick_queue_hard_ratio == 0.93
    assert loaded.tick_queue_overload_wait_ms == 4.0
    assert loaded.tick_queue_emergency_drop_batch == 33
    assert loaded.real_ingress_soft_ratio == 0.77
    assert loaded.real_ingress_hard_ratio == 0.96
    assert loaded.legacy_single_queue is True


def test_settings_roundtrip_keeps_rsi_cci_fields(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings()
    settings.rsi_use_cci_filter = True
    settings.rsi_cci_period = 25
    settings.rsi_cci_entry_threshold = 10.0
    settings.rsi_cci_add_threshold = 120.0

    settings.save(str(path))
    loaded = Settings.load(str(path))

    assert loaded.rsi_use_cci_filter is True
    assert loaded.rsi_cci_period == 25
    assert loaded.rsi_cci_entry_threshold == 10.0
    assert loaded.rsi_cci_add_threshold == 120.0


def test_settings_roundtrip_keeps_pullback_fields(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings()
    settings.pullback_retrace_atr_mult = 0.9
    settings.pullback_rebreak_buffer_atr_mult = 0.3
    settings.pullback_invalidate_atr_mult = 0.6
    settings.pullback_max_bars = 8

    settings.save(str(path))
    loaded = Settings.load(str(path))

    assert loaded.pullback_retrace_atr_mult == 0.9
    assert loaded.pullback_rebreak_buffer_atr_mult == 0.3
    assert loaded.pullback_invalidate_atr_mult == 0.6
    assert loaded.pullback_max_bars == 8
