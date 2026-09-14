from datetime import datetime, timezone

from use_cases.order_intent_guard import OrderIntentGuard


def test_same_code_and_side_can_only_be_claimed_once():
    guard = OrderIntentGuard()
    now = datetime.now(timezone.utc)

    assert guard.claim("005930", "BUY", now)
    assert not guard.claim("005930", "BUY", now)
    assert guard.is_pending("005930", "BUY")


def test_sell_is_independent_from_buy_and_release_allows_reclaim():
    guard = OrderIntentGuard()
    now = datetime.now(timezone.utc)

    assert guard.claim("005930", "BUY", now)
    assert guard.claim("005930", "SELL", now)

    guard.release("005930", "BUY")
    assert guard.claim("005930", "BUY", now)
    assert guard.is_pending("005930", "SELL")


def test_clear_code_removes_both_sides():
    guard = OrderIntentGuard()
    now = datetime.now(timezone.utc)
    guard.claim("005930", "BUY", now)
    guard.claim("005930", "SELL", now)

    guard.clear_code("005930")

    assert not guard.is_pending("005930", "BUY")
    assert not guard.is_pending("005930", "SELL")
