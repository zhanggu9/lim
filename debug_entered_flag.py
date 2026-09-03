#!/usr/bin/env python
"""_entered_overbought 플래그 추적."""

import sys
import datetime

sys.path.insert(0, 'src')

from use_cases.strategy import RsiStrategy
from use_cases.order_sizer import OrderSizer
from use_cases.cooldown import CooldownTracker
from use_cases.market_hours import MarketHours


class FixedClock:
    def __init__(self, now: datetime.datetime):
        self._now = now
    def now(self) -> datetime.datetime:
        return self._now


def _seoul_time(hour: int, minute: int, second: int = 0) -> datetime.datetime:
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Asia/Seoul")
    except Exception:
        import pytz
        tz = pytz.timezone("Asia/Seoul")
    return datetime.datetime(2026, 2, 9, hour, minute, second, tzinfo=tz)


def trace_entered_flag():
    """_entered_overbought 플래그의 변화를 추적."""
    print("=" * 80)
    print("TRACING _entered_overbought FLAG")
    print("=" * 80)
    
    clock = FixedClock(_seoul_time(10, 0, 0))
    market_hours = MarketHours(start="09:00", end="15:30", timezone="Asia/Seoul")
    cooldown = CooldownTracker(seconds=0, clock=clock)
    sizer = OrderSizer()
    
    strategy = RsiStrategy(
        overbought=70.0,
        sell_half=29.0,
        sell_all=19.0,
        buy_cash=1_000_000,
        cooldown=cooldown,
        order_sizer=sizer,
        market_hours=market_hours,
        entry_atr_mult=0.5,
        use_adx_filter=True,
        adx_threshold=23.0,
    )
    
    code = "TEST"
    
    print("\nSimulating 35 candles with gradual RSI increase...")
    print(f"{'Bar':>3} {'RSI':>7} {'Price':>7} {'High':>7} {'Low':>7} entered? signals")
    print("-" * 80)
    
    for candle_idx in range(35):
        price = 10000 + candle_idx * 50
        high = price + 150
        low = price - 150
        rsi = 40 + (candle_idx / 35) * 50  # Gradually increase from 40 to 90
        
        signals = strategy.on_rsi_update(
            code=code,
            rsi=rsi,
            price=price,
            position_qty=0,
            high=high,
            low=low,
        )
        
        entered = strategy._entered_overbought.get(code, False)
        print(f"{candle_idx:3d} {rsi:7.2f} {price:7d} {high:7d} {low:7d} {str(entered):8s} {len(signals)} signal(s)")
        
        if signals:
            for sig in signals:
                print(f"      >>> {sig.side} {sig.quantity} @ {sig.price}: {sig.reason}")
    
    print("\n" + "=" * 80)
    print("ANALYSIS")
    print("=" * 80)
    
    # Check final state
    final_entered = strategy._entered_overbought.get(code, False)
    final_atr = strategy._atr_trackers.get(code)
    final_adx = strategy._adx_trackers.get(code)
    
    print(f"\nFinal state after 35 bars:")
    print(f"  - _entered_overbought[{code}]: {final_entered}")
    print(f"  - Last RSI: ~89.29")
    if final_atr:
        print(f"  - ATR value: {final_atr._atr}")
    if final_adx:
        print(f"  - ADX value: {final_adx._adx}")
    
    if final_entered:
        print("\n✓ Entry occurred (flag set to True)")
    else:
        print("\n✗ Entry NEVER occurred (flag still False)")
        print("\nThis means one of the following:")
        print("  1. RSI never reached 70 (but it did: ~89 at end)")
        print("  2. ATR not initialized when RSI reached 70")
        print("  3. ADX not high enough when RSI reached 70")
        print("  4. Cooldown prevented entry")
        print("  5. Entry qty was 0")


def check_condition_progression():
    """각 조건의 시간에 따른 변화."""
    print("\n\n" + "=" * 80)
    print("CONDITION PROGRESSION")
    print("=" * 80)
    
    clock = FixedClock(_seoul_time(10, 0, 0))
    market_hours = MarketHours(start="09:00", end="15:30", timezone="Asia/Seoul")
    cooldown = CooldownTracker(seconds=0, clock=clock)
    sizer = OrderSizer()
    
    strategy = RsiStrategy(
        overbought=70.0,
        sell_half=29.0,
        sell_all=19.0,
        buy_cash=1_000_000,
        cooldown=cooldown,
        order_sizer=sizer,
        market_hours=market_hours,
        entry_atr_mult=0.5,
        use_adx_filter=True,
        adx_threshold=23.0,
    )
    
    code = "TEST"
    
    print("\nMonitoring conditions when RSI passes 70...")
    print(f"{'Bar':>3} {'RSI':>7} {'>=70?':>6} {'ATR':>8} {'ADX':>8} {'atr_ok?':>8} {'adx_ok?':>8} {'allowed?':>8} SIGNAL")
    print("-" * 90)
    
    for candle_idx in range(25):
        price = 10000 + candle_idx * 60
        high = price + 180
        low = price - 180
        rsi = 50 + (candle_idx / 25) * 45  # 50 -> 95
        
        # Manually check conditions before calling update
        strategy.on_rsi_update(code=code, rsi=rsi, price=price, position_qty=0, high=high, low=low)
        
        # Get internal state
        entered = strategy._entered_overbought.get(code, False)
        atr_tracker = strategy._atr_trackers.get(code)
        adx_tracker = strategy._adx_trackers.get(code)
        
        atr_val = atr_tracker._atr if atr_tracker else None
        adx_val = adx_tracker._adx if adx_tracker else None
        
        # Check conditions
        rsi_ok = rsi >= 70
        atr_ok = (strategy.entry_atr_mult == 0) or (atr_val is not None and atr_val > 0)
        adx_ok = (not strategy.use_adx_filter) or (adx_val is not None and adx_val >= strategy.adx_threshold)
        cooldown_ok = cooldown.allow(code) or entered  # Already entered means this doesn't matter
        
        print(f"{candle_idx:3d} {rsi:7.2f} {str(rsi_ok):>6} {str(atr_val):>8} {str(adx_val):>8} {str(atr_ok):>8} {str(adx_ok):>8} {str(cooldown_ok):>8}", end="")
        
        if rsi_ok and atr_ok and adx_ok and not entered:
            print(" <- SHOULD ENTER!")
        else:
            print()


if __name__ == "__main__":
    trace_entered_flag()
    check_condition_progression()
