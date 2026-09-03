#!/usr/bin/env python
"""Cooldown과 qty 체크."""

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


def check_cooldown_and_qty():
    """Cooldown과 qty를 상세히 추적."""
    print("=" * 90)
    print("CHECKING COOLDOWN AND QTY")
    print("=" * 90)
    
    clock = FixedClock(_seoul_time(10, 0, 0))
    market_hours = MarketHours(start="09:00", end="15:30", timezone="Asia/Seoul")
    cooldown = CooldownTracker(seconds=10, clock=clock)  # 10초 쿨다운
    sizer = OrderSizer()
    
    strategy = RsiStrategy(
        overbought=70.0,
        sell_half=29.0,
        sell_all=19.0,
        buy_cash=1_000_000,  # 100만원
        cooldown=cooldown,
        order_sizer=sizer,
        market_hours=market_hours,
        entry_atr_mult=0.5,
        use_adx_filter=True,
        adx_threshold=23.0,
    )
    
    code = "TEST"
    
    print(f"\nConfiguration:")
    print(f"  - buy_cash: {strategy.buy_cash:,}")
    print(f"  - stage_multipliers[0]: {strategy.stage_multipliers[0]}")
    print(f"  - cooldown_seconds: {cooldown._seconds}")
    
    print(f"\n{'Bar':>3} {'RSI':>7} {'Price':>7} {'qty':>6} {'cd_ok?':>7} {'cd_now':>10} RESULT")
    print("-" * 90)
    
    for candle_idx in range(20):
        price = 10000 + candle_idx * 60
        high = price + 180
        low = price - 180
        rsi = 50 + (candle_idx / 25) * 45
        
        # Check cooldown BEFORE calling strategy
        cd_ok_before = cooldown.allow(code)
        cd_now_before = clock.now()
        
        signals = strategy.on_rsi_update(
            code=code,
            rsi=rsi,
            price=price,
            position_qty=0,
            high=high,
            low=low,
        )
        
        # Calculate what qty would be
        base_cash = int(max(0.0, float(strategy.buy_cash) * float(strategy.stage_multipliers[0])))
        qty = sizer.buy_quantity(base_cash, price)
        
        print(f"{candle_idx:3d} {rsi:7.2f} {price:7d} {qty:6d} {str(cd_ok_before):>7} {cd_now_before.strftime('%H:%M:%S')} ", end="")
        
        if signals:
            print(f"ENTERED! {signals[0].reason}")
        else:
            if rsi < 70:
                print("RSI < 70")
            else:
                # All other conditions must have failed
                atr_tracker = strategy._atr_trackers.get(code)
                adx_tracker = strategy._adx_trackers.get(code)
                atr_val = atr_tracker._atr if atr_tracker else None
                adx_val = adx_tracker._adx if adx_tracker else None
                
                atr_ok = (strategy.entry_atr_mult == 0) or (atr_val is not None and atr_val > 0)
                adx_ok = (not strategy.use_adx_filter) or (adx_val is not None and adx_val >= strategy.adx_threshold)
                
                if not atr_ok:
                    print("ATR not ready")
                elif not adx_ok:
                    print(f"ADX {adx_val:.1f} < {strategy.adx_threshold}")
                elif not cd_ok_before:
                    print("Cooldown blocking")
                elif qty == 0:
                    print("qty=0 (invalid)")
                else:
                    print("Unknown reason")
    
    print("\n" + "=" * 90)
    print("RESULT SUMMARY")
    print("=" * 90)
    print(f"\nNo entry signal was generated in {20} bars!")
    print(f"\nLikely causes:")
    print(f"  1. Cooldown blocked the entry")
    print(f"  2. Order sizer returned qty=0")
    print(f"  3. RSI >= 70 but ADX/ATR not ready")


def test_with_zero_cooldown():
    """쿨다운 없이 테스트."""
    print("\n\n" + "=" * 90)
    print("TEST WITH ZERO COOLDOWN")
    print("=" * 90)
    
    clock = FixedClock(_seoul_time(10, 0, 0))
    market_hours = MarketHours(start="09:00", end="15:30", timezone="Asia/Seoul")
    cooldown = CooldownTracker(seconds=0, clock=clock)  # No cooldown
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
    
    print("\nSimulating with 0-second cooldown...")
    for candle_idx in range(20):
        price = 10000 + candle_idx * 60
        high = price + 180
        low = price - 180
        rsi = 50 + (candle_idx / 25) * 45
        
        signals = strategy.on_rsi_update(
            code=code,
            rsi=rsi,
            price=price,
            position_qty=0,
            high=high,
            low=low,
        )
        
        if signals:
            print(f"✓ Bar {candle_idx}: Entry at RSI={rsi:.2f}, Price={price}")
            print(f"  Reason: {signals[0].reason}")
            return True
    
    print("✗ Still no entry with 0-second cooldown!")
    return False


if __name__ == "__main__":
    check_cooldown_and_qty()
    test_with_zero_cooldown()
