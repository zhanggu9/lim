from domain.indicators import RsiTracker

def test_rsi_flat_price_stays_at_50():
    """가격 변동이 없을 때 RSI가 100으로 튀지 않고 50으로 유지되는지 확인한다."""
    tracker = RsiTracker(period=14)
    # 초기 15개 데이터를 동일한 가격으로 입력
    price = 10000
    rsi = None
    for _ in range(15):
        rsi = tracker.update(price)
    
    # Wilder 초기화 후 RSI가 계산되었을 때 50이어야 함 (avg_gain=0, avg_loss=0)
    assert rsi == 50.0

def test_rsi_flat_price_after_movement():
    """가격 변동 후 정체되었을 때 RSI가 서서히 50으로 수렴하는지 확인한다."""
    tracker = RsiTracker(period=14)
    
    # 상승 후 정체
    prices = [100, 110, 120, 130, 140, 150, 160, 170, 180, 190, 200, 210, 220, 230, 240]
    rsi = None
    for p in prices:
        rsi = tracker.update(p)
    
    initial_rsi = rsi
    assert initial_rsi > 90.0 # 강한 상승 상태
    
    # 이후 100번 동일 가격 입력
    for _ in range(100):
        rsi = tracker.update(240)
    
    # 평균 이득/손실이 점차 줄어들며 50으로 수렴해야 함
    assert 49.0 <= rsi <= 51.0
