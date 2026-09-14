from __future__ import annotations

import datetime

from app.settings import Settings
from use_cases.cooldown import CooldownTracker
from use_cases.market_hours import MarketHours
from use_cases.order_sizer import OrderSizer
from use_cases.trend_orchestrator import TrendOrchestrator


class FixedClock:
    def __init__(self):
        self._now = datetime.datetime(2026, 2, 9, 10, 0, tzinfo=datetime.timezone.utc)

    def now(self):
        return self._now


def test_trend_orchestrator_enters_after_breakout_and_momentum():
    clock = FixedClock()
    cooldown = CooldownTracker(seconds=0, clock=clock)
    market_hours = MarketHours(start="09:00", end="15:30", timezone="UTC")
    settings = Settings()
    settings.buy_cash = 100_000
    settings.trend_breakout_period = 10
    settings.trend_momentum_bars = 3
    settings.trend_atr_period = 5
    settings.trend_adx_period = 5
    settings.trend_max_chase_atr_mult = 2.0
    settings.trend_pyramiding_enabled = False

    strategy = TrendOrchestrator(settings, cooldown, OrderSizer(), market_hours)

    prices = [100] * 10 + [101, 102, 103, 104, 105]
    signals = []
    for price in prices:
        signals = strategy.on_rsi_update("000001", 0, price, 0, high=price, low=price)

    assert signals
    assert signals[-1].side == "BUY"
    assert signals[-1].tag == "trend:ENTRY"
    assert signals[-1].quantity > 0


def test_trend_orchestrator_stops_position_when_price_breaks_atr_stop():
    clock = FixedClock()
    cooldown = CooldownTracker(seconds=0, clock=clock)
    market_hours = MarketHours(start="09:00", end="15:30", timezone="UTC")
    settings = Settings()
    settings.buy_cash = 100_000
    settings.trend_atr_period = 3
    settings.trend_stop_atr_mult = 1.0
    settings.trend_take_profit_pct = 100.0
    settings.trend_trailing_atr_mult = 10.0

    strategy = TrendOrchestrator(settings, cooldown, OrderSizer(), market_hours)

    for price in (100, 101, 102, 103, 104):
        strategy.on_rsi_update("000001", 0, price, 0, high=price, low=price)

    signals = strategy.on_rsi_update("000001", 0, 95, 10, high=95, low=95)

    assert signals
    assert signals[-1].side == "SELL"
    assert signals[-1].tag == "trend:STOP"
    assert signals[-1].quantity == 10
