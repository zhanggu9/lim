#!/usr/bin/env python
"""Entry 조건을 상세히 검증."""

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


def detailed_condition_check():
    """Entry 조건을 하나하나 검증."""
    print("=" * 100)
    print("DETAILED ENTRY CONDITION CHECK")
    print("=" * 100)
    
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
    
    print("\nBuilding history and checking entry conditions...")
    print(f"{'Bar':>3} {'RSI':>7} {'rsi>=70':>8} {'entered':>10} {'adx_ok':>10} {'cci_ok':>10} {'entry_atr_ok':>15} {'cd_ok':>8} {'qty>0':>8}")
    print("-" * 110)
    
    for bar_idx in range(25):
        price = 10000 + bar_idx * 60
        high = price + 180
        low = price - 180
        rsi = 50 + (bar_idx / 25) * 45
        
        # Before calling strategy
        entered_before = strategy._entered_overbought.get(code, False)
        
        # Get internal state BEFORE update
        prev_rsi = strategy._last_rsi.get(code)
        prev_price = strategy._last_price.get(code)
        atr_tracker = strategy._atr_trackers.get(code)
        adx_tracker = strategy._adx_trackers.get(code)
        
        atr_val = atr_tracker._atr if atr_tracker else None
        adx_val = adx_tracker._adx if adx_tracker else None
        
        # Calculate what the conditions should be
        rsi_ok = rsi >= strategy.overbought
        entered = strategy._entered_overbought.get(code, False)
        
        adx_ok = (not strategy.use_adx_filter) or (adx_val is not None and float(adx_val) >= float(strategy.adx_threshold))
        cci_ok = True  # No CCI filter
        
        entry_atr_ok = True
        if strategy.entry_atr_mult > 0:
            entry_atr_ok = (
                prev_price is not None
                and atr_val is not None
                and atr_val > 0
                and float(price) >= (float(prev_price) + (float(atr_val) * float(strategy.entry_atr_mult)))
            )
        
        cd_ok = cooldown.allow(code)
        
        # Calculate qty
        base_cash = int(max(0.0, float(strategy.buy_cash) * float(strategy.stage_multipliers[0])))
        qty = sizer.buy_quantity(base_cash, price)
        qty_ok = qty > 0
        
        # Call strategy
        signals = strategy.on_rsi_update(
            code=code,
            rsi=rsi,
            price=price,
            position_qty=0,
            high=high,
            low=low,
        )
        
        # Print row
        entered_status = "F" if entered else "T"  # T means can enter
        print(f"{bar_idx:3d} {rsi:7.2f} {str(rsi_ok):>8} {entered_status:>10} {str(adx_ok):>10} {str(cci_ok):>10} {str(entry_atr_ok):>15} {str(cd_ok):>8} {str(qty_ok):>8}", end="")
        
        # Check if should have entered
        if rsi_ok and not entered and adx_ok and cci_ok and entry_atr_ok and cd_ok and qty_ok:
            print(" <- SHOULD ENTER!")
            if signals:
                print(f"      ✓ Got signal: {signals[0].reason}")
            else:
                print(f"      ✗ NO SIGNAL!")
        else:
            if signals:
                print(f" GOT SIGNAL: {signals[0].reason}")
            else:
                print()
    
    print("\n" + "=" * 100)
    print("ANALYSIS")
    print("=" * 100)
    
    # Check when all conditions are met
    for bar_idx in range(25):
        price = 10000 + bar_idx * 60
        high = price + 180
        low = price - 180
        rsi = 50 + (bar_idx / 25) * 45
        
        # Build up state
        strategy.on_rsi_update(code=code, rsi=rsi, price=price, position_qty=0, high=high, low=low)
    
    # Final state
    print(f"\nFinal state:")
    print(f"  - _entered_overbought: {strategy._entered_overbought.get(code, False)}")
    print(f"  - _last_rsi: {strategy._last_rsi.get(code)}")
    print(f"  - _last_price: {strategy._last_price.get(code)}")
    
    atr_tracker = strategy._atr_trackers.get(code)
    if atr_tracker:
        print(f"  - ATR: {atr_tracker._atr}")
    
    adx_tracker = strategy._adx_trackers.get(code)
    if adx_tracker:
        print(f"  - ADX: {adx_tracker._adx}")


if __name__ == "__main__":
    detailed_condition_check()
