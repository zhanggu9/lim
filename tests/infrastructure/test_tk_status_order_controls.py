from infrastructure.ui.tk_status import StatusWindow


class DummyInput:
    """UI 입력 위젯 대체 객체."""

    def __init__(self, text: str) -> None:
        self._text = text

    def get(self) -> str:
        return self._text

    def delete(self, *_args) -> None:
        self._text = ""

    def insert(self, _index, value: str) -> None:
        self._text = str(value)


class DummyListbox:
    """트리뷰 대체 객체."""

    def __init__(self, items) -> None:
        self._rows = [tuple(item) for item in items]

    def get_children(self):
        return list(range(len(self._rows)))

    def item(self, item_id, option=None):
        values = self._rows[int(item_id)]
        if option == "values":
            return values
        return {"values": values}


class DummyBoolVar:
    def __init__(self, value: bool) -> None:
        self._value = bool(value)

    def get(self) -> bool:
        return self._value


def test_apply_order_config_calls_callback():
    called = {}
    window = StatusWindow.__new__(StatusWindow)
    window._sync_timeout_sec = 3.0
    window._sync_state = {
        "buy_order": {
            "seen_version": 0,
            "pending_expected_version": 0,
            "pending_deadline": None,
            "editing": False,
        }
    }
    window._now = lambda: __import__("datetime").datetime(2026, 2, 23, 10, 0, 0)
    window._buy_mode_combo = DummyInput("금액")
    window._buy_value_entry = DummyInput("1000000")
    window._on_change_order_config = lambda buy_mode, buy_value: called.update(
        {
            "buy_mode": buy_mode,
            "buy_value": buy_value,
        }
    )

    window._apply_order_config()

    assert called == {
        "buy_mode": "cash",
        "buy_value": 1_000_000,
    }
    assert window._sync_state["buy_order"]["pending_expected_version"] == 1


def test_apply_order_config_skips_invalid_number():
    called = {"count": 0}
    window = StatusWindow.__new__(StatusWindow)
    window._buy_mode_combo = DummyInput("금액")
    window._buy_value_entry = DummyInput("abc")
    window._on_change_order_config = lambda *args: called.update({"count": called["count"] + 1})

    window._apply_order_config()

    assert called["count"] == 0


def test_apply_excluded_codes_calls_callback_and_marks_pending():
    called = {}
    window = StatusWindow.__new__(StatusWindow)
    window._sync_timeout_sec = 3.0
    window._sync_state = {
        "exclude": {
            "seen_version": 0,
            "pending_expected_version": 0,
            "pending_deadline": None,
            "editing": False,
        }
    }
    window._now = lambda: __import__("datetime").datetime(2026, 2, 24, 10, 0, 0)
    window._exclude_tree = DummyListbox([("005930", "삼성전자"), ("000660", "SK하이닉스")])
    window._on_change_excluded_codes = lambda value: called.update({"value": value})

    window._apply_excluded_codes()

    assert called == {"value": "005930, 000660"}
    assert window._sync_state["exclude"]["pending_expected_version"] == 1


def test_apply_rsi_pyramiding_calls_callback_and_marks_pending():
    called = {}
    window = StatusWindow.__new__(StatusWindow)
    window._sync_timeout_sec = 3.0
    window._sync_state = {
        "strategy": {
            "seen_version": 0,
            "pending_expected_version": 0,
            "pending_deadline": None,
            "editing": False,
        }
    }
    window._now = lambda: __import__("datetime").datetime(2026, 2, 24, 10, 0, 0)
    window._rsi_pyramiding_var = DummyBoolVar(False)
    window._on_change_pyramiding = lambda name, enabled: called.update({"name": name, "enabled": enabled})

    window._apply_rsi_pyramiding()

    assert called == {"name": "rsi_grid", "enabled": False}
    assert window._sync_state["strategy"]["pending_expected_version"] == 1


def test_apply_rsi_cci_filter_calls_callback_and_marks_pending():
    called = {}
    window = StatusWindow.__new__(StatusWindow)
    window._sync_timeout_sec = 3.0
    window._sync_state = {
        "strategy": {
            "seen_version": 0,
            "pending_expected_version": 0,
            "pending_deadline": None,
            "editing": False,
        }
    }
    window._now = lambda: __import__("datetime").datetime(2026, 2, 24, 10, 0, 0)
    window._rsi_cci_var = DummyBoolVar(True)
    window._on_change_cci_filter = lambda name, enabled: called.update({"name": name, "enabled": enabled})

    window._apply_rsi_cci_filter()

    assert called == {"name": "rsi_grid", "enabled": True}
    assert window._sync_state["strategy"]["pending_expected_version"] == 1


def test_apply_rsi_cci_thresholds_calls_callback_and_marks_pending():
    called = {}
    window = StatusWindow.__new__(StatusWindow)
    window._sync_timeout_sec = 3.0
    window._sync_state = {
        "cci_threshold": {
            "seen_version": 0,
            "pending_expected_version": 0,
            "pending_deadline": None,
            "editing": False,
        }
    }
    window._now = lambda: __import__("datetime").datetime(2026, 2, 24, 10, 0, 0)
    window._rsi_cci_entry_entry = DummyInput("15")
    window._rsi_cci_add_entry = DummyInput("110")
    window._on_change_cci_threshold = lambda name, entry, add: called.update(
        {"name": name, "entry": entry, "add": add}
    )

    window._apply_rsi_cci_thresholds()

    assert called == {"name": "rsi_grid", "entry": 15.0, "add": 110.0}
    assert window._sync_state["cci_threshold"]["pending_expected_version"] == 1
