#!/usr/bin/env python
"""RSI >= 70일 때 매수가 작동하지 않는 문제를 진단하는 스크립트."""

import sys
import datetime
from typing import Optional

# Add src to path
sys.path.insert(0, 'src')

from domain.entities import TradeSignal
from use_cases.strategy import RsiStrategy
from use_cases.order_sizer import OrderSizer
from use_cases.cooldown import CooldownTracker
from use_cases.market_hours import MarketHours


class FixedClock:
    """고정 시간을 제공하는 테스트용 시계."""

    def __init__(self, now: datetime.datetime):
        self._now = now

    def now(self) -> datetime.datetime:
        return self._now

    def advance(self, seconds: int) -> None:
        self._now = self._now + datetime.timedelta(seconds=seconds)


def _seoul_time(hour: int, minute: int, second: int = 0) -> datetime.datetime:
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Asia/Seoul")
    except Exception:
        import pytz
        tz = pytz.timezone("Asia/Seoul")
    return datetime.datetime(2026, 2, 9, hour, minute, second, tzinfo=tz)


def test_rsi_entry_with_atr_and_adx():
    """RSI >= 70, ADX >= 23, ATR 필터를 만족할 때 매수가 발생하는지 테스트."""
    print("=" * 80)
    print("TEST: RSI Entry with ATR and ADX Filters")
    print("=" * 80)
    
    clock = FixedClock(_seoul_time(10, 0, 0))
    market_hours = MarketHours(start="09:00", end="15:30", timezone="Asia/Seoul")
    cooldown = CooldownTracker(seconds=10, clock=clock)
    sizer = OrderSizer()
    
    # settings.json과 동일한 설정
    strategy = RsiStrategy(
        overbought=70.0,
        sell_half=29.0,
        sell_all=19.0,
        buy_cash=1_000_000,
        cooldown=cooldown,
        order_sizer=sizer,
        market_hours=market_hours,
        grid_step_percent=1.3,
        pyramiding_enabled=False,
        entry_atr_mult=0.5,  # ATR 필터 활성
        add_atr_mult=1.0,
        atr_trailing_mult=2.7,
        atr_buffer_mult=0.7,
        atr_period=14,
        profit_protect_atr_mult=1.0,
        use_adx_filter=True,  # ADX 필터 활성
        adx_period=14,
        adx_threshold=23.0,  # 설정에서는 23.0
        use_cci_filter=False,
        cci_period=20,
        cci_entry_threshold=0.0,
        cci_add_threshold=100.0,
    )
    
    print("\nStrategy Configuration:")
    print(f"  - overbought: {strategy.overbought}")
    print(f"  - entry_atr_mult: {strategy.entry_atr_mult}")
    print(f"  - use_adx_filter: {strategy.use_adx_filter}")
    print(f"  - adx_threshold: {strategy.adx_threshold}")
    print(f"  - cooldown_seconds: {cooldown._seconds}")
    
    # Step 1: 초기 상태에서 RSI 50으로 시작
    print("\n--- Step 1: Baseline (RSI 50) ---")
    signals = strategy.on_rsi_update(
        code="TEST001",
        rsi=50.0,
        price=10000,
        position_qty=0,
        high=10050,
        low=9950,
    )
    print(f"RSI=50.0, Price=10000, High=10050, Low=9950")
    print(f"Signals: {signals}")
    
    # Step 2: RSI < 70 상태에서 여러 바 진행
    print("\n--- Step 2: Build momentum (RSI 60-65) ---")
    for i in range(5):
        rsi = 50 + i * 2
        price = 10000 + i * 50
        high = price + 100
        low = price - 100
        signals = strategy.on_rsi_update(
            code="TEST001",
            rsi=float(rsi),
            price=price,
            position_qty=0,
            high=high,
            low=low,
        )
        print(f"  Bar {i+1}: RSI={rsi}, Price={price}, High={high}, Low={low}")
        if signals:
            print(f"    -> Signals: {[(s.side, s.reason) for s in signals]}")
    
    # Step 3: RSI >= 70이 되는 순간
    print("\n--- Step 3: RSI >= 70 Entry Attempt ---")
    print("Before entry_atr_mult check: prev_price should exist from previous updates")
    
    rsi_value = 71.0
    price = 10300
    high = 10400
    low = 10200
    
    signals = strategy.on_rsi_update(
        code="TEST001",
        rsi=rsi_value,
        price=price,
        position_qty=0,
        high=high,
        low=low,
    )
    
    print(f"RSI={rsi_value}, Price={price}, High={high}, Low={low}")
    print(f"Signals generated: {len(signals)}")
    for sig in signals:
        print(f"  - {sig.side} {sig.quantity} @ {sig.price}: {sig.reason}")
    
    if len(signals) == 0:
        print("\n⚠️  NO SIGNALS GENERATED!")
        print("\nDiagnosis:")
        print("  Checking conditions in on_rsi_update:")
        print("  1. Is RSI >= overbought?", rsi_value >= strategy.overbought)
        print("  2. Is cooldown allowing?", True, "(we just called it, should be allowed if entry happens)")
        print("\n  Potential issues:")
        print("  - entry_atr_mult=0.5 requires: price >= prev_price + (atr * 0.5)")
        print("    -> If ATR is 0 or very small, this might fail")
        print("  - ADX >= 23.0 required (adx_ok condition)")
        print("    -> If ADX filter prevents entry")
        return False
    else:
        print("\n✓ ENTRY SIGNAL GENERATED!")
        return True


