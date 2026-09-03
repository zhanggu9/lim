from __future__ import annotations

import datetime
import logging
import threading
import tkinter as tk
import tkinter.font as tkfont
import tkinter.ttk as ttk
from tkinter import simpledialog
from typing import Dict, Optional

from app.status_bus import StatusBus, StatusSnapshot

LOGGER = logging.getLogger("kw-bot")
PROFIT_COLOR = "#B22222"
LOSS_COLOR = "#1F5AA6"
TREEVIEW_TEXT_COLOR = "black"
TREEVIEW_SELECTED_TEXT_COLOR = "white"


class ScrollableFrame(tk.Frame):
    """세로 스크롤이 가능한 프레임."""

    def __init__(self, parent, width: int = 560, height: int = 160, horizontal: bool = False) -> None:
        super().__init__(parent)
        self._canvas = tk.Canvas(self, width=width, height=height, highlightthickness=0)
        self._scrollbar = tk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._x_scrollbar = tk.Scrollbar(self, orient="horizontal", command=self._canvas.xview) if horizontal else None
        self._content = tk.Frame(self._canvas)
        self._content.bind("<Configure>", self._on_configure)
        self._canvas.create_window((0, 0), window=self._content, anchor="nw")
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        if self._x_scrollbar is not None:
            self._canvas.configure(xscrollcommand=self._x_scrollbar.set)

        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._scrollbar.grid(row=0, column=1, sticky="ns")
        if self._x_scrollbar is not None:
            self._x_scrollbar.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

    @property
    def content(self) -> tk.Frame:
        """스크롤 영역의 내부 프레임을 반환한다."""
        return self._content

    def clear(self) -> None:
        """내부 위젯을 모두 제거한다."""
        for child in self._content.winfo_children():
            child.destroy()

    def _on_configure(self, event=None) -> None:
        """스크롤 영역 크기를 갱신한다."""
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))


