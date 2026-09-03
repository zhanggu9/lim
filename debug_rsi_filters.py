#!/usr/bin/env python
"""ATR/ADX 필터의 상세 진단."""

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


def detailed_filter_analysis():
    """각 필터가 정확히 어디서 막는지 분석."""
    print("=" * 80)
    print("DETAILED FILTER ANALYSIS")
    print("=" * 80)
    
    clock = FixedClock(_seoul_time(10, 0, 0))
    market_hours = MarketHours(start="09:00", end="15:30", timezone="Asia/Seoul")
    cooldown = CooldownTracker(seconds=0, clock=clock)
    sizer = OrderSizer()
    
    # 현재 설정
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
        entry_atr_mult=0.5,
        add_atr_mult=1.0,
        atr_trailing_mult=2.7,
        atr_buffer_mult=0.7,
        atr_period=14,
        profit_protect_atr_mult=1.0,
        use_adx_filter=True,
        adx_period=14,
        adx_threshold=23.0,
        use_cci_filter=False,
    )
    
    print("\n[SCENARIO 1] Only ATR filter enabled, No ADX")
    strategy1 = RsiStrategy(
        overbought=70.0, sell_half=29.0, sell_all=19.0, buy_cash=1_000_000,
        cooldown=CooldownTracker(seconds=0, clock=FixedClock(_seoul_time(10, 0, 0))),
        order_sizer=sizer, market_hours=market_hours,
        entry_atr_mult=0.5, use_adx_filter=False,
    )
    
    # Build enough history for ATR
    print("\nBuilding history (6 bars)...")
    for i in range(6):
        price = 10000 + i * 100
        high = price + 100
        low = price - 100
        signals = strategy1.on_rsi_update(
            code="TEST",
            rsi=float(50 + i * 2),
            price=price,
            position_qty=0,
            high=high,
            low=low,
        )
    
    # Now try entry
    print("\nAttempting entry with RSI=71 after history is built...")
    signals = strategy1.on_rsi_update(
        code="TEST",
        rsi=71.0,
        price=10600,
        position_qty=0,
        high=10700,
        low=10500,
    )
    print(f"Signals: {len(signals)}")
    if signals:
        print(f"  SUCCESS: {signals[0].reason}")
    else:
        print("  FAIL: No signal")
        print("\nChecking internal state:")
        print(f"  - entry_atr_mult: {strategy1.entry_atr_mult}")
        print(f"  - _last_price.get('TEST'): {strategy1._last_price.get('TEST')}")
        atr_tracker = strategy1._atr_trackers.get('TEST')
        if atr_tracker:
            print(f"  - ATR tracker exists: True")
            print(f"  - ATR value: {atr_tracker._atr}")
    
    print("\n" + "-" * 80)
    print("[SCENARIO 2] Only ADX filter enabled, No ATR")
    strategy2 = RsiStrategy(
        overbought=70.0, sell_half=29.0, sell_all=19.0, buy_cash=1_000_000,
        cooldown=CooldownTracker(seconds=0, clock=FixedClock(_seoul_time(10, 0, 0))),
        order_sizer=sizer, market_hours=market_hours,
        entry_atr_mult=0.0, use_adx_filter=True, adx_threshold=23.0,
    )
    
    # Build enough history for ADX
    print("\nBuilding history (15+ bars for ADX)...")
    for i in range(20):
        price = 10000 + i * 50 + (i * i if i % 2 == 0 else -i * 50)  # Some volatility
        high = price + 200
        low = max(price - 200, 9000)
        signals = strategy2.on_rsi_update(
            code="TEST",
            rsi=float(50 + (i % 20)),
            price=price,
            position_qty=0,
            high=high,
            low=low,
        )
    
    # Now try entry
    print("\nAttempting entry with RSI=71...")
    signals = strategy2.on_rsi_update(
        code="TEST",
        rsi=71.0,
        price=10500,
        position_qty=0,
        high=10700,
        low=10300,
    )
    print(f"Signals: {len(signals)}")
    if signals:
        print(f"  SUCCESS: {signals[0].reason}")
    else:
        print("  FAIL: No signal")
        adx_tracker = strategy2._adx_trackers.get('TEST')
        if adx_tracker:
            print(f"\nChecking ADX state:")
            print(f"  - ADX tracker exists: True")
            print(f"  - ADX value: {adx_tracker._adx}")
            print(f"  - ADX threshold: {strategy2.adx_threshold}")
            if adx_tracker._adx is not None:
                print(f"  - ADX >= threshold? {adx_tracker._adx >= strategy2.adx_threshold}")
            else:
                print(f"  - ADX is None (not yet initialized)")
        else:
            print(f"  - ADX tracker: None (not created)")
    
    print("\n" + "-" * 80)
    print("[SCENARIO 3] Both ATR and ADX filters")
    strategy3 = RsiStrategy(
        overbought=70.0, sell_half=29.0, sell_all=19.0, buy_cash=1_000_000,
        cooldown=CooldownTracker(seconds=0, clock=FixedClock(_seoul_time(10, 0, 0))),
        order_sizer=sizer, market_hours=market_hours,
        entry_atr_mult=0.5, use_adx_filter=True, adx_threshold=23.0,
    )
    
    print("\nBuilding history (20 bars)...")
    for i in range(20):
        price = 10000 + i * 100
        high = price + 150
        low = max(price - 150, 9000)
        signals = strategy3.on_rsi_update(
            code="TEST",
            rsi=float(50 + (i % 20)),
            price=price,
            position_qty=0,
            high=high,
            low=low,
        )
    
    print("\nAttempting entry with RSI=71...")
    signals = strategy3.on_rsi_update(
        code="TEST",
        rsi=71.0,
        price=10500,
        position_qty=0,
        high=10700,
        low=10300,
    )
    print(f"Signals: {len(signals)}")
    if signals:
        print(f"  SUCCESS: {signals[0].reason}")
    else:
        print("  FAIL: No signal from both filters")


