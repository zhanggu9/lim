from __future__ import annotations

import datetime

from app.settings import Settings
from use_cases.cooldown import CooldownTracker
from use_cases.market_hours import MarketHours
from use_cases.order_sizer import OrderSizer
from use_cases.trend_orchestrator import TrendOrchestrator


class FixedClock:
    def now(self):
        return datetime.datetime(2026, 2, 9, 10, 0, tzinfo=datetime.timezone.utc)


def make_strategy(**overrides):
    settings = Settings()
    settings.buy_cash = 100_000
    settings.trend_breakout_period = 5
    settings.trend_momentum_bars = 2
    settings.trend_atr_period = 3
    for key, value in overrides.items():
        setattr(settings, key, value)
    clock = FixedClock()
    return TrendOrchestrator(
        settings,
        CooldownTracker(seconds=0, clock=clock),
        OrderSizer(),
        MarketHours(start="09:00", end="15:30", timezone="UTC"),
    )


def test_trend_entry_requires_minimum_breakout_distance():
    strategy = make_strategy(trend_min_breakout_atr=1.10)
    for price in (100, 101, 102, 103, 104):
        strategy.on_rsi_update("000001", 0, price, 0, high=price, low=price)

    signals = strategy.on_rsi_update("000001", 0, 105, 0, high=105, low=105)
    assert not signals
    assert strategy.state["000001"].phase == "SETUP"


def test_trend_entry_requires_close_near_candle_high():
    strategy = make_strategy(trend_min_close_location=0.70)
    for price in (100, 100, 100, 100, 100):
        strategy.on_rsi_update("000002", 0, price, 0, high=price, low=price)

    signals = strategy.on_rsi_update("000002", 0, 101, 0, high=105, low=99)
    assert not signals
    assert strategy.state["000002"].phase == "SETUP"


def test_trend_entry_accepts_strong_breakout_with_close_at_high():
    strategy = make_strategy(trend_min_breakout_atr=0.15, trend_min_close_location=0.70)
    for price in (100, 100, 100, 100, 100, 101, 102):
        signals = strategy.on_rsi_update("000003", 0, price, 0, high=price, low=price)

    assert signals
    assert signals[-1].tag == "trend:ENTRY"