class StatusWindow:
    """간단한 상태 UI를 출력한다."""

    def __init__(
        self,
        title: str = "Kiwoom Auto Trader",
        on_sell_all=None,
        on_refresh_holdings=None,
        on_change_condition=None,
        on_refresh_conditions=None,
        on_change_strategy=None,
        on_change_candle=None,
        on_change_rsi_period=None,
        on_change_rsi_thresholds=None,
        on_change_order_config=None,
        on_change_excluded_codes=None,
        on_change_pyramiding=None,
        on_change_cci_filter=None,
        on_change_cci_threshold=None,
    ) -> None:
        """상태 UI 창을 초기화한다."""
        self._root = tk.Tk()
        self._root.report_callback_exception = self._handle_tk_exception
        self._root.title(title)
        self._root.geometry("900x660")
        self._root.minsize(840, 620)
        self._root.rowconfigure(0, weight=1)
        self._root.columnconfigure(0, weight=1)
        self._style = ttk.Style(self._root)
        self._configure_treeview_style()
        self._base_font = tkfont.Font(family="맑은 고딕", size=10)
        self._header_font = tkfont.Font(family="맑은 고딕", size=10, weight="bold")
        self._root.option_add("*Font", self._base_font)
        self._labels = {}
        self._holdings_frame = None
        self._holdings_header = None
        self._holdings_body = None
        self._holdings_tree = None
        self._rsi_body = None
        self._container = None
        self._on_sell_all = on_sell_all
        self._on_refresh_holdings = on_refresh_holdings
        self._on_change_condition = on_change_condition
        self._on_refresh_conditions = on_refresh_conditions
        self._on_change_strategy = on_change_strategy
        self._on_change_candle = on_change_candle
        self._on_change_rsi_period = on_change_rsi_period
        self._on_change_rsi_thresholds = on_change_rsi_thresholds
        self._on_change_order_config = on_change_order_config
        self._on_change_excluded_codes = on_change_excluded_codes
        self._on_change_pyramiding = on_change_pyramiding
        self._on_change_cci_filter = on_change_cci_filter
        self._on_change_cci_threshold = on_change_cci_threshold
        self._condition_combo = None
        self._condition_values = []
        self._strategy_combo = None
        self._strategy_values = []
        self._candle_combo = None
        self._rsi_period_entry = None
        self._rsi_overbought_entry = None
        self._rsi_sell_half_entry = None
        self._rsi_sell_all_entry = None
        self._buy_mode_combo = None
        self._buy_value_entry = None
        self._rsi_pyramiding_var = None
        self._livermore_pyramiding_var = None
        self._rsi_cci_var = None
        self._livermore_cci_var = None
        self._rsi_cci_entry_entry = None
        self._rsi_cci_add_entry = None
        self._livermore_cci_entry_entry = None
        self._livermore_cci_add_entry = None
        self._exclude_codes_entry = None
        self._exclude_codes_listbox = None
        self._exclude_tree = None
        self._candle_values = [
            "20틱",
            "30틱",
            "60틱",
            "100틱",
            "200틱",
            "1분",
            "3분",
            "15분",
            "30분",
        ]
        self._trade_text = None
        self._trade_tree = None
        self._trade_items = []
        self._trade_sort_column = "first_buy"
        self._trade_sort_descending = True
        self._holdings_row_codes = {}
        self._sync_timeout_sec = 3.0
        self._sync_state: Dict[str, dict] = {
            "condition": self._new_sync_entry(),
            "strategy": self._new_sync_entry(),
            "candle": self._new_sync_entry(),
            "rsi_period": self._new_sync_entry(),
            "buy_order": self._new_sync_entry(),
            "exclude": self._new_sync_entry(),
            "cci_threshold": self._new_sync_entry(),
        }
        self._build_ui()

    def _handle_tk_exception(self, exc_type, exc_value, exc_traceback) -> None:
        """Tk 콜백 예외를 로그에 남기고 UI 루프가 계속 돌 수 있게 한다."""
        LOGGER.error("UI 콜백 오류", exc_info=(exc_type, exc_value, exc_traceback))

    def _configure_treeview_style(self) -> None:
        """Treeview 태그 전경색이 Windows 테마에 묻히지 않도록 기본 스타일을 고정한다."""
        try:
            if "clam" in self._style.theme_names():
                self._style.theme_use("clam")
            self._style.configure("Treeview", foreground=TREEVIEW_TEXT_COLOR)
            self._style.map("Treeview", foreground=[("selected", TREEVIEW_SELECTED_TEXT_COLOR)])
        except tk.TclError:
            LOGGER.exception("Treeview 스타일 설정 실패")

    @staticmethod
    def _configure_profit_loss_tags(tree) -> None:
        """수익/손실 행 색상 태그를 적용한다."""
        if tree is None:
            return
        tree.tag_configure("profit", foreground=PROFIT_COLOR)
        tree.tag_configure("loss", foreground=LOSS_COLOR)

    def _run_background(self, name: str, callback, *args) -> None:
        """UI를 막을 수 있는 작업을 백그라운드 스레드에서 실행한다."""
        if callback is None:
            return

        def worker() -> None:
            try:
                callback(*args)
            except Exception:
                LOGGER.exception("UI 명령 처리 실패: %s", name)

        thread = threading.Thread(target=worker, name=f"ui-command-{name}", daemon=True)
        thread.start()

    def _build_ui(self) -> None:
        """기본 UI 레이아웃을 구성한다."""
        container = tk.Frame(self._root, padx=10, pady=10)
        container.grid(row=0, column=0, sticky="nsew")
        container.bind("<Configure>", self._on_container_configure)
        container.columnconfigure(1, weight=1)
        self._container = container
        fields = [
            ("server_mode", "서버"),
            ("account_no", "계좌"),
            ("watchlist_count", "감시 종목 수"),
            ("watchlist_names", "감시 종목"),
            ("holding_count", "보유 종목 수"),
            ("realtime_status", "실시간 처리 상태"),
            ("account_summary", "계좌 요약"),
            ("last_signal", "최근 신호"),
            ("last_update", "마지막 업데이트"),
        ]
        for row, (key, label) in enumerate(fields):
            tk.Label(container, text=label, width=16, anchor="w").grid(row=row, column=0, padx=3, pady=2, sticky="w")
            value_label = tk.Label(container, text="-", anchor="w", justify="left")
            value_label.grid(row=row, column=1, padx=3, pady=2, sticky="ew")
            self._labels[key] = value_label

        control_row = len(fields)
        tk.Label(container, text="조건식 선택", width=16, anchor="w").grid(
            row=control_row, column=0, padx=3, pady=2, sticky="w"
        )
        control_frame = tk.Frame(container)
        control_frame.grid(row=control_row, column=1, padx=3, pady=2, sticky="w")
        self._condition_combo = ttk.Combobox(control_frame, width=28, state="readonly")
        self._condition_combo.pack(side="left")
        self._condition_combo.bind("<<ComboboxSelected>>", self._apply_condition)
        self._bind_editing(self._condition_combo, "condition")
        tk.Button(control_frame, text="새로고침", command=self._refresh_conditions, width=8).pack(
            side="left", padx=6
        )

        strategy_row = control_row + 1
        tk.Label(container, text="전략 선택", width=16, anchor="w").grid(
            row=strategy_row, column=0, padx=3, pady=2, sticky="w"
        )
        strategy_frame = tk.Frame(container)
        strategy_frame.grid(row=strategy_row, column=1, padx=3, pady=2, sticky="w")
        self._strategy_combo = ttk.Combobox(strategy_frame, width=28, state="readonly")
        self._strategy_combo.pack(side="left")
        self._strategy_combo.bind("<<ComboboxSelected>>", self._apply_strategy)
        self._bind_editing(self._strategy_combo, "strategy")
        self._rsi_pyramiding_var = tk.BooleanVar(value=True)
        self._livermore_pyramiding_var = tk.BooleanVar(value=True)
        self._rsi_cci_var = tk.BooleanVar(value=False)
        self._livermore_cci_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            strategy_frame,
            text="RSI 피라미딩",
            variable=self._rsi_pyramiding_var,
            command=self._apply_rsi_pyramiding,
        ).pack(side="left", padx=(8, 2))
        tk.Checkbutton(
            strategy_frame,
            text="RSI CCI",
            variable=self._rsi_cci_var,
            command=self._apply_rsi_cci_filter,
        ).pack(side="left", padx=(2, 2))
        tk.Checkbutton(
            strategy_frame,
            text="Livermore 피라미딩",
            variable=self._livermore_pyramiding_var,
            command=self._apply_livermore_pyramiding,
        ).pack(side="left", padx=(2, 0))
        tk.Checkbutton(
            strategy_frame,
            text="Livermore CCI",
            variable=self._livermore_cci_var,
            command=self._apply_livermore_cci_filter,
        ).pack(side="left", padx=(2, 0))

        cci_row = strategy_row + 1
        tk.Label(container, text="CCI 기준", width=16, anchor="w").grid(
            row=cci_row, column=0, padx=3, pady=2, sticky="w"
        )
        cci_frame = tk.Frame(container)
        cci_frame.grid(row=cci_row, column=1, padx=3, pady=2, sticky="w")
        tk.Label(cci_frame, text="RSI 진입").pack(side="left")
        self._rsi_cci_entry_entry = tk.Entry(cci_frame, width=6, justify="right")
        self._rsi_cci_entry_entry.pack(side="left", padx=(4, 2))
        self._bind_editing(self._rsi_cci_entry_entry, "cci_threshold")
        tk.Label(cci_frame, text="추가").pack(side="left", padx=(4, 0))
        self._rsi_cci_add_entry = tk.Entry(cci_frame, width=6, justify="right")
        self._rsi_cci_add_entry.pack(side="left", padx=(4, 6))
        self._bind_editing(self._rsi_cci_add_entry, "cci_threshold")
        tk.Button(cci_frame, text="RSI 적용", command=self._apply_rsi_cci_thresholds, width=8).pack(side="left", padx=(0, 8))
        tk.Label(cci_frame, text="Liv 진입").pack(side="left")
        self._livermore_cci_entry_entry = tk.Entry(cci_frame, width=6, justify="right")
        self._livermore_cci_entry_entry.pack(side="left", padx=(4, 2))
        self._bind_editing(self._livermore_cci_entry_entry, "cci_threshold")
        tk.Label(cci_frame, text="추가").pack(side="left", padx=(4, 0))
        self._livermore_cci_add_entry = tk.Entry(cci_frame, width=6, justify="right")
        self._livermore_cci_add_entry.pack(side="left", padx=(4, 6))
        self._bind_editing(self._livermore_cci_add_entry, "cci_threshold")
        tk.Button(cci_frame, text="Liv 적용", command=self._apply_livermore_cci_thresholds, width=8).pack(side="left")

        candle_row = cci_row + 1
        tk.Label(container, text="캔들 기준", width=16, anchor="w").grid(
            row=candle_row, column=0, padx=3, pady=2, sticky="w"
        )
        candle_frame = tk.Frame(container)
        candle_frame.grid(row=candle_row, column=1, padx=3, pady=2, sticky="w")
        self._candle_combo = ttk.Combobox(candle_frame, width=16, state="readonly")
        self._candle_combo["values"] = self._candle_values
        self._candle_combo.pack(side="left")
        self._candle_combo.bind("<<ComboboxSelected>>", self._apply_candle)
        self._bind_editing(self._candle_combo, "candle")

        rsi_period_row = candle_row + 1
        tk.Label(container, text="기간 설정", width=16, anchor="w").grid(
            row=rsi_period_row, column=0, padx=3, pady=2, sticky="w"
        )
        rsi_period_frame = tk.Frame(container)
        rsi_period_frame.grid(row=rsi_period_row, column=1, padx=3, pady=2, sticky="w")
        self._rsi_period_entry = tk.Entry(rsi_period_frame, width=8, justify="right")
        self._rsi_period_entry.pack(side="left")
        self._rsi_period_entry.bind("<Return>", self._apply_rsi_period)
        self._bind_editing(self._rsi_period_entry, "rsi_period")
        tk.Label(rsi_period_frame, text="overbought").pack(side="left", padx=(8, 2))
        self._rsi_overbought_entry = tk.Entry(rsi_period_frame, width=6, justify="right")
        self._rsi_overbought_entry.pack(side="left", padx=(0, 2))
        self._rsi_overbought_entry.bind("<Return>", self._apply_rsi_period)
        self._bind_editing(self._rsi_overbought_entry, "rsi_period")
        tk.Label(rsi_period_frame, text="sell_half").pack(side="left", padx=(6, 2))
        self._rsi_sell_half_entry = tk.Entry(rsi_period_frame, width=6, justify="right")
        self._rsi_sell_half_entry.pack(side="left", padx=(0, 2))
        self._rsi_sell_half_entry.bind("<Return>", self._apply_rsi_period)
        self._bind_editing(self._rsi_sell_half_entry, "rsi_period")
        tk.Label(rsi_period_frame, text="sell_all").pack(side="left", padx=(6, 2))
        self._rsi_sell_all_entry = tk.Entry(rsi_period_frame, width=6, justify="right")
        self._rsi_sell_all_entry.pack(side="left", padx=(0, 2))
        self._rsi_sell_all_entry.bind("<Return>", self._apply_rsi_period)
        self._bind_editing(self._rsi_sell_all_entry, "rsi_period")
        tk.Button(rsi_period_frame, text="적용", command=self._apply_rsi_period, width=8).pack(
            side="left", padx=6
        )

        order_row = rsi_period_row + 1
        tk.Label(container, text="주문 설정", width=16, anchor="w").grid(
            row=order_row, column=0, padx=3, pady=2, sticky="w"
        )
        order_frame = tk.Frame(container)
        order_frame.grid(row=order_row, column=1, padx=3, pady=2, sticky="w")
        tk.Label(order_frame, text="매수").pack(side="left")
        self._buy_mode_combo = ttk.Combobox(order_frame, width=6, state="readonly")
        self._buy_mode_combo["values"] = ["금액", "수량"]
        self._buy_mode_combo.pack(side="left", padx=(4, 2))
        self._bind_editing(self._buy_mode_combo, "buy_order")
        self._buy_value_entry = tk.Entry(order_frame, width=10, justify="right")
        self._buy_value_entry.pack(side="left", padx=(0, 8))
        self._bind_editing(self._buy_value_entry, "buy_order")
        tk.Button(order_frame, text="매수설정 적용", command=self._apply_order_config, width=12).pack(
            side="left"
        )

        exclude_row = order_row + 1
        tk.Label(container, text="제외 종목", width=16, anchor="w").grid(
            row=exclude_row, column=0, padx=3, pady=2, sticky="nw"
        )
        exclude_frame = tk.LabelFrame(container, text="제외 종목 목록", padx=6, pady=6)
        exclude_frame.grid(row=exclude_row, column=1, padx=3, pady=2, sticky="nsew")
        exclude_frame.rowconfigure(0, weight=1)
        exclude_frame.columnconfigure(0, weight=1)
        exclude_frame.columnconfigure(1, weight=0)

        exclude_list_frame = tk.Frame(exclude_frame)
        exclude_list_frame.grid(row=0, column=0, sticky="nsew")
        exclude_list_frame.rowconfigure(0, weight=1)
        exclude_list_frame.columnconfigure(0, weight=1)

        self._exclude_tree = ttk.Treeview(exclude_list_frame, columns=("code", "name"), show="headings", height=4)
        self._exclude_tree.grid(row=0, column=0, sticky="nsew")
        self._exclude_tree.heading("code", text="코드")
        self._exclude_tree.heading("name", text="이름")
        self._exclude_tree.column("code", width=90, anchor="center", stretch=False)
        self._exclude_tree.column("name", width=160, anchor="w")

        exclude_scroll = tk.Scrollbar(exclude_list_frame, orient="vertical", command=self._exclude_tree.yview)
        exclude_scroll.grid(row=0, column=1, sticky="ns")
        self._exclude_tree.configure(yscrollcommand=exclude_scroll.set)

        exclude_button_frame = tk.Frame(exclude_frame)
        exclude_button_frame.grid(row=0, column=1, sticky="ns", padx=(6, 0))
        tk.Button(exclude_button_frame, text="추가", command=self._add_excluded_code, width=7).pack(pady=(0, 4))
        tk.Button(exclude_button_frame, text="삭제", command=self._remove_excluded_code, width=7).pack()
        
        rsi_row = exclude_row + 1
        tk.Label(container, text="RSI 요약", width=16, anchor="w").grid(
            row=rsi_row, column=0, padx=3, pady=2, sticky="nw"
        )
        self._rsi_body = ScrollableFrame(container, width=620, height=72, horizontal=True)
        self._rsi_body.grid(row=rsi_row, column=1, padx=3, pady=2, sticky="nsew")

        holdings_row = rsi_row + 1
        holdings_control = tk.Frame(container)
        holdings_control.grid(row=holdings_row, column=0, padx=3, pady=2, sticky="nw")
        tk.Label(holdings_control, text="보유 요약", width=10, anchor="w").pack(side="left")
        tk.Button(
            holdings_control,
            text="새로고침",
            width=7,
            command=self._refresh_holdings,
        ).pack(side="left", padx=4)
        self._holdings_frame = tk.Frame(container)
        self._holdings_frame.grid(row=holdings_row, column=1, padx=3, pady=2, sticky="nsew")
        holdings_columns = ("name", "qty", "avg_price", "last_price", "value", "pnl", "action")
        self._holdings_tree = ttk.Treeview(self._holdings_frame, columns=holdings_columns, show="headings", height=6)
        self._holdings_tree.grid(row=0, column=0, sticky="nsew")
        self._holdings_tree.heading("name", text="종목")
        self._holdings_tree.heading("qty", text="수량")
        self._holdings_tree.heading("avg_price", text="평균")
        self._holdings_tree.heading("last_price", text="현재")
        self._holdings_tree.heading("value", text="평가")
        self._holdings_tree.heading("pnl", text="손익(%)")
        self._holdings_tree.heading("action", text="주문")
        self._holdings_tree.column("name", width=96, anchor="w")
        self._holdings_tree.column("qty", width=55, anchor="e", stretch=False)
        self._holdings_tree.column("avg_price", width=80, anchor="e", stretch=False)
        self._holdings_tree.column("last_price", width=80, anchor="e", stretch=False)
        self._holdings_tree.column("value", width=88, anchor="e", stretch=False)
        self._holdings_tree.column("pnl", width=104, anchor="e", stretch=False)
        self._holdings_tree.column("action", width=62, anchor="center", stretch=False)
        self._configure_profit_loss_tags(self._holdings_tree)
        self._holdings_tree.bind("<ButtonRelease-1>", self._on_holdings_tree_click)
        holdings_scroll = tk.Scrollbar(self._holdings_frame, orient="vertical", command=self._holdings_tree.yview)
        holdings_scroll.grid(row=0, column=1, sticky="ns")
        self._holdings_tree.configure(yscrollcommand=holdings_scroll.set)
        self._holdings_frame.columnconfigure(0, weight=1)
        self._holdings_frame.rowconfigure(0, weight=1)

        trade_row = holdings_row + 1
        tk.Label(container, text="당일 매매 상세", width=16, anchor="w").grid(
            row=trade_row, column=0, padx=3, pady=2, sticky="nw"
        )
        trade_frame = tk.Frame(container)
        trade_frame.grid(row=trade_row, column=1, padx=3, pady=2, sticky="nsew")
        columns = ("first_buy", "name", "avg_price", "buy_amount", "sell_amount", "net_pnl", "profit_rate")
        self._trade_tree = ttk.Treeview(trade_frame, columns=columns, show="headings", height=8)
        self._trade_tree.grid(row=0, column=0, sticky="nsew")
        self._trade_tree.heading("first_buy", text="최초매수", command=lambda: self._sort_trade_tree("first_buy"))
        self._trade_tree.heading("name", text="종목", command=lambda: self._sort_trade_tree("name"))
        self._trade_tree.heading("avg_price", text="평균단가", command=lambda: self._sort_trade_tree("avg_price"))
        self._trade_tree.heading("buy_amount", text="매수금액", command=lambda: self._sort_trade_tree("buy_amount"))
        self._trade_tree.heading("sell_amount", text="매도금액", command=lambda: self._sort_trade_tree("sell_amount"))
        self._trade_tree.heading("net_pnl", text="실현손익", command=lambda: self._sort_trade_tree("net_pnl"))
        self._trade_tree.heading("profit_rate", text="수익률", command=lambda: self._sort_trade_tree("profit_rate"))
        self._trade_tree.column("first_buy", width=82, anchor="center", stretch=False)
        self._trade_tree.column("name", width=84, anchor="w")
        self._trade_tree.column("avg_price", width=82, anchor="e", stretch=False)
        self._trade_tree.column("buy_amount", width=102, anchor="e", stretch=False)
        self._trade_tree.column("sell_amount", width=102, anchor="e", stretch=False)
        self._trade_tree.column("net_pnl", width=104, anchor="e", stretch=False)
        self._trade_tree.column("profit_rate", width=72, anchor="e", stretch=False)
        self._configure_profit_loss_tags(self._trade_tree)
        trade_scroll = tk.Scrollbar(trade_frame, orient="vertical", command=self._trade_tree.yview)
        trade_scroll.grid(row=0, column=1, sticky="ns")
        self._trade_tree.configure(yscrollcommand=trade_scroll.set)
        trade_frame.rowconfigure(0, weight=1)
        trade_frame.columnconfigure(0, weight=1)

        container.rowconfigure(rsi_row, weight=1)
        container.rowconfigure(holdings_row, weight=2)
        container.rowconfigure(trade_row, weight=1)

    @staticmethod
    def _new_sync_entry() -> dict:
        """항목별 동기화 상태 엔트리를 생성한다."""
        return {
            "seen_version": 0,
            "pending_expected_version": 0,
            "pending_deadline": None,
            "editing": False,
        }

    def _now(self) -> datetime.datetime:
        """동기화 타임아웃 계산용 현재 시간을 반환한다."""
        return datetime.datetime.now()

    def _get_sync_entry(self, key: str) -> dict:
        """항목별 동기화 상태를 반환한다."""
        if not hasattr(self, "_sync_state") or self._sync_state is None:
            self._sync_state = {}
        entry = self._sync_state.get(key)
        if entry is None:
            entry = self._new_sync_entry()
            self._sync_state[key] = entry
        return entry

    def _mark_pending(self, key: str) -> None:
        """사용자 명령 전송 직후 대기 상태를 설정한다."""
        entry = self._get_sync_entry(key)
        seen = int(entry.get("seen_version", 0))
        entry["pending_expected_version"] = seen + 1
        entry["pending_deadline"] = self._now() + datetime.timedelta(seconds=float(self._sync_timeout_sec))

    def _set_editing(self, key: str, is_editing: bool) -> None:
        """편집 중 상태를 설정한다."""
        entry = self._get_sync_entry(key)
        entry["editing"] = bool(is_editing)

    def _bind_editing(self, widget, key: str) -> None:
        """위젯 포커스 이벤트를 편집 상태와 연결한다."""
        if widget is None:
            return
        widget.bind("<FocusIn>", lambda _e, k=key: self._set_editing(k, True), add="+")
        widget.bind("<FocusOut>", lambda _e, k=key: self._set_editing(k, False), add="+")

    def _should_sync(self, key: str, snapshot_version: int) -> bool:
        """버전 규칙에 따라 UI 동기화 가능 여부를 반환한다."""
        entry = self._get_sync_entry(key)
        current_seen = int(entry.get("seen_version", 0))
        current_version = int(snapshot_version or 0)
        pending_expected = int(entry.get("pending_expected_version", 0))
        pending_deadline = entry.get("pending_deadline")
        editing = bool(entry.get("editing", False))

        if pending_expected > 0:
            if current_version >= pending_expected:
                entry["seen_version"] = max(current_seen, current_version)
                entry["pending_expected_version"] = 0
                entry["pending_deadline"] = None
                return not editing
            if pending_deadline is not None and self._now() >= pending_deadline:
                entry["seen_version"] = max(current_seen, current_version)
                entry["pending_expected_version"] = 0
                entry["pending_deadline"] = None
                return not editing
            return False

        if editing:
            return False
        if current_version < current_seen:
            return False
        entry["seen_version"] = max(current_seen, current_version)
        return True

    def update(self, snapshot: StatusSnapshot) -> None:
        """스냅샷 정보를 UI에 반영한다."""
        self._labels["server_mode"].config(text=snapshot.server_mode)
        self._labels["account_no"].config(text=snapshot.account_no)
        self._labels["watchlist_count"].config(text=str(snapshot.watchlist_count))
        self._labels["watchlist_names"].config(text=snapshot.watchlist_names)
        self._labels["holding_count"].config(text=str(snapshot.holding_count))
        self._labels["realtime_status"].config(text=snapshot.realtime_status)
        if snapshot.realtime_status_level == "warn":
            self._labels["realtime_status"].config(fg="#B22222")
        else:
            self._labels["realtime_status"].config(fg="black")
        self._labels["account_summary"].config(text=snapshot.account_summary)
        self._labels["last_signal"].config(text=snapshot.last_signal)
        self._labels["last_update"].config(text=snapshot.last_update.strftime("%Y-%m-%d %H:%M:%S"))
        if self._condition_combo is not None and self._should_sync("condition", snapshot.condition_version):
            items = snapshot.condition_items or []
            values = [f"{item.get('index')} - {item.get('name', '')}" for item in items]
            if values != self._condition_values:
                self._condition_combo["values"] = values
                self._condition_values = values
            for i, item in enumerate(items):
                if item.get("index") == snapshot.condition_index:
                    if self._condition_combo.current() != i:
                        self._condition_combo.current(i)
                    break
        if self._strategy_combo is not None and self._should_sync("strategy", snapshot.strategy_version):
            items = snapshot.strategy_items or []
            values = [f"{item.get('name')} - {item.get('label', '')}" for item in items]
            if values != self._strategy_values:
                self._strategy_combo["values"] = values
                self._strategy_values = values
            for i, item in enumerate(items):
                if item.get("name") == snapshot.strategy_name:
                    if self._strategy_combo.current() != i:
                        self._strategy_combo.current(i)
                    break
            pyramiding_map = {
                str(item.get("name", "") or ""): bool(item.get("pyramiding_enabled", True))
                for item in items
            }
            cci_filter_map = {
                str(item.get("name", "") or ""): bool(item.get("cci_filter_enabled", False))
                for item in items
            }
            if self._rsi_pyramiding_var is not None:
                self._rsi_pyramiding_var.set(bool(pyramiding_map.get("rsi_grid", True)))
            if self._rsi_cci_var is not None:
                self._rsi_cci_var.set(bool(cci_filter_map.get("rsi_grid", False)))
            if self._livermore_pyramiding_var is not None:
                self._livermore_pyramiding_var.set(bool(pyramiding_map.get("livermore_pyramid", True)))
            if self._livermore_cci_var is not None:
                self._livermore_cci_var.set(bool(cci_filter_map.get("livermore_pyramid", False)))
        if self._should_sync("cci_threshold", snapshot.strategy_version):
            strategy_map = {
                str(item.get("name", "") or ""): item for item in (snapshot.strategy_items or [])
            }
            self._sync_cci_entry_pair(
                getattr(self, "_rsi_cci_entry_entry", None),
                getattr(self, "_rsi_cci_add_entry", None),
                strategy_map.get("rsi_grid", {}),
            )
            self._sync_cci_entry_pair(
                getattr(self, "_livermore_cci_entry_entry", None),
                getattr(self, "_livermore_cci_add_entry", None),
                strategy_map.get("livermore_pyramid", {}),
            )
        if self._candle_combo is not None and self._should_sync("candle", snapshot.candle_version):
            if snapshot.candle_source == "minute":
                text = f"{snapshot.minutes_per_candle}분"
            else:
                text = f"{snapshot.ticks_per_candle}틱"
            if text in self._candle_values:
                index = self._candle_values.index(text)
                if self._candle_combo.current() != index:
                    self._candle_combo.current(index)
        if self._rsi_period_entry is not None and self._should_sync("rsi_period", snapshot.rsi_period_version):
            current_text = self._rsi_period_entry.get().strip()
            target_text = str(snapshot.rsi_period)
            if current_text != target_text:
                self._rsi_period_entry.delete(0, tk.END)
                self._rsi_period_entry.insert(0, target_text)
            self._sync_numeric_entry(self._rsi_overbought_entry, getattr(snapshot, "rsi_overbought", 70.0))
            self._sync_numeric_entry(self._rsi_sell_half_entry, getattr(snapshot, "rsi_sell_half", 39.0))
            self._sync_numeric_entry(self._rsi_sell_all_entry, getattr(snapshot, "rsi_sell_all", 29.0))
        if self._buy_mode_combo is not None and self._should_sync("buy_order", snapshot.buy_order_version):
            buy_label = "금액" if snapshot.buy_size_mode == "cash" else "수량"
            if self._buy_mode_combo.get() != buy_label:
                self._buy_mode_combo.set(buy_label)
            if self._buy_value_entry is not None:
                target_text = str(snapshot.buy_size_value)
                if self._buy_value_entry.get().strip() != target_text:
                    self._buy_value_entry.delete(0, tk.END)
                    self._buy_value_entry.insert(0, target_text)
        exclude_entry = getattr(self, "_exclude_codes_entry", None)
        exclude_tree = getattr(self, "_exclude_tree", None)
        exclude_version = int(getattr(snapshot, "exclude_version", 0))
        excluded_items = list(getattr(snapshot, "excluded_items", []) or [])
        if exclude_tree is not None and self._should_sync("exclude", exclude_version):
            self._update_exclude_tree(excluded_items)
            if exclude_entry is not None:
                exclude_entry.delete(0, tk.END)
        self._render_rsi(snapshot.rsi_items)
        self._render_holdings(snapshot.holdings_items)
        self._render_daily_trades(getattr(snapshot, "daily_trade_items", []))
        self._resize_window_to_content()

    def _render_daily_trades(self, items) -> None:
        """당일 매매 상세를 표 형태로 렌더링한다."""
        if self._trade_tree is None:
            return
        self._configure_profit_loss_tags(self._trade_tree)
        self._trade_items = [item for item in list(items or []) if item.get("type") in {"trade", "trade_group"}]
        self._trade_tree.delete(*self._trade_tree.get_children())
        if not self._trade_items:
            self._trade_tree.insert("", "end", values=("-", "-", "-", "-", "-", "-", "-"))
            return
        self._populate_trade_tree()

    def _populate_trade_tree(self) -> None:
        """현재 정렬 기준으로 매매 상세 표를 채운다."""
        if self._trade_tree is None:
            return
        self._configure_profit_loss_tags(self._trade_tree)
        self._trade_tree.delete(*self._trade_tree.get_children())
        sorted_items = sorted(
            self._trade_items,
            key=lambda item: self._trade_sort_key(item, self._trade_sort_column),
            reverse=bool(self._trade_sort_descending),
        )
        for item in sorted_items:
            avg = int(item.get("avg_price", 0) or 0)
            net_pnl = int(item.get("net_pnl", 0) or 0)
            profit_rate = float(item.get("profit_rate", 0.0) or 0.0)
            tags = ()
            if net_pnl > 0:
                tags = ("profit",)
            elif net_pnl < 0:
                tags = ("loss",)
            self._trade_tree.insert(
                "",
                "end",
                values=(
                    item.get("first_buy", "-"),
                    item.get("name", "-"),
                    f"{avg:,}원" if avg > 0 else "-",
                    f"{int(item.get('buy_amount', 0)):,}원",
                    f"{int(item.get('sell_amount', 0)):,}원",
                    f"{net_pnl:+,}원",
                    f"{profit_rate:.2f}%",
                ),
                tags=tags,
            )

    def _sort_trade_tree(self, column: str) -> None:
        """컬럼 클릭 시 매매 상세 표 정렬을 전환한다."""
        if self._trade_tree is None:
            return
        if self._trade_sort_column == column:
            self._trade_sort_descending = not self._trade_sort_descending
        else:
            self._trade_sort_column = str(column)
            self._trade_sort_descending = column != "name"
        self._populate_trade_tree()

    @staticmethod
    def _trade_sort_key(item: dict, column: str):
        """매매 상세 표 정렬용 키를 계산한다."""
        if column == "first_buy":
            value = str(item.get("first_buy", "") or "")
            return (value == "", value)
        if column in {"avg_price", "buy_amount", "sell_amount", "net_pnl"}:
            return int(item.get(column, 0) or 0)
        if column == "profit_rate":
            return float(item.get(column, 0.0) or 0.0)
        return str(item.get(column, "") or "")

    def _apply_condition(self, event=None) -> None:
        """조건식 인덱스를 적용한다."""
        if self._on_change_condition is None or self._condition_combo is None:
            return
        text = self._condition_combo.get()
        if not text:
            return
        index_text = text.split("-", 1)[0].strip()
        try:
            index = int(index_text)
        except ValueError:
            return
        self._mark_pending("condition")
        self._run_background("change_condition", self._on_change_condition, index)

    def _refresh_conditions(self) -> None:
        """조건식 목록을 새로고침한다."""
        if self._on_refresh_conditions is None:
            return
        self._run_background("refresh_conditions", self._on_refresh_conditions)

    def _refresh_holdings(self) -> None:
        """보유 종목 정보를 서버 기준으로 즉시 새로고침한다."""
        if self._on_refresh_holdings is None:
            return
        self._run_background("refresh_holdings", self._on_refresh_holdings)

    def _apply_strategy(self, event=None) -> None:
        """전략을 적용한다."""
        if self._strategy_combo is None or self._on_change_strategy is None:
            return
        text = self._strategy_combo.get()
        if not text:
            return
        name = text.split("-", 1)[0].strip()
        if not name:
            return
        self._mark_pending("strategy")
        self._run_background("change_strategy", self._on_change_strategy, name)

    def _apply_rsi_pyramiding(self) -> None:
        """RSI 피라미딩 사용 여부를 적용한다."""
        if self._on_change_pyramiding is None or self._rsi_pyramiding_var is None:
            return
        self._mark_pending("strategy")
        self._run_background("rsi_pyramiding", self._on_change_pyramiding, "rsi_grid", bool(self._rsi_pyramiding_var.get()))

    def _apply_livermore_pyramiding(self) -> None:
        """Livermore 피라미딩 사용 여부를 적용한다."""
        if self._on_change_pyramiding is None or self._livermore_pyramiding_var is None:
            return
        self._mark_pending("strategy")
        self._run_background(
            "livermore_pyramiding",
            self._on_change_pyramiding,
            "livermore_pyramid",
            bool(self._livermore_pyramiding_var.get()),
        )

    def _apply_rsi_cci_filter(self) -> None:
        """RSI CCI 필터 사용 여부를 적용한다."""
        if self._on_change_cci_filter is None or self._rsi_cci_var is None:
            return
        self._mark_pending("strategy")
        self._run_background("rsi_cci_filter", self._on_change_cci_filter, "rsi_grid", bool(self._rsi_cci_var.get()))

    def _apply_livermore_cci_filter(self) -> None:
        """Livermore CCI 필터 사용 여부를 적용한다."""
        if self._on_change_cci_filter is None or self._livermore_cci_var is None:
            return
        self._mark_pending("strategy")
        self._run_background(
            "livermore_cci_filter",
            self._on_change_cci_filter,
            "livermore_pyramid",
            bool(self._livermore_cci_var.get()),
        )

    @staticmethod
    def _format_cci_threshold(value) -> str:
        """CCI 기준값을 입력창용 문자열로 포맷한다."""
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return ""
        if numeric.is_integer():
            return str(int(numeric))
        return f"{numeric:.1f}"

    @staticmethod
    def _format_numeric_entry_value(value) -> str:
        """설정 숫자를 입력창용 문자열로 포맷한다."""
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return ""
        if numeric.is_integer():
            return str(int(numeric))
        return f"{numeric:.1f}"

    def _sync_numeric_entry(self, entry_widget, value) -> None:
        """숫자 입력창을 스냅샷 값과 동기화한다."""
        if entry_widget is None:
            return
        target = self._format_numeric_entry_value(value)
        if entry_widget.get().strip() != target:
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, target)

    def _sync_cci_entry_pair(self, entry_widget, add_widget, item: dict) -> None:
        """CCI 기준값 입력창 한 쌍을 스냅샷과 동기화한다."""
        if entry_widget is not None:
            target_entry = self._format_cci_threshold(item.get("cci_entry_threshold", 0.0))
            if entry_widget.get().strip() != target_entry:
                entry_widget.delete(0, tk.END)
                entry_widget.insert(0, target_entry)
        if add_widget is not None:
            target_add = self._format_cci_threshold(item.get("cci_add_threshold", 0.0))
            if add_widget.get().strip() != target_add:
                add_widget.delete(0, tk.END)
                add_widget.insert(0, target_add)

    def _apply_rsi_cci_thresholds(self) -> None:
        """RSI 전략의 CCI 기준값을 적용한다."""
        if self._on_change_cci_threshold is None or self._rsi_cci_entry_entry is None or self._rsi_cci_add_entry is None:
            return
        try:
            entry_value = float(self._rsi_cci_entry_entry.get().strip())
            add_value = float(self._rsi_cci_add_entry.get().strip())
        except (TypeError, ValueError):
            return
        self._mark_pending("cci_threshold")
        self._run_background("rsi_cci_threshold", self._on_change_cci_threshold, "rsi_grid", entry_value, add_value)

    def _apply_livermore_cci_thresholds(self) -> None:
        """Livermore 전략의 CCI 기준값을 적용한다."""
        if self._on_change_cci_threshold is None or self._livermore_cci_entry_entry is None or self._livermore_cci_add_entry is None:
            return
        try:
            entry_value = float(self._livermore_cci_entry_entry.get().strip())
            add_value = float(self._livermore_cci_add_entry.get().strip())
        except (TypeError, ValueError):
            return
        self._mark_pending("cci_threshold")
        self._run_background(
            "livermore_cci_threshold",
            self._on_change_cci_threshold,
            "livermore_pyramid",
            entry_value,
            add_value,
        )

    def _apply_candle(self, event=None) -> None:
        """캔들 기준을 적용한다."""
        if self._candle_combo is None or self._on_change_candle is None:
            return
        text = self._candle_combo.get()
        if not text:
            return
        if text.endswith("틱"):
            try:
                value = int(text.replace("틱", "").strip())
            except ValueError:
                return
            self._mark_pending("candle")
            self._run_background("change_candle", self._on_change_candle, "tick", value)
        elif text.endswith("분"):
            try:
                value = int(text.replace("분", "").strip())
            except ValueError:
                return
            self._mark_pending("candle")
            self._run_background("change_candle", self._on_change_candle, "minute", value)

    def _apply_rsi_period(self, event=None) -> None:
        """RSI 기간 변경을 적용한다."""
        if self._rsi_period_entry is None:
            return
        text = self._rsi_period_entry.get().strip()
        if not text:
            return
        try:
            value = int(text)
        except ValueError:
            return
        if value <= 0:
            return

        thresholds = None
        if self._on_change_rsi_thresholds is None:
            thresholds = None
        else:
            try:
                thresholds = (
                    float(self._rsi_overbought_entry.get().strip()),
                    float(self._rsi_sell_half_entry.get().strip()),
                    float(self._rsi_sell_all_entry.get().strip()),
                )
            except (AttributeError, TypeError, ValueError):
                thresholds = None

        def apply_rsi_config() -> None:
            if self._on_change_rsi_period is not None:
                self._on_change_rsi_period(value)
            if thresholds is not None and self._on_change_rsi_thresholds is not None:
                self._on_change_rsi_thresholds(*thresholds)

        self._mark_pending("rsi_period")
        self._run_background("change_rsi_config", apply_rsi_config)

    def _apply_order_config(self, event=None) -> None:
        """매수 주문 금액/수량 설정을 적용한다."""
        if self._on_change_order_config is None:
            return
        if self._buy_mode_combo is None or self._buy_value_entry is None:
            return
        buy_mode_text = self._buy_mode_combo.get().strip()
        mode_map = {"금액": "cash", "수량": "qty"}
        buy_mode = mode_map.get(buy_mode_text, "")
        if not buy_mode:
            return
        try:
            buy_value = int(self._buy_value_entry.get().strip())
        except ValueError:
            return
        if buy_value < 0:
            return
        self._mark_pending("buy_order")
        self._run_background("change_order_config", self._on_change_order_config, buy_mode, buy_value)

    def _add_excluded_code(self, event=None) -> None:
        """제외 종목을 리스트에 추가하고 즉시 반영한다."""
        if self._exclude_tree is None:
            return
        code_or_name = self._prompt_excluded_code()
        if not code_or_name:
            return
        items = [self._exclude_tree.item(item_id, "values")[0] for item_id in self._exclude_tree.get_children()]
        names = [self._exclude_tree.item(item_id, "values")[1] for item_id in self._exclude_tree.get_children()]
        if code_or_name not in items and code_or_name not in names:
            self._exclude_tree.insert("", "end", values=(code_or_name, ""))
            self._apply_excluded_codes()

    def _prompt_excluded_code(self) -> str:
        """제외 종목 추가용 입력 팝업을 표시한다."""
        if self._exclude_codes_entry is not None:
            try:
                value = str(self._exclude_codes_entry.get() or "").strip().upper()
                if value:
                    return value
            except Exception:
                pass
        value = simpledialog.askstring("제외 종목 추가", "종목코드 또는 종목명을 입력하세요.", parent=self._root)
        return str(value or "").strip().upper()

    def _remove_excluded_code(self, event=None) -> None:
        """선택된 제외 종목을 리스트에서 제거하고 즉시 반영한다."""
        if self._exclude_tree is None:
            return
        selection = self._exclude_tree.selection()
        for item_id in selection:
            self._exclude_tree.delete(item_id)
        if selection:
            self._apply_excluded_codes()

    def _update_exclude_tree(self, items: list) -> None:
        """제외 종목 표를 코드/이름 목록으로 갱신한다."""
        if self._exclude_tree is None:
            return
        self._exclude_tree.delete(*self._exclude_tree.get_children())
        for item in items:
            self._exclude_tree.insert(
                "",
                "end",
                values=(
                    str(item.get("code", "") or ""),
                    str(item.get("name", "") or ""),
                ),
            )

    def _apply_excluded_codes(self, event=None) -> None:
        """제외 종목 리스트를 서버에 적용한다."""
        if self._on_change_excluded_codes is None:
            return
        tree = getattr(self, "_exclude_tree", None)
        if tree is None:
            return
        codes = []
        for item_id in tree.get_children():
            values = tree.item(item_id, "values")
            code = str(values[0] if values else "").strip()
            name = str(values[1] if len(values) > 1 else "").strip()
            codes.append(code or name)
        excluded_codes_text = ", ".join([code for code in codes if code])
        self._mark_pending("exclude")
        self._run_background("change_excluded_codes", self._on_change_excluded_codes, excluded_codes_text)

    def _render_rsi(self, items) -> None:
        """RSI 요약을 표 형태로 렌더링한다."""
        if self._rsi_body is None:
            return
        self._rsi_body.clear()
        items = items or []
        if not items:
            tk.Label(self._rsi_body.content, text="-", anchor="w").grid(row=0, column=0, sticky="w")
            return
        display = items[:20]
        for idx, item in enumerate(display):
            name = item.get("name", "")
            value = item.get("value")
            if value is None:
                text = f"{name} -"
            else:
                text = f"{name} {value:.2f}"
            tk.Label(
                self._rsi_body.content,
                text=text,
                width=16,
                anchor="w",
                relief="groove",
                padx=4,
                pady=2,
            ).grid(
                row=0, column=idx, padx=(0, 4), pady=1, sticky="w"
            )

    def _on_container_configure(self, event) -> None:
        """창 크기 변경 시 텍스트 줄바꿈 폭을 조정한다."""
        if event is None:
            return
        wrap = max(320, event.width - 220)
        for label in self._labels.values():
            label.configure(wraplength=wrap)

    def _render_holdings(self, items) -> None:
        """보유 종목 테이블을 렌더링한다."""
        if self._holdings_tree is None:
            return
        self._configure_profit_loss_tags(self._holdings_tree)
        self._holdings_row_codes = {}
        self._holdings_tree.delete(*self._holdings_tree.get_children())
        for item in items or []:
            pnl_amount = int(item.get("pnl_amount", 0))
            pnl_rate = float(item.get("pnl_rate", 0.0))
            tags = ()
            if pnl_amount > 0:
                tags = ("profit",)
            elif pnl_amount < 0:
                tags = ("loss",)
            row_id = self._holdings_tree.insert(
                "",
                "end",
                values=(
                    item.get("name", ""),
                    str(item.get("qty", 0)),
                    f"{int(item.get('avg_price', 0)):,}",
                    f"{int(item.get('last_price', 0)):,}",
                    f"{int(item.get('value', 0)):,}",
                    f"{pnl_amount:+,} ({pnl_rate:.2f}%)",
                    "전량매도" if self._on_sell_all else "-",
                ),
                tags=tags,
            )
            self._holdings_row_codes[row_id] = str(item.get("code", "") or "")

    def _on_holdings_tree_click(self, event=None) -> None:
        """보유 종목 표의 주문 열 클릭을 처리한다."""
        if self._holdings_tree is None or self._on_sell_all is None or event is None:
            return
        row_id = self._holdings_tree.identify_row(event.y)
        column_id = self._holdings_tree.identify_column(event.x)
        if not row_id or column_id != "#7":
            return
        code = str(self._holdings_row_codes.get(row_id, "") or "")
        if code:
            self._run_background("sell_all", self._on_sell_all, code)

    def _resize_window_to_content(self) -> None:
        """현재 콘텐츠 높이에 맞춰 창 높이를 자동으로 늘린다."""
        self._root.update_idletasks()
        current_width = max(self._root.winfo_width(), self._root.winfo_reqwidth(), 900)
        required_height = self._root.winfo_reqheight() + 24
        screen_limit = int(self._root.winfo_screenheight() * 0.9)
        target_height = min(required_height, screen_limit)
        current_height = self._root.winfo_height()
        if target_height > current_height:
            self._root.geometry(f"{current_width}x{target_height}")

    def run(self, bus: StatusBus, refresh_ms: int) -> None:
        """상태 버스를 주기적으로 확인하며 UI를 실행한다."""
        interval = max(50, int(refresh_ms or 500))

        def poll() -> None:
            """상태 버스를 주기적으로 확인한다."""
            try:
                snapshot = bus.try_get()
                if snapshot is not None:
                    self.update(snapshot)
            except tk.TclError:
                LOGGER.exception("UI 갱신 중 Tk 오류")
            except Exception:
                LOGGER.exception("UI 갱신 실패")
            try:
                self._root.after(interval, poll)
            except tk.TclError:
                LOGGER.info("UI 종료로 상태 갱신 루프를 중단합니다.")

        poll()
        self._root.mainloop()