def test_real_world_scenario():
    """실제 거래 상황처럼 시뮬레이션."""
    print("\n\n" + "=" * 80)
    print("REAL-WORLD SCENARIO: Simulating actual market ticks")
    print("=" * 80)
    
    clock = FixedClock(_seoul_time(10, 0, 0))
    market_hours = MarketHours(start="09:00", end="15:30", timezone="Asia/Seoul")
    cooldown = CooldownTracker(seconds=10, clock=clock)
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
    
    # Simulate 30 completed candles (mimicking tick aggregation with 30 ticks per candle)
    prices = []
    rsi_values = []
    
    print("\n[Building 30 candles of history]")
    for candle_idx in range(30):
        # Simulate uptrend with some volatility
        base_price = 10000 + candle_idx * 50
        high = base_price + 100
        low = base_price - 100
        
        # RSI gradually increases
        rsi = 40 + (candle_idx / 30) * 45  # Goes from 40 to 85
        
        if candle_idx % 5 == 0:
            print(f"  Candle {candle_idx}: Price={base_price}, RSI={rsi:.1f}, High={high}, Low={low}")
        
        signals = strategy.on_rsi_update(
            code="005930",  # Samsung
            rsi=rsi,
            price=base_price,
            position_qty=0,
            high=high,
            low=low,
        )
        
        prices.append(base_price)
        rsi_values.append(rsi)
        
        if signals:
            print(f"\n  ⚠️  ENTRY at Candle {candle_idx}!")
            for sig in signals:
                print(f"     {sig.side} {sig.quantity} @ {sig.price}: {sig.reason}")
            break
    
    if not any(strategy._entered_overbought.values()):
        print("\n  ✗ NO ENTRY SIGNALS AFTER 30 CANDLES")
        print("\n  Checking final state:")
        print(f"    - Last RSI: {rsi_values[-1]:.1f}")
        print(f"    - Cooldown ready: {cooldown.allow('005930')}")
        if '005930' in strategy._atr_trackers:
            atr = strategy._atr_trackers['005930']._atr
            print(f"    - ATR initialized: {atr is not None}, value: {atr}")
        if '005930' in strategy._adx_trackers:
            adx = strategy._adx_trackers['005930']._adx
            print(f"    - ADX initialized: {adx is not None}, value: {adx}")


if __name__ == "__main__":
    detailed_filter_analysis()
    test_real_world_scenario()
    
    print("\n\n" + "=" * 80)
    print("RECOMMENDATION")
    print("=" * 80)
    print("""
The issue is that RSI >= 70 entry requires BOTH conditions to be true:
1. ATR 필터: entry_atr_mult=0.5 이면 price >= prev_price + atr*0.5 필요
2. ADX 필터: adx >= 23.0 필요

Problems identified:
- ATR 초기화에 충분한 바가 필요 (period=14)
- ADX 초기화에도 충분한 바가 필요 (period=14)
- 이 바들이 완성되지 않으면 필터가 막힘

솔루션:
1. entry_atr_mult을 0으로 설정 (ATR 필터 비활성)
2. use_adx_filter를 false로 설정 (ADX 필터 비활성)
3. 둘 다 필요하면, 초기화되지 않은 상태에서는 조건을 느슨하게 함
    """)
