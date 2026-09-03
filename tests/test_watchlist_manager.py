from use_cases.watchlist_manager import WatchlistManager


def test_watchlist_respects_max_with_holdings():
    """보유 종목을 포함한 총 제한 수를 유지한다."""
    manager = WatchlistManager(max_total=3)
    manager.update_holdings({"A"})
    manager.apply_condition_snapshot({"B", "C", "D"})

    tracked = manager.get_tracked_codes()
    assert "A" in tracked
    assert "B" in tracked
    assert "C" in tracked
    assert "D" not in tracked
    assert len(tracked) == 3


def test_watchlist_removes_on_exit_if_not_holding():
    """조건식 이탈(D)이고 보유가 아니면 리스트에서 제거한다."""
    manager = WatchlistManager(max_total=3)
    manager.update_holdings(set())
    manager.apply_condition_snapshot({"B"})
    assert "B" in manager.get_tracked_codes()

    manager.apply_condition_event(code="B", event_type="D")
    assert "B" not in manager.get_tracked_codes()


def test_watchlist_keeps_holding_on_exit():
    """조건식 이탈(D)이어도 보유 종목은 유지한다."""
    manager = WatchlistManager(max_total=3)
    manager.update_holdings({"A"})
    manager.apply_condition_snapshot({"A"})

    manager.apply_condition_event(code="A", event_type="D")
    assert "A" in manager.get_tracked_codes()


def test_watchlist_removes_when_holding_sold_and_not_in_condition():
    """보유 종목이 빠지고 조건식에도 없으면 감시 리스트에서 제거한다."""
    manager = WatchlistManager(max_total=3)
    manager.update_holdings({"A"})
    assert "A" in manager.get_tracked_codes()

    manager.update_holdings(set())
    assert "A" not in manager.get_tracked_codes()


def test_watchlist_resets_condition_codes():
    """조건식을 초기화하면 보유가 아닌 종목은 제거된다."""
    manager = WatchlistManager(max_total=3)
    manager.update_holdings({"A"})
    manager.apply_condition_snapshot({"A", "B"})

    manager.reset_conditions()

    tracked = manager.get_tracked_codes()
    assert "A" in tracked
    assert "B" not in tracked


def test_watchlist_excludes_configured_codes():
    """제외 종목에 등록된 코드는 보유/조건식에서 모두 감시 제외된다."""
    manager = WatchlistManager(max_total=5)
    manager.set_excluded_codes({"A", "C"})
    manager.update_holdings({"A", "B"})
    manager.apply_condition_snapshot({"B", "C", "D"})

    tracked = manager.get_tracked_codes()
    assert "A" not in tracked
    assert "C" not in tracked
    assert "B" in tracked
    assert "D" in tracked
