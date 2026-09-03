import datetime

from infrastructure.ui.tk_status import StatusWindow


class DummyClock:
    """테스트용 시간 공급자."""

    def __init__(self) -> None:
        self.now_value = datetime.datetime(2026, 2, 23, 10, 0, 0)

    def now(self) -> datetime.datetime:
        return self.now_value


def _create_window_for_sync_tests(clock: DummyClock) -> StatusWindow:
    window = StatusWindow.__new__(StatusWindow)
    window._sync_timeout_sec = 3.0
    window._sync_state = {}
    window._now = clock.now
    return window


def test_should_sync_blocks_stale_snapshot_while_pending():
    clock = DummyClock()
    window = _create_window_for_sync_tests(clock)

    window._mark_pending("candle")

    assert window._should_sync("candle", 0) is False


def test_should_sync_accepts_when_expected_version_arrives():
    clock = DummyClock()
    window = _create_window_for_sync_tests(clock)

    window._mark_pending("candle")

    assert window._should_sync("candle", 1) is True


def test_should_sync_releases_pending_after_timeout():
    clock = DummyClock()
    window = _create_window_for_sync_tests(clock)

    window._mark_pending("candle")
    clock.now_value = clock.now_value + datetime.timedelta(seconds=4)

    assert window._should_sync("candle", 0) is True


def test_should_sync_blocks_while_editing():
    clock = DummyClock()
    window = _create_window_for_sync_tests(clock)

    window._set_editing("candle", True)

    assert window._should_sync("candle", 1) is False


def test_should_sync_allows_after_editing_is_cleared():
    clock = DummyClock()
    window = _create_window_for_sync_tests(clock)

    window._set_editing("candle", True)
    assert window._should_sync("candle", 1) is False

    window._set_editing("candle", False)
    assert window._should_sync("candle", 1) is True


def test_should_sync_keeps_blocked_if_timeout_passed_but_editing():
    clock = DummyClock()
    window = _create_window_for_sync_tests(clock)

    window._mark_pending("candle")
    window._set_editing("candle", True)
    clock.now_value = clock.now_value + datetime.timedelta(seconds=4)
    assert window._should_sync("candle", 0) is False

    window._set_editing("candle", False)
    assert window._should_sync("candle", 0) is True
