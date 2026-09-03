#!/usr/bin/env python
"""수정 후 RSI >= 70 매수 테스트."""

import sys
import datetime
import json

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


def test_after_fix():
    """수정 후 RSI >= 70에서 매수가 되는지 테스트."""
    print("=" * 80)
    print("TEST: RSI Entry AFTER FIX (entry_atr_mult=0.0)")
    print("=" * 80)
    
    # Load settings from settings.json to verify
    with open('settings.json', 'r') as f:
        settings = json.load(f)
    
    print(f"\nSettings:")
    print(f"  - rsi_entry_atr_mult: {settings.get('rsi_entry_atr_mult')}")
    print(f"  - rsi_use_adx_filter: {settings.get('rsi_use_adx_filter')}")
    print(f"  - rsi_adx_threshold: {settings.get('rsi_adx_threshold')}")
    print(f"  - rsi_overbought: {settings.get('rsi_overbought')}")
    
    clock = FixedClock(_seoul_time(10, 0, 0))
    market_hours = MarketHours(start="09:00", end="15:30", timezone="Asia/Seoul")
    cooldown = CooldownTracker(seconds=0, clock=clock)
    sizer = OrderSizer()
    
    strategy = RsiStrategy(
        overbought=float(settings.get('rsi_overbought', 70.0)),
        sell_half=float(settings.get('rsi_sell_half', 29.0)),
        sell_all=float(settings.get('rsi_sell_all', 19.0)),
        buy_cash=int(settings.get('buy_cash', 1_000_000)),
        cooldown=cooldown,
        order_sizer=sizer,
        market_hours=market_hours,
        entry_atr_mult=float(settings.get('rsi_entry_atr_mult', 0.0)),
        add_atr_mult=float(settings.get('rsi_add_atr_mult', 1.0)),
        use_adx_filter=bool(settings.get('rsi_use_adx_filter', False)),
        adx_threshold=float(settings.get('rsi_adx_threshold', 25.0)),
    )
    
    code = "005930"
    
    print("\nSimulating 30 candles...")
    for bar_idx in range(30):
        price = 10000 + bar_idx * 50
        high = price + 100
        low = price - 100
        rsi = 40 + (bar_idx / 30) * 50  # 40 ~ 90
        
        signals = strategy.on_rsi_update(
            code=code,
            rsi=rsi,
            price=price,
            position_qty=0,
            high=high,
            low=low,
        )
        
        if bar_idx % 5 == 0 or signals:
            print(f"  Bar {bar_idx:2d}: RSI={rsi:6.2f}, Price={price:6d} ", end="")
            if signals:
                print(f"✓ ENTRY!")
                for sig in signals:
                    print(f"            {sig.side} {sig.quantity} @ {sig.price}")
                    print(f"            {sig.reason}")
                return True
            else:
                print()
    
    print("\n✗ NO ENTRY AFTER 30 BARS!")
    return False


if __name__ == "__main__":
    result = test_after_fix()
    
    print("\n" + "=" * 80)
    if result:
        print("✅ SUCCESS: RSI >= 70 에서 매수 신호 발생!")
    else:
        print("⚠️  STILL FAILING: 다른 원인이 있을 수 있음")
