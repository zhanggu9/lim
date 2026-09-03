from infrastructure.ui.tk_status import StatusWindow


def test_refresh_holdings_calls_callback():
    called = {"count": 0}
    window = StatusWindow.__new__(StatusWindow)
    window._on_refresh_holdings = lambda: called.update({"count": called["count"] + 1})

    window._refresh_holdings()

    assert called["count"] == 1


def test_refresh_holdings_without_callback_is_noop():
    window = StatusWindow.__new__(StatusWindow)
    window._on_refresh_holdings = None

    window._refresh_holdings()