def test_rsi_entry_without_filters():
    """필터를 제거했을 때 RSI >= 70에서 매수가 발생하는지 테스트."""
    print("\n" + "=" * 80)
    print("TEST: RSI Entry WITHOUT Filters (for comparison)")
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
        entry_atr_mult=0.0,  # No ATR filter
        use_adx_filter=False,  # No ADX filter
    )
    
    print("\nStrategy Configuration:")
    print(f"  - entry_atr_mult: 0.0 (NO ATR FILTER)")
    print(f"  - use_adx_filter: False (NO ADX FILTER)")
    
    # Simple test
    signals = strategy.on_rsi_update(
        code="TEST002",
        rsi=71.0,
        price=10000,
        position_qty=0,
        high=10100,
        low=9900,
    )
    
    print(f"\nDirect entry with RSI=71.0:")
    print(f"Signals: {len(signals)} signal(s)")
    for sig in signals:
        print(f"  - {sig.side} {sig.quantity} @ {sig.price}: {sig.reason}")
    
    return len(signals) > 0


def analyze_entry_conditions():
    """매수 조건을 상세히 분석."""
    print("\n" + "=" * 80)
    print("ANALYSIS: Entry Conditions for RSI Strategy")
    print("=" * 80)
    
    print("""
From strategy.py on_rsi_update():

Entry conditions that must ALL be True:
1. rsi >= self.overbought (70.0)
2. not entered (hasn't entered in this overbought phase)
3. adx_ok: 
   - (not self.use_adx_filter) OR (adx is not None and adx >= adx_threshold)
   - In our case: adx_ok = (adx is not None and adx >= 23.0)
4. cci_ok:
   - (not self.use_cci_filter) OR (cci is not None and cci >= cci_entry_threshold)
   - In our case: cci_ok = True (no CCI filter)
5. entry_atr_ok:
   - if entry_atr_mult == 0: entry_atr_ok = True
   - if entry_atr_mult > 0: 
     - prev_price is not None AND
     - atr is not None AND atr > 0 AND
     - price >= (prev_price + atr * entry_atr_mult)
6. self.cooldown.allow(code)

PROBLEMS:
- If high/low not passed: atr = None -> entry_atr_ok fails if entry_atr_mult > 0
- If ADX not initialized yet: adx = None -> adx_ok fails
- If cooldown not ready: entry fails

KEY ISSUE: The code requires high/low parameters to calculate ATR!
If high/low are not being passed, ATR = None and entry will fail.
    """)


if __name__ == "__main__":
    try:
        # Test 1: With filters (current settings)
        result1 = test_rsi_entry_with_atr_and_adx()
        
        # Test 2: Without filters
        result2 = test_rsi_entry_without_filters()
        
        # Analysis
        analyze_entry_conditions()
        
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"Entry with filters: {'✓ PASS' if result1 else '✗ FAIL'}")
        print(f"Entry without filters: {'✓ PASS' if result2 else '✗ FAIL'}")
        
        if result1 and not result2:
            print("\n>>> LIKELY ISSUE: Filters (ATR or ADX) are blocking entry!")
        elif not result1 and result2:
            print("\n>>> CONFIRMED ISSUE: Filters are blocking entry!")
        elif not result1 and not result2:
            print("\n>>> CRITICAL ISSUE: Entry fails even without filters!")
            
    except Exception as e:
        print(f"\n❌ Error running tests: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
