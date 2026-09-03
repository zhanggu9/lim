import datetime
from types import SimpleNamespace

from infrastructure.ui.tk_status import LOSS_COLOR, PROFIT_COLOR, StatusWindow


class FakeLabel:
    """라벨 config 호출 결과를 기록하는 스텁."""

    def __init__(self) -> None:
        self.text = "-"
        self.fg = "black"
        self.wraplength = 0

    def config(self, **kwargs) -> None:
        if "text" in kwargs:
            self.text = kwargs["text"]
        if "fg" in kwargs:
            self.fg = kwargs["fg"]
        if "wraplength" in kwargs:
            self.wraplength = kwargs["wraplength"]

    configure = config


class FakeTree:
    """Treeview 호출 결과를 기록하는 테스트 더블."""

    def __init__(self) -> None:
        self.children = []
        self.rows = []
        self.tag_options = {}

    def tag_configure(self, tag, **kwargs) -> None:
        self.tag_options[tag] = kwargs

    def get_children(self):
        return list(self.children)

    def delete(self, *items) -> None:
        self.children = []
        self.rows = []

    def insert(self, parent, index, values=(), tags=()):
        row_id = f"row-{len(self.rows)}"
        self.children.append(row_id)
        self.rows.append({"values": values, "tags": tuple(tags)})
        return row_id


def _make_snapshot(level: str):
    return SimpleNamespace(
        server_mode="모의",
        account_no="1111111111",
        condition_index=0,
        condition_name="A",
        strategy_name="rsi_grid",
        candle_source="tick",
        ticks_per_candle=60,
        minutes_per_candle=1,
        rsi_period=14,
        condition_version=0,
        strategy_version=0,
        candle_version=0,
        rsi_period_version=0,
        buy_order_version=0,
        buy_size_mode="cash",
        buy_size_value=1_000_000,
        excluded_items=[],
        watchlist_count=0,
        holding_count=0,
        last_signal="-",
        last_rsi="-",
        last_update=datetime.datetime(2026, 2, 24, 10, 0, 0),
        watchlist_names="-",
        holdings_summary="-",
        rsi_summary="-",
        rsi_items=[],
        account_summary="-",
        daily_trade_details="-",
        daily_trade_items=[],
        exclude_version=0,
        excluded_codes_text="",
        condition_items=[],
        strategy_items=[],
        holdings_items=[],
        realtime_status="수신Q 0 | 연산Q 0/10000(0%) | 드롭 0 | TR대기 0ms | 주문대기 0ms",
        realtime_status_level=level,
        real_ingress_queue_size=0,
        tick_compute_queue_size=0,
        tick_compute_queue_capacity=10000,
        tick_drop_count=0,
        tr_limit_wait_ms_1s=0.0,
        order_limit_wait_ms_1s=0.0,
    )


def _make_window_for_update() -> StatusWindow:
    window = StatusWindow.__new__(StatusWindow)
    keys = [
        "server_mode",
        "account_no",
        "watchlist_count",
        "watchlist_names",
        "holding_count",
        "realtime_status",
        "account_summary",
        "last_signal",
        "last_update",
    ]
    window._labels = {key: FakeLabel() for key in keys}
    window._condition_combo = None
    window._strategy_combo = None
    window._candle_combo = None
    window._rsi_period_entry = None
    window._buy_mode_combo = None
    window._buy_value_entry = None
    window._trade_text = None
    window._trade_tree = None
    window._render_rsi = lambda items: None
    window._render_holdings = lambda items: None
    window._resize_window_to_content = lambda: None
    return window


def test_update_sets_warn_color_for_realtime_status():
    window = _make_window_for_update()
    snapshot = _make_snapshot("warn")

    window.update(snapshot)

    assert window._labels["realtime_status"].fg == "#B22222"


def test_update_sets_ok_color_for_realtime_status():
    window = _make_window_for_update()
    snapshot = _make_snapshot("ok")

    window.update(snapshot)

    assert window._labels["realtime_status"].fg == "black"


def test_trade_tree_applies_profit_loss_tags_and_colors():
    window = StatusWindow.__new__(StatusWindow)
    tree = FakeTree()
    window._trade_tree = tree
    window._trade_sort_column = "first_buy"
    window._trade_sort_descending = False
    window._trade_items = [
        {
            "type": "trade_group",
            "first_buy": "09:01",
            "name": "이익종목",
            "avg_price": 1000,
            "buy_amount": 100000,
            "sell_amount": 102000,
            "net_pnl": 2000,
            "profit_rate": 2.0,
        },
        {
            "type": "trade_group",
            "first_buy": "09:02",
            "name": "손실종목",
            "avg_price": 1000,
            "buy_amount": 100000,
            "sell_amount": 99000,
            "net_pnl": -1000,
            "profit_rate": -1.0,
        },
    ]

    window._populate_trade_tree()

    assert tree.tag_options["profit"]["foreground"] == PROFIT_COLOR
    assert tree.tag_options["loss"]["foreground"] == LOSS_COLOR
    assert tree.rows[0]["tags"] == ("profit",)
    assert tree.rows[1]["tags"] == ("loss",)


def test_holdings_tree_applies_profit_loss_tags_and_colors():
    window = StatusWindow.__new__(StatusWindow)
    tree = FakeTree()
    window._holdings_tree = tree
    window._holdings_row_codes = {}
    window._on_sell_all = None

    window._render_holdings(
        [
            {
                "code": "000001",
                "name": "이익보유",
                "qty": 1,
                "avg_price": 1000,
                "last_price": 1100,
                "value": 1100,
                "pnl_amount": 100,
                "pnl_rate": 10.0,
            },
            {
                "code": "000002",
                "name": "손실보유",
                "qty": 1,
                "avg_price": 1000,
                "last_price": 900,
                "value": 900,
                "pnl_amount": -100,
                "pnl_rate": -10.0,
            },
        ]
    )

    assert tree.tag_options["profit"]["foreground"] == PROFIT_COLOR
    assert tree.tag_options["loss"]["foreground"] == LOSS_COLOR
    assert tree.rows[0]["tags"] == ("profit",)
    assert tree.rows[1]["tags"] == ("loss",)
