from __future__ import annotations

import json

from app.settings import Settings

# sitecustomize.py supplies the compatibility persistence patch used by the app.
import sitecustomize  # noqa: F401,E402


def test_strategy_change_preserves_unknown_trend_and_sell_settings(tmp_path):
    path = tmp_path / "settings.json"
    original = {
        "strategy_name": "donchian_breakout",
        "trend_breakout_period": 17,
        "trend_exit_period": 7,
        "trend_adx_threshold": 22.5,
        "trend_pyramiding_enabled": False,
        "sell_size_mode": "cash",
        "sell_cash": 123456,
        "sell_qty": 9,
        "future_setting": {"keep": True},
    }
    path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")

    settings = Settings.load(str(path))
    assert settings.trend_breakout_period == 17
    assert settings.trend_exit_period == 7
    assert settings.trend_adx_threshold == 22.5
    assert settings.trend_pyramiding_enabled is False

    settings.strategy_name = "trend_combo"
    settings.save(str(path))

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["strategy_name"] == "trend_combo"
    assert saved["trend_breakout_period"] == 17
    assert saved["trend_exit_period"] == 7
    assert saved["trend_adx_threshold"] == 22.5
    assert saved["trend_pyramiding_enabled"] is False
    assert saved["sell_size_mode"] == "cash"
    assert saved["sell_cash"] == 123456
    assert saved["sell_qty"] == 9
    assert saved["future_setting"] == {"keep": True}
