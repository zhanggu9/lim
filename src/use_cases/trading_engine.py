from __future__ import annotations

import copy
import datetime
import queue
import re
import time
import threading
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

from app.status_bus import StatusBus, StatusSnapshot
from domain.entities import Candle, Tick, TradeSignal
from domain.indicators import RsiTracker
from domain.blocklist import Blocklist
from infrastructure.kiwoom.chejan_parser import parse_balance_event, parse_order_event
from infrastructure.kiwoom.kiwoom_parser import clean_int, normalize_code, parse_condition_list
from infrastructure.kiwoom.real_data_parser import parse_tick
from infrastructure.blocklist_storage import SettingsBasedBlocklistStorage
from interfaces.gateways import BrokerGateway, ConditionGateway, MarketDataGateway, ChejanGateway
from use_cases.blocklist_manager import BlocklistManager
from use_cases.cooldown import CooldownTracker
from use_cases.daily_trade_tracker import DailyTradeTracker
from use_cases.market_hours import MarketHours
from use_cases.order_sizer import OrderSizer
from use_cases.portfolio import Portfolio
from use_cases.strategy import create_strategy, list_strategies
from use_cases.tick_aggregator import TickAggregator
from use_cases.time_aggregator import TimeAggregator
from use_cases.watchlist_manager import WatchlistManager


class TradingEngine:
    """조건식, 실시간 체결, 주문 로직을 통합 실행한다."""

    def __init__(
        self,
        settings,
        gateway,
        logger,
        status_bus: StatusBus,
        clock,
        trade_logger=None,
        chejan_logger=None,
    ) -> None:
        """거래 엔진 구성 요소를 초기화한다."""
        self._settings = settings
        self._gateway = gateway
        self._logger = logger
        self._trade_logger = trade_logger or logger
        # 수신된 CHEJAN 원본 로그 로거를 인스턴스에 보관 (선택적)
        self._chejan_logger = chejan_logger if chejan_logger else None
        self._status_bus = status_bus
        self._clock = clock

        self._portfolio = Portfolio()
        include_holdings = bool(getattr(settings, "watchlist_include_holdings", True))
        self._watchlist = WatchlistManager(
            max_total=settings.max_total_symbols,
            include_holdings=include_holdings,
        )
        self._order_sizer = OrderSizer()
        candle_source = getattr(settings, "candle_source", "tick")
        if candle_source == "minute":
            minutes_per_candle = getattr(settings, "minutes_per_candle", 1)
            self._aggregator = TimeAggregator(minutes_per_candle=minutes_per_candle)
        else:
            self._aggregator = TickAggregator(ticks_per_candle=settings.ticks_per_candle)
        self._aggregator_lock = threading.Lock()
        # 종목별로 aggregator 상태를 병렬로 갱신하기 위한 샤딩 락들
        self._aggregator_locks: Dict[str, threading.Lock] = {}
        self._aggregator_locks_lock = threading.Lock()
        # CHEJAN 원본 로그 전용 로거: 생성자 파라미터 우선, 없으면 settings에서 시도
        if self._chejan_logger is None:
            try:
                self._chejan_logger = getattr(settings, "chejan_logger", None)
            except Exception:
                self._chejan_logger = None
        # 이미 처리된 체결을 중복 기록하지 않기 위한 집합 (일별 초기화)
        self._seen_executions: set = set()
        self._seen_executions_date: Optional[datetime.date] = None
        self._rsi_trackers: Dict[str, RsiTracker] = {}
        self._rsi_trackers_lock = threading.RLock()  # rsi_trackers 전용 락 (레이스 컨디션 방지)
        
        # Save mode-specific defaults for candle switching
        # 현재 모드가 무엇이든, 각 모드별 기본값을 명확히 저장한다
        # candle_source는 위에서 이미 선언됨 (재사용)
        if candle_source == "minute":
            # 분봉 모드로 시작: 현재값은 분봉 설정, 틱 모드 기본값은 고정값
            self._tick_default_rsi_period = 14  # 틱 모드의 기본값 (고정)
            self._tick_default_rsi_overbought = 70.0
            self._tick_default_rsi_sell_half = 39.0
            self._tick_default_rsi_sell_all = 29.0
            self._minute_default_rsi_period = int(getattr(settings, "rsi_period", 9))
            self._minute_default_rsi_overbought = float(getattr(settings, "rsi_overbought", 70.0))
            self._minute_default_rsi_sell_half = float(getattr(settings, "rsi_sell_half", 59.0))
            self._minute_default_rsi_sell_all = float(getattr(settings, "rsi_sell_all", 39.0))
        else:
            # 틱 모드로 시작: 현재값은 틱 설정, 분봉 모드 기본값은 고정값
            self._tick_default_rsi_period = int(getattr(settings, "rsi_period", 14))
            self._tick_default_rsi_overbought = float(getattr(settings, "rsi_overbought", 70.0))
            self._tick_default_rsi_sell_half = float(getattr(settings, "rsi_sell_half", 39.0))
            self._tick_default_rsi_sell_all = float(getattr(settings, "rsi_sell_all", 29.0))
            self._minute_default_rsi_period = 9  # 분봉 모드의 기본값 (고정)
            self._minute_default_rsi_overbought = 70.0
            self._minute_default_rsi_sell_half = 59.0
            self._minute_default_rsi_sell_all = 39.0

        cooldown = CooldownTracker(seconds=settings.cooldown_seconds, clock=clock)
        market_hours = MarketHours(
            start=settings.market_start,
            end=settings.market_end,
            timezone=settings.market_timezone,
        )
        
        # Blocklist 초기화
        # settings를 dict로 변환
        settings_dict = settings.__dict__ if hasattr(settings, '__dict__') else {}
        if not isinstance(settings_dict, dict):
            settings_dict = {"excluded_codes": ""}
        storage = SettingsBasedBlocklistStorage(settings_dict)
        self._blocklist_manager = BlocklistManager(repository=storage)
        try:
            self._blocklist_manager.load()
        except Exception as e:
            self._logger.warning("BlocklistManager 로드 실패: %s", e)
        
        self._strategy_name = getattr(settings, "strategy_name", "rsi_grid")
        self._strategy_items = list_strategies()
        self._strategy = create_strategy(
            self._strategy_name,
            settings,
            cooldown,
            self._order_sizer,
            market_hours,
        )

        self._account_no = ""
        self._server_mode = ""
        self._condition_name = ""
        self._condition_list: List[tuple] = []
        self._condition_started = False
        self._condition_log_emitted = False
        self._condition_lock = threading.RLock()
        self._last_watchlist: List[str] = []
        self._last_signal = "-"
        self._last_rsi = "-"
        self._allow_trading = False
        self._tick_counts: Dict[str, int] = {}
        self._last_tick_time: Dict[str, datetime.datetime] = {}
        self._last_tick_log: Optional[datetime.datetime] = None
        self._watchlist_since: Dict[str, datetime.datetime] = {}
        self._code_names: Dict[str, str] = {}
        self._last_prices: Dict[str, int] = {}
        self._last_rsi_values: Dict[str, float] = {}
        self._last_candle_end_time: Dict[str, str] = {}
        self._account_info: Dict[str, float] = {}
        self._last_account_refresh: Optional[datetime.datetime] = None
        self._last_holdings_refresh: Optional[datetime.datetime] = None
        self._daily_tracker = DailyTradeTracker(clock, fee_rate=getattr(settings, "fee_rate", 0.0))
        self._order_fill_snapshot: Dict[tuple, int] = {}
        self._force_account_refresh: bool = False  # 체결 후 강제 갱신 플래그
        self._last_real_reg_at: Optional[datetime.datetime] = None
        self._pending_watchlist: Optional[List[str]] = None
        self._total_ticks_received = 0
        self._total_ticks_processed = 0
        self._ui_versions: Dict[str, int] = {
            "condition": 0,
            "strategy": 0,
            "candle": 0,
            "rsi_period": 0,
            "buy_order": 0,
            "exclude": 0,
        }
        queue_size = max(1, int(getattr(settings, "tick_queue_maxsize", 10000)))
        self._queue_policy_mode = str(getattr(settings, "queue_policy_mode", "hybrid") or "hybrid").lower()
        self._legacy_single_queue = bool(getattr(settings, "legacy_single_queue", False))
        if self._queue_policy_mode == "legacy_single_queue":
            self._legacy_single_queue = True
        self._tick_queue_soft_ratio = min(
            0.99,
            max(0.05, float(getattr(settings, "tick_queue_soft_ratio", 0.80))),
        )
        self._tick_queue_hard_ratio = min(
            1.0,
            max(self._tick_queue_soft_ratio, float(getattr(settings, "tick_queue_hard_ratio", 0.95))),
        )
        self._tick_queue_overload_wait_sec = max(
            0.0,
            float(getattr(settings, "tick_queue_overload_wait_ms", 0.0)) / 1000.0,
        )
        self._tick_queue_emergency_drop_batch = max(
            1,
            int(getattr(settings, "tick_queue_emergency_drop_batch", 50)),
        )
        shard_count = max(
            1,
            int(
                getattr(
                    settings,
                    "tick_compute_shard_count",
                    getattr(settings, "tick_compute_worker_count", 20),
                )
            ),
        )
        if self._legacy_single_queue:
            shard_count = 1
        self._tick_compute_shard_count = shard_count
        if shard_count <= 1:
            self._tick_queue: queue.Queue[Tick] = queue.Queue(maxsize=queue_size)
            self._tick_shard_queues: List[queue.Queue[Tick]] = [self._tick_queue]
        else:
            shard_queue_size = max(1, int((queue_size + shard_count - 1) / shard_count))
            self._tick_shard_queues = [queue.Queue(maxsize=shard_queue_size) for _ in range(shard_count)]
            # 하위 호환성: 일부 테스트/코드가 _tick_queue를 직접 참조할 수 있다.
            self._tick_queue = self._tick_shard_queues[0]
        self._tick_shard_peak_sizes: List[int] = [0 for _ in range(len(self._tick_shard_queues))]
        self._tick_shard_drop_counts: List[int] = [0 for _ in range(len(self._tick_shard_queues))]
        self._tick_drop_count = 0
        self._tick_emergency_drop_count = 0
        self._last_tick_drop_log: Optional[datetime.datetime] = None
        self._last_tick_backpressure_log: Optional[datetime.datetime] = None
        self._recent_tick_buffer_size = max(
            100,
            int(getattr(settings, "minute_backfill_tick_buffer_size", 800)),
        )
        self._minute_backfill_tick_size = max(
            1,
            int(getattr(settings, "minute_backfill_tick_size", 20)),
        )
        self._minute_backfill_candle_count = max(
            1,
            int(getattr(settings, "minute_backfill_candle_count", 20)),
        )
        self._recent_tick_aggregator = TickAggregator(ticks_per_candle=self._minute_backfill_tick_size)
        self._recent_minute_aggregator = TimeAggregator(minutes_per_candle=1)
        self._recent_candles_by_code: Dict[str, Deque[Candle]] = {}
        self._recent_minute_candles_by_code: Dict[str, Deque[Candle]] = {}
        self._signal_markers: Dict[tuple, str] = {}
        self._signal_marker_lock = threading.Lock()
        self._sell_sync_guard: Dict[str, tuple] = {}
        self._manual_sell_pending: Dict[str, Dict[str, object]] = {}
        self._manual_sell_trace_interval_sec = max(
            1.0,
            float(getattr(settings, "manual_sell_trace_interval_sec", 5.0)),
        )
        self._manual_sell_trace_timeout_sec = max(
            self._manual_sell_trace_interval_sec,
            float(getattr(settings, "manual_sell_trace_timeout_sec", 30.0)),
        )
        # Livermore 피라미딩 단계 주문의 미체결 재시도 상태
        self._strategy_pending_lock = threading.Lock()
        self._strategy_retry_lock = threading.Lock()
        self._strategy_pending_orders: Dict[tuple, Dict[str, object]] = {}
        self._strategy_retry_timeout_sec = max(
            1.0,
            float(getattr(settings, "livermore_retry_timeout_sec", 15.0)),
        )
        self._strategy_retry_max = max(0, int(getattr(settings, "livermore_retry_max", 1)))
        self._last_watchset = set()
        self._excluded_codes_set = set(
            self._normalize_excluded_codes(getattr(self._settings, "excluded_codes", []))
        )
        self._settings.excluded_codes = sorted(self._excluded_codes_set)
        self._watchlist.set_excluded_codes(self._excluded_codes_set)

    def initialize(self) -> None:
        """로그인 후 초기 상태를 구성한다."""
        self._server_mode = self._gateway.get_server_gubun()
        self._allow_trading = self._validate_mode(self._settings.mode, self._server_mode)

        accounts = self._gateway.get_account_numbers()
        self._account_no = accounts[0] if accounts else ""
        self._logger.info("계좌 선택: %s", self._account_no)

        if self._account_no:
            self._refresh_holdings(force=True)
            self._refresh_account_info(force=True)

        self._try_setup_condition(retry_seconds=15)

        self._sync_real_registration()
        self._publish_status()

    def refresh_condition_snapshot(self) -> None:
        """조건식 스냅샷을 요청한다."""
        with self._condition_lock:
            if not self._condition_started: # 조건식이 아직 설정되지 않았으면
                self._try_setup_condition(retry_seconds=0) # 재시도 없이 설정 시도
            if not self._condition_started:
                return
            self._gateway.send_condition( # 조건식 스냅샷 요청
                screen=self._settings.condition_screen, # 조건식 스크린
                cond_name=self._condition_name, # 조건식 이름
                index=self._settings.condition_index, # 조건식 인덱스
                search=0,
            )

    def refresh_account_info_periodic(self) -> None:
        """계좌 예수금 정보를 주기적으로 갱신한다."""
        # 체결 후 강제 갱신 플래그가 설정되면 force=True로 갱신
        force = bool(getattr(self, "_force_account_refresh", False))
        if force:
            self._force_account_refresh = False
        self._refresh_account_info(force=force)
        self._refresh_holdings(force=force)
        # 감시 리스트 변경 시 실시간 등록 수행
        self._sync_real_registration()

    def refresh_holdings_now(self) -> None:
        """UI 요청으로 계좌/보유 정보를 즉시 새로고침한다."""
        self._logger.info("수동 보유 새로고침 요청")
        self._refresh_account_info(force=True)
        self._refresh_holdings(force=True)

    def process_condition_queues(self) -> None:
        """조건식 TR/실시간 큐를 처리한다."""
        updated = False
        while True:  # TR 조건식 큐 처리
            tr_data = self._gateway.get_tr_condition()
            if tr_data is None:
                break
            codes = set(tr_data.get("code_list", []))  # 조건식 일치 종목 코드 목록
            self._watchlist.apply_condition_snapshot(codes)  # 감시 리스트 갱신
            updated = True  # 상태 갱신 플래그 설정

        while True:
            real_data = self._gateway.get_real_condition()  # 실시간 조건식 큐 처리
            if real_data is None:
                break
            code = real_data.get("code", "")  # 종목 코드
            event_type = real_data.get("type", "")  # 이벤트 유형
            if code:
                self._watchlist.apply_condition_event(code, event_type)
                updated = True
        if updated:
            self._sync_real_registration()
            self._publish_status()
        self._flush_real_registration_if_due()

    def process_real_data_queue(self) -> None:
        """실시간 체결 큐를 빠르게 수신해 내부 큐로 전달한다."""
        real_fids = list(getattr(self._settings, "real_fids", []) or [])
        if not real_fids:
            self._logger.error("실시간 FID 설정이 부족합니다. real_fids를 확인하세요.")
            return
        price_fid = real_fids[0]
        volume_fid = real_fids[1] if len(real_fids) >= 2 else None
        time_fid = real_fids[2] if len(real_fids) >= 3 else None
        if not self._last_watchset and self._last_watchlist:
            self._last_watchset = set(self._last_watchlist)
        for data in self._drain_real_batch():
            tick = parse_tick(
                data,
                price_fid=price_fid,
                volume_fid=volume_fid,
                time_fid=time_fid,
                default_volume=0,
                default_time=self._clock.now().strftime("%H%M%S"),
            )
            if tick is None:
                continue
            if tick.code not in self._last_watchset:
                continue
            self._total_ticks_received += 1
            self._tick_counts[tick.code] = self._tick_counts.get(tick.code, 0) + 1
            self._last_tick_time[tick.code] = self._clock.now()
            self._last_prices[tick.code] = tick.price
            self._append_recent_tick(tick)
            if self._tick_counts[tick.code] == 1 and self._settings.tick_start_log_enabled:
                self._logger.info("틱 수신 시작: %s", self._get_name(tick.code))
            self._enqueue_tick(tick)
        self._log_tick_health()

    def _drain_real_batch(self) -> List[dict]:
        """게이트웨이에서 실시간 데이터를 배치 단위로 가져온다."""
        base_batch = max(1, int(getattr(self._settings, "real_ingress_drain_batch", 500)))
        drain_batch = base_batch
        ingress_size = 0
        if hasattr(self._gateway, "get_real_ingress_size"):
            try:
                ingress_size = int(self._gateway.get_real_ingress_size())
            except Exception:
                ingress_size = 0
        ingress_capacity = max(1, int(getattr(self._settings, "real_ingress_buffer_maxsize", 5000)))
        ingress_soft = int(ingress_capacity * float(getattr(self._settings, "real_ingress_soft_ratio", 0.80)))
        ingress_hard = int(ingress_capacity * float(getattr(self._settings, "real_ingress_hard_ratio", 0.95)))
        if ingress_size >= ingress_hard:
            drain_batch = max(base_batch * 4, base_batch + 200)
        elif ingress_size >= ingress_soft:
            drain_batch = max(base_batch * 2, base_batch + 100)

        if hasattr(self._gateway, "drain_real_data"):
            return list(self._gateway.drain_real_data(drain_batch))

        batch: List[dict] = []
        while len(batch) < drain_batch:
            data = self._gateway.get_real_data()
            if data is None:
                break
            batch.append(data)
        return batch

    def process_tick_compute_queue(self, shard_id: Optional[int] = None) -> None:
        """내부 틱 큐를 소비해 캔들/RSI/전략을 계산한다."""
        max_batch = max(1, int(getattr(self._settings, "tick_compute_batch_size", 1000)))
        for current_shard in self._resolve_shard_ids(shard_id):
            processed = 0
            tick_queue = self._tick_shard_queues[current_shard]
            while processed < max_batch:
                try:
                    tick = tick_queue.get_nowait()
                except queue.Empty:
                    break
                processed += 1
                self._total_ticks_processed += 1
                if tick.code not in self._last_watchset:
                    continue
                
                # 실시간 RSI 프리뷰 (UI용)
                with self._rsi_trackers_lock:
                    tracker = self._rsi_trackers.get(tick.code)
                if tracker:
                    preview_rsi = tracker.preview(tick.price)
                    if preview_rsi is not None:
                        self._last_rsi_values[tick.code] = preview_rsi

                lock = self._get_aggregator_lock_for(tick.code)
                with lock:
                    candle = self._aggregator.update(tick)
                if candle:
                    self._handle_candle(candle)
                self._evaluate_in_progress_candle(tick.code)
        self._flush_candles_by_clock()
        self._retry_pending_strategy_orders()

    def process_chejan_queue(self) -> None:
        """체결/잔고 큐를 처리한다."""
        # 날짜가 바뀌면 체결 중복방지 set을 초기화 (장기 실행 시 메모리 누수 방지)
        today = self._clock.now().date()
        if self._seen_executions_date != today:
            self._seen_executions.clear()
            self._seen_executions_date = today
        updated = False
        trade_updated = False
        execution_completed = False
        holdings_refreshed = False
        while True:
            data = self._gateway.get_chejan_data()
            if data is None:
                break
            # 원본 CHEJAN 이벤트를 디버그에 남겨 문제 재현/조사에 활용할 수 있게 함
            try:
                self._logger.debug("CHEJAN RAW: %s", data)
                if getattr(self, "_chejan_logger", None):
                    try:
                        self._chejan_logger.debug("%s", data)
                    except Exception:
                        pass
            except Exception:
                pass
            gubun = str(data.get("gubun", ""))
            if gubun == "0":
                execution = parse_order_event(data)
                if execution is None:
                    self._handle_strategy_order_status(data)
                    self._log_pending_order_status(data)
                    continue
                self._clear_pending_order_by_execution(execution)
                self._log_pending_order_status(data, execution=execution)
                name = execution.name or self._get_name(execution.code)
                self._logger.info(
                    "체결수신: %s %s %d주 @%s (잔량 %d)",
                    execution.side,
                    name,
                    execution.quantity,
                    f"{execution.price:,}",
                    execution.remaining_qty,
                )
                order_no = str(getattr(execution, "order_no", "") or "").strip()
                order_key = (
                    execution.code,
                    execution.side,
                    order_no if order_no else str(execution.time or ""),
                )
                if int(execution.order_qty) > 0 and int(execution.remaining_qty) >= 0:
                    filled_total = max(0, int(execution.order_qty) - int(execution.remaining_qty))
                else:
                    filled_total = int(execution.quantity)
                prev_filled = int(self._order_fill_snapshot.get(order_key, 0))
                if filled_total < prev_filled:
                    prev_filled = 0
                delta_qty = max(0, filled_total - prev_filled)
                if delta_qty > 0:
                    exec_key = (order_key, filled_total, int(execution.price))
                    if exec_key not in self._seen_executions:
                        self._daily_tracker.record(
                            code=execution.code,
                            side=execution.side,
                            qty=delta_qty,
                            price=execution.price,
                            name=name,
                            time=str(execution.time or ""),
                        )
                        self._seen_executions.add(exec_key)
                        trade_updated = True
                    else:
                        self._logger.debug("중복 체결 이벤트 무시: %s", exec_key)
                self._order_fill_snapshot[order_key] = max(prev_filled, filled_total)

                # 부분체결인 경우 추가 로깅 및 잔고 동기화를 수행
                if execution.remaining_qty > 0:
                    self._logger.info(
                        "부분체결: %s %s %d주 체결(잔량 %d)",
                        execution.side,
                        name,
                        execution.quantity,
                        execution.remaining_qty,
                    )
                # 체결 수신 시 서버 요청 대신 플래그만 설정하고, 주기적 갱신 스레드에서 처리
                # (메인 엔진 스레드 블로킹 방지)
                self._force_account_refresh = True
                if delta_qty > 0:
                    self._trade_logger.info("당일 매매 상세:\n%s", self._daily_tracker.details())
                if execution.remaining_qty == 0:
                    self._order_fill_snapshot.pop(order_key, None)
                    if execution.side == "SELL":
                        # 잔고 체결(gubun=1) 누락 시에도 보유 요약이 남지 않도록 체결수량만큼 즉시 차감한다.
                        current_qty = self._portfolio.get_qty(execution.code)
                        current_sellable = self._portfolio.get_sellable(execution.code)
                        current_avg = self._portfolio.get_avg_price(execution.code)
                        new_qty = max(0, current_qty - int(execution.quantity))
                        new_sellable = max(0, current_sellable - int(execution.quantity))
                        self._portfolio.update_position(
                            execution.code,
                            qty=new_qty,
                            sellable=new_sellable,
                            avg_price=current_avg,
                        )
                        # 체결 직후 TR 보유조회가 지연되어 과거 수량을 반환할 수 있어 짧은 시간 보호한다.
                        guard_until = self._clock.now() + datetime.timedelta(seconds=3)
                        self._sell_sync_guard[execution.code] = (new_qty, guard_until)
                        self._manual_sell_pending.pop(execution.code, None)
                        self._watchlist.update_holdings(self._portfolio.get_codes())
                        updated = True
                    self._logger.info(
                        "체결완료: %s %s %d주 @%s",
                        execution.side,
                        name,
                        execution.quantity,
                        f"{execution.price:,}",
                    )
                    execution_completed = True
                continue
            if gubun != "1":
                continue
            parsed = parse_balance_event(data)
            if parsed is None:
                continue
            code, qty, sellable, avg_price, current_price = parsed
            self._portfolio.update_position(code, qty, sellable, avg_price)
            if current_price > 0:
                self._last_prices[code] = current_price
            self._watchlist.update_holdings(self._portfolio.get_codes())
            # 실시간 등록은 주기적 갱신 스레드에서 처리하도록 통합 (블로킹 방지)
            updated = True
        if execution_completed:
            # 체결완료 후 강제 갱신 플래그 설정 (서버 동기화는 주기적 스레드에서)
            self._force_account_refresh = True
            self._publish_status()
        elif updated:
            self._publish_status()
        if trade_updated and not updated and not execution_completed:
            self._publish_status()
        self._flush_real_registration_if_due()

    def _handle_candle(self, candle: Candle) -> None:
        """캔들 완성 시 RSI 계산과 전략 판단을 수행한다."""
        # 종목별 락으로 RSi 트래커 접근을 보호하면 서로 다른 종목을 병렬로 처리 가능
        lock = self._get_aggregator_lock_for(candle.code)
        with lock:
            self._append_recent_candle(candle)
        with self._rsi_trackers_lock:
            tracker = self._rsi_trackers.get(candle.code)
            if tracker is None:
                tracker = RsiTracker(period=self._settings.rsi_period)
                self._rsi_trackers[candle.code] = tracker
            rsi = tracker.update(candle.close)
            if rsi is not None:
                self._last_rsi_values[candle.code] = rsi
                self._last_candle_end_time[candle.code] = str(candle.end_time or "")

        self._evaluate_strategy_for_candle(candle, rsi=rsi, strategy=self._strategy, is_preview=False)
        self._publish_status()

    def _evaluate_strategy_for_candle(
        self,
        candle: Candle,
        rsi: Optional[float],
        strategy,
        is_preview: bool,
        execute_orders: bool = True,
    ) -> None:
        """완성/진행 중 캔들에 대해 전략 신호를 계산하고 주문으로 연결한다."""
        strategy_requires_rsi = bool(getattr(strategy, "requires_rsi", True))
        if rsi is None and strategy_requires_rsi:
            return
        rsi_for_strategy = float(rsi) if rsi is not None else float(self._last_rsi_values.get(candle.code, 50.0))
        if rsi is not None and bool(getattr(self._settings, "rsi_trace_log_enabled", False)) and not is_preview:
            self._logger.info(
                "RSI 업데이트: %s close=%s end=%s rsi=%.2f period=%s",
                self._get_name(candle.code),
                candle.close,
                str(candle.end_time or "-"),
                rsi_for_strategy,
                int(getattr(self._settings, "rsi_period", 14)),
            )
        if rsi is not None and not is_preview:
            self._last_rsi = f"{self._get_name(candle.code)} RSI {rsi_for_strategy:.2f}"
        position_qty = self._portfolio.get_qty(candle.code)
        signals = strategy.on_rsi_update(
            candle.code,
            rsi_for_strategy,
            candle.close,
            position_qty,
            high=candle.high,
            low=candle.low,
        )
        candle_marker = self._build_candle_marker(candle)
        self._process_strategy_signals(
            signals=signals,
            candle=candle,
            rsi_for_strategy=rsi_for_strategy,
            candle_marker=candle_marker,
            is_preview=is_preview,
            execute_orders=execute_orders,
        )

    def _process_strategy_signals(
        self,
        signals: List[TradeSignal],
        candle: Candle,
        rsi_for_strategy: float,
        candle_marker: str,
        is_preview: bool,
        execute_orders: bool = True,
    ) -> None:
        """전략 신호를 중복 제어 후 실제 주문으로 전송한다."""
        for signal in signals:
            if not execute_orders:
                if bool(getattr(self._settings, "rsi_trace_log_enabled", False)):
                    self._logger.info(
                        "신호 생성(미리보기): %s %s qty=%s reason=%s rsi=%.2f close=%s candle_end=%s",
                        signal.side,
                        self._get_name(signal.code),
                        int(signal.quantity),
                        signal.reason,
                        rsi_for_strategy,
                        candle.close,
                        str(candle.end_time or "-"),
                    )
                continue
            if self._is_duplicate_strategy_signal(signal, candle_marker) or not self._try_claim_signal_marker(signal, candle_marker):
                self._logger.debug("중복 전략 신호 무시: %s %s %s", signal.code, signal.side, signal.tag or signal.reason)
                continue
            if bool(getattr(self._settings, "rsi_trace_log_enabled", False)):
                phase = "미리보기" if is_preview else "확정"
                self._logger.info(
                    "신호 생성(%s): %s %s qty=%s reason=%s rsi=%.2f close=%s candle_end=%s",
                    phase,
                    signal.side,
                    self._get_name(signal.code),
                    int(signal.quantity),
                    signal.reason,
                    rsi_for_strategy,
                    candle.close,
                    str(candle.end_time or "-"),
                )
            sent = self._execute_signal(signal, candle_end=candle_marker)
            if not sent:
                self._release_signal_marker(signal, candle_marker)

    def _should_execute_preview_orders(self, strategy) -> bool:
        """진행 중 캔들 미리보기에서 실제 주문 전송 여부를 반환한다."""
        source = str(getattr(self._settings, "candle_source", "tick")).lower()
        strategy_name = str(getattr(strategy, "name", self._strategy_name) or self._strategy_name).lower()
        if source == "minute" and strategy_name == "rsi_grid":
            return False
        return True

    def _evaluate_in_progress_candle(self, code: str) -> None:
        """진행 중 분봉 기준으로 전략 프리뷰를 수행한다."""
        if not isinstance(self._aggregator, TimeAggregator):
            return
        lock = self._get_aggregator_lock_for(code)
        with lock:
            current_candle = self._aggregator.get_current_candle(code)
        with self._rsi_trackers_lock:
            tracker = self._rsi_trackers.get(code)
        if current_candle is None:
            return
        preview_rsi = tracker.preview(current_candle.close) if tracker is not None else None
        try:
            preview_strategy = copy.deepcopy(self._strategy)
        except Exception:
            self._logger.debug("전략 프리뷰 복제 실패: %s", code)
            return
        execute_orders = self._should_execute_preview_orders(preview_strategy)
        self._evaluate_strategy_for_candle(
            current_candle,
            rsi=preview_rsi,
            strategy=preview_strategy,
            is_preview=True,
            execute_orders=execute_orders,
        )

    def _build_candle_marker(self, candle: Candle) -> str:
        """중복 주문 방지용 캔들 마커를 생성한다."""
        source = str(getattr(self._settings, "candle_source", "tick")).lower()
        if source == "minute":
            minutes = int(getattr(self._settings, "minutes_per_candle", 1))
            bucket = self._bucket_from_time_text(str(candle.end_time or ""), minutes)
            if bucket is not None:
                return f"minute:{minutes}:{bucket}"
        return str(candle.end_time or "")

    def _try_claim_signal_marker(self, signal: TradeSignal, candle_marker: str) -> bool:
        """동일 캔들에서 같은 의미의 신호를 원자적으로 한 번만 선점한다."""
        if not candle_marker:
            return True
        key = self._build_signal_marker_key(signal)
        with self._signal_marker_lock:
            if self._signal_markers.get(key) == candle_marker:
                return False
            self._signal_markers[key] = candle_marker
            return True

    def _release_signal_marker(self, signal: TradeSignal, candle_marker: str) -> None:
        """주문 전송 실패 시 선점한 신호 마커를 해제한다."""
        if not candle_marker:
            return
        key = self._build_signal_marker_key(signal)
        with self._signal_marker_lock:
            if self._signal_markers.get(key) == candle_marker:
                self._signal_markers.pop(key, None)

    def _build_signal_marker_key(self, signal: TradeSignal) -> tuple:
        """의미상 동일한 신호를 식별할 키를 만든다."""
        tag = str(getattr(signal, "tag", "") or "").strip()
        if tag:
            return (str(signal.code), str(signal.side).upper(), tag)
        normalized_reason = re.sub(r"\d+(?:\.\d+)?", "#", str(signal.reason or ""))
        normalized_reason = " ".join(normalized_reason.split())
        return (str(signal.code), str(signal.side).upper(), normalized_reason)

    @staticmethod
    def _bucket_from_time_text(time_text: str, minutes_per_candle: int) -> Optional[int]:
        """체결시각 문자열을 분봉 버킷 숫자로 변환한다."""
        digits = "".join([c for c in str(time_text or "") if c.isdigit()])
        if len(digits) < 4:
            return None
        digits = digits.zfill(6)
        try:
            hour = int(digits[0:2])
            minute = int(digits[2:4])
        except ValueError:
            return None
        total_minutes = hour * 60 + minute
        return (total_minutes // max(1, int(minutes_per_candle))) * max(1, int(minutes_per_candle))

    def _resolve_shard_ids(self, shard_id: Optional[int]) -> List[int]:
        """처리 대상 샤드 인덱스를 반환한다."""
        total = len(self._tick_shard_queues)
        if total <= 0:
            return []
        if shard_id is None:
            return list(range(total))
        try:
            parsed = int(shard_id)
        except (TypeError, ValueError):
            return list(range(total))
        if parsed < 0 or parsed >= total:
            return []
        return [parsed]

    @staticmethod
    def _stable_hash(text: str) -> int:
        """파이썬 런타임 seed에 영향받지 않는 안정 해시를 계산한다."""
        value = 0
        for ch in str(text):
            value = (value * 131 + ord(ch)) & 0x7FFFFFFF
        return value

    def _tick_shard_index(self, code: str) -> int:
        """코드별 샤드 인덱스를 반환한다."""
        count = max(1, len(self._tick_shard_queues))
        if count == 1:
            return 0
        return int(self._stable_hash(code) % count)

    def _flush_candles_by_clock(self) -> None:
        """분봉 모드에서 무틱 구간 경계 캔들을 시계 기준으로 확정한다."""
        if not isinstance(self._aggregator, TimeAggregator):
            return
        now_value = self._clock.now()
        with self._aggregator_lock:
            flushed = self._aggregator.flush_by_clock(now_value)
        for candle in flushed:
            self._logger.debug(
                "분봉 플러시 확정: %s O=%s H=%s L=%s C=%s V=%s T=%s",
                self._get_name(candle.code),
                candle.open,
                candle.high,
                candle.low,
                candle.close,
                candle.volume,
                str(candle.end_time or "-"),
            )
            self._handle_candle(candle)

    def _enqueue_tick(self, tick: Tick) -> None:
        """틱 데이터를 샤드 큐에 넣고 과부하 시 hybrid 정책을 적용한다."""
        shard = self._tick_shard_index(tick.code)
        tick_queue = self._tick_shard_queues[shard]
        if self._queue_policy_mode != "hybrid":
            self._enqueue_tick_legacy_drop_oldest(tick_queue, tick, shard)
            return

        qmax = int(getattr(tick_queue, "maxsize", 0) or 0)
        qsize = tick_queue.qsize()
        ratio = (float(qsize) / float(qmax)) if qmax > 0 else 0.0
        if qmax > 0 and ratio >= self._tick_queue_hard_ratio:
            soft_mark = max(0, int(qmax * self._tick_queue_soft_ratio))
            drop_to_soft = max(0, qsize - soft_mark + 1)
            dropped = self._drop_oldest_from_queue(
                tick_queue,
                max_items=max(self._tick_queue_emergency_drop_batch, drop_to_soft),
            )
            if dropped > 0:
                self._tick_emergency_drop_count += dropped
                self._tick_drop_count += dropped
                self._tick_shard_drop_counts[shard] += dropped
                qsize = tick_queue.qsize()
                ratio = float(qsize) / float(qmax)
                self._log_tick_drop_once(shard=shard, queue_size=qsize, dropped=dropped, emergency=True)

        try:
            if ratio < self._tick_queue_soft_ratio:
                tick_queue.put_nowait(tick)
                self._tick_shard_peak_sizes[shard] = max(self._tick_shard_peak_sizes[shard], tick_queue.qsize())
                return
            wait_sec = self._tick_queue_overload_wait_sec
            if wait_sec > 0:
                tick_queue.put(tick, timeout=wait_sec)
                self._tick_shard_peak_sizes[shard] = max(self._tick_shard_peak_sizes[shard], tick_queue.qsize())
                self._log_tick_backpressure_once(shard=shard, ratio=ratio, wait_sec=wait_sec)
                return
            tick_queue.put_nowait(tick)
            self._tick_shard_peak_sizes[shard] = max(self._tick_shard_peak_sizes[shard], tick_queue.qsize())
            return
        except queue.Full:
            pass

        # 동시성 경합 등으로 put 시점에 가득 찬 경우에도 최신 틱을 우선 반영한다.
        current_ratio = ratio
        if qmax > 0:
            try:
                current_ratio = float(tick_queue.qsize()) / float(qmax)
            except Exception:
                current_ratio = ratio
        if current_ratio >= self._tick_queue_hard_ratio:
            current_size = tick_queue.qsize()
            soft_mark = max(0, int(qmax * self._tick_queue_soft_ratio)) if qmax > 0 else 0
            drop_to_soft = max(0, current_size - soft_mark + 1)
            dropped = self._drop_oldest_from_queue(
                tick_queue,
                max_items=max(self._tick_queue_emergency_drop_batch, drop_to_soft),
            )
            if dropped > 0:
                self._tick_emergency_drop_count += dropped
                self._tick_drop_count += dropped
                self._tick_shard_drop_counts[shard] += dropped
                self._log_tick_drop_once(shard=shard, queue_size=tick_queue.qsize(), dropped=dropped, emergency=True)
        try:
            tick_queue.put_nowait(tick)
            self._tick_shard_peak_sizes[shard] = max(self._tick_shard_peak_sizes[shard], tick_queue.qsize())
            return
        except queue.Full:
            self._tick_drop_count += 1
            self._tick_shard_drop_counts[shard] += 1
            self._log_tick_drop_once(shard=shard, queue_size=tick_queue.qsize(), dropped=1, emergency=False)

    @staticmethod
    def _drop_oldest_from_queue(target_queue: queue.Queue, max_items: int) -> int:
        """queue에서 오래된 항목을 최대 max_items개 제거하고 개수를 반환한다."""
        dropped = 0
        limit = max(0, int(max_items))
        while dropped < limit:
            try:
                target_queue.get_nowait()
            except queue.Empty:
                break
            dropped += 1
        return dropped

    def _enqueue_tick_legacy_drop_oldest(self, tick_queue: queue.Queue, tick: Tick, shard: int) -> None:
        """기존 단일 큐 방식(가득 차면 oldest 1건 제거)을 유지한다."""
        try:
            tick_queue.put_nowait(tick)
            self._tick_shard_peak_sizes[shard] = max(self._tick_shard_peak_sizes[shard], tick_queue.qsize())
            return
        except queue.Full:
            pass
        # 큐가 가득 찬 경우: 오래된 틱 1건 제거 후 재시도
        try:
            tick_queue.get_nowait()
        except queue.Empty:
            return
        # 오래된 틱 1건을 드롭했으므로 카운트 증가
        self._tick_drop_count += 1
        self._tick_shard_drop_counts[shard] += 1
        try:
            tick_queue.put_nowait(tick)
            self._tick_shard_peak_sizes[shard] = max(self._tick_shard_peak_sizes[shard], tick_queue.qsize())
        except queue.Full:
            self._log_tick_drop_once(shard=shard, queue_size=tick_queue.qsize(), dropped=1, emergency=True)
            return
        self._log_tick_drop_once(shard=shard, queue_size=tick_queue.qsize(), dropped=1, emergency=True)

    def _log_tick_backpressure_once(self, shard: int, ratio: float, wait_sec: float) -> None:
        """백프레셔 적용 로그를 주기적으로 남긴다."""
        now = self._clock.now()
        if self._last_tick_backpressure_log is None or (now - self._last_tick_backpressure_log).total_seconds() >= 5.0:
            self._logger.warning(
                "틱 큐 백프레셔: shard=%d 사용률=%.0f%% 대기=%.1fms",
                shard,
                ratio * 100.0,
                wait_sec * 1000.0,
            )
            self._last_tick_backpressure_log = now

    def _log_tick_drop_once(self, shard: int, queue_size: int, dropped: int, emergency: bool) -> None:
        """틱 드롭 로그를 주기적으로 남긴다."""
        now = self._clock.now()
        if self._last_tick_drop_log is None or (now - self._last_tick_drop_log).total_seconds() >= 5.0:
            mode = "긴급드롭" if emergency else "신규틱폐기"
            self._logger.warning(
                "틱 큐 적체: %s shard=%d 이번=%d 누적=%d 큐크기=%d",
                mode,
                shard,
                dropped,
                self._tick_drop_count,
                queue_size,
            )
            self._last_tick_drop_log = now

    def _append_recent_candle(self, candle: Candle) -> None:
        """RSI 워밍업에 사용할 최근 캔들 히스토리를 유지한다."""
        buffer = self._recent_candles_by_code.get(candle.code)
        if buffer is None:
            buffer = deque(maxlen=self._recent_tick_buffer_size)
            self._recent_candles_by_code[candle.code] = buffer
        buffer.append(candle)

    def _append_recent_tick(self, tick: Tick) -> None:
        """분봉 전환 시 RSI 워밍업에 사용할 최근 틱 기반 캔들을 구성한다."""
        if str(getattr(self._settings, "candle_source", "tick")).lower() == "tick":
            minute_candle = self._recent_minute_aggregator.update(tick)
            if minute_candle is not None:
                minute_buffer = self._recent_minute_candles_by_code.get(minute_candle.code)
                if minute_buffer is None:
                    minute_buffer = deque(maxlen=self._recent_tick_buffer_size)
                    self._recent_minute_candles_by_code[minute_candle.code] = minute_buffer
                minute_buffer.append(minute_candle)
                if self._minute_backfill_candle_count > 0:
                    while len(minute_buffer) > self._minute_backfill_candle_count:
                        minute_buffer.popleft()
        candle = self._recent_tick_aggregator.update(tick)
        if candle is None:
            return
        buffer = self._recent_candles_by_code.get(candle.code)
        if buffer is None:
            buffer = deque(maxlen=self._recent_tick_buffer_size)
            self._recent_candles_by_code[candle.code] = buffer
        buffer.append(candle)
        if self._minute_backfill_candle_count > 0:
            while len(buffer) > self._minute_backfill_candle_count:
                buffer.popleft()

    def _get_aggregator_lock_for(self, code: str) -> threading.Lock:
        """종목별로 고유한 락을 반환한다(없으면 생성).

        이렇게 하면 서로 다른 종목에 대한 aggregator 업데이트는 동시에 수행할 수 있어
        멀티스레드 환경에서 처리량을 높일 수 있다.
        """
        if isinstance(self._aggregator, TimeAggregator):
            # 분봉 집계기는 내부 상태 dict를 전체 코드가 공유하므로 단일 락으로 보호한다.
            return self._aggregator_lock
        if not code:
            return self._aggregator_lock
        with self._aggregator_locks_lock:
            lock = self._aggregator_locks.get(code)
            if lock is None:
                lock = threading.Lock()
                self._aggregator_locks[code] = lock
            return lock

    @staticmethod
    def _parse_signal_stage(tag: str) -> Optional[int]:
        """신호 태그에서 피라미딩 단계 번호를 파싱한다."""
        if not tag:
            return None
        match = re.search(r"STAGE_(\d+)", str(tag))
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    def _is_strategy_retry_target(self, signal: TradeSignal) -> bool:
        """전략 미체결 재시도 대상 신호인지 확인한다."""
        tag = str(getattr(signal, "tag", "") or "")
        if not tag.startswith("livermore:"):
            return False
        if str(signal.side).upper() != "BUY":
            return False
        return self._parse_signal_stage(tag) is not None

    def _build_strategy_pending_key(self, signal: TradeSignal, candle_end: str) -> Optional[tuple]:
        """전략 신호의 중복/재시도 추적 키를 생성한다."""
        stage = self._parse_signal_stage(getattr(signal, "tag", ""))
        if stage is None:
            return None
        strategy_name = str(getattr(self._strategy, "name", self._strategy_name) or self._strategy_name)
        return (str(signal.code), strategy_name, int(stage), str(candle_end or ""))

    def _is_duplicate_strategy_signal(self, signal: TradeSignal, candle_end: str) -> bool:
        """동일 캔들에서 이미 전송한 단계 신호인지 확인한다."""
        if not self._is_strategy_retry_target(signal):
            return False
        key = self._build_strategy_pending_key(signal, candle_end)
        if key is None:
            return False
        with self._strategy_pending_lock:
            return key in self._strategy_pending_orders

    def _register_strategy_pending_order(self, signal: TradeSignal, qty: int, candle_end: str) -> None:
        """전송한 전략 주문을 미체결 재시도 대상으로 등록한다."""
        if not self._is_strategy_retry_target(signal):
            return
        key = self._build_strategy_pending_key(signal, candle_end)
        if key is None:
            return
        with self._strategy_pending_lock:
            self._strategy_pending_orders[key] = {
                "signal": signal,
                "qty": int(qty),
                "sent_at": self._clock.now(),
                "retry_count": 0,
                "candle_end": str(candle_end or ""),
                "stage": key[2],
                "partial_fill": False,
                "retry_disabled": False,
                "partial_fill_at": None,
                "partial_fill_price": None,
                "accepted": False,
                "accepted_at": None,
            }

    def _retry_pending_strategy_orders(self) -> None:
        """미체결 전략 주문을 타임아웃 기준으로 재전송한다."""
        if not self._strategy_retry_lock.acquire(blocking=False):
            return
        try:
            with self._strategy_pending_lock:
                items = list(self._strategy_pending_orders.items())
            if not items:
                return
            now = self._clock.now()
            for key, state in items:
                try:
                    signal = state.get("signal")
                    if not isinstance(signal, TradeSignal):
                        with self._strategy_pending_lock:
                            self._strategy_pending_orders.pop(key, None)
                        continue
                    stage = int(state.get("stage", -1))
                    if bool(state.get("partial_fill")):
                        partial_at = state.get("partial_fill_at")
                        if isinstance(partial_at, datetime.datetime):
                            elapsed_partial = (now - partial_at).total_seconds()
                            if elapsed_partial >= self._strategy_retry_timeout_sec:
                                with self._strategy_pending_lock:
                                    cleared = self._strategy_pending_orders.pop(key, None)
                                if cleared and hasattr(self._strategy, "on_order_filled"):
                                    try:
                                        price = float(cleared.get("partial_fill_price") or 0.0)
                                        if price <= 0:
                                            price = float(getattr(signal, "price", 0) or 0.0)
                                        self._strategy.on_order_filled(
                                            signal.code,
                                            "BUY",
                                            stage=stage,
                                            price=price,
                                        )
                                    except Exception:
                                        self._logger.exception("부분체결 보정 콜백 실패: %s", signal.code)
                                continue
                        continue
                    if bool(state.get("retry_disabled")):
                        continue
                    sent_at = state.get("sent_at")
                    if not isinstance(sent_at, datetime.datetime):
                        continue
                    elapsed = (now - sent_at).total_seconds()
                    if elapsed < self._strategy_retry_timeout_sec:
                        continue
                    retry_count = int(state.get("retry_count", 0))
                    if retry_count >= self._strategy_retry_max:
                        self._logger.info(
                            "전략 주문 재시도 종료: %s stage=%s retry=%s",
                            self._get_name(signal.code),
                            stage,
                            retry_count,
                        )
                        with self._strategy_pending_lock:
                            self._strategy_pending_orders.pop(key, None)
                        if hasattr(self._strategy, "on_order_retry_exhausted"):
                            try:
                                self._strategy.on_order_retry_exhausted(signal.code, stage)
                            except Exception:
                                self._logger.exception("전략 재시도 종료 콜백 실패: %s", signal.code)
                        continue
                    sent = self._execute_signal(signal, candle_end=str(state.get("candle_end", "")), track_pending=False)
                    if not sent:
                        continue
                    retry_count += 1
                    with self._strategy_pending_lock:
                        current = self._strategy_pending_orders.get(key)
                        if current is None:
                            continue
                        current["retry_count"] = retry_count
                        current["sent_at"] = now
                    self._logger.info(
                        "전략 주문 재시도: %s stage=%s RETRY_%s",
                        self._get_name(signal.code),
                        stage,
                        retry_count,
                    )
                    if hasattr(self._strategy, "on_order_retry"):
                        try:
                            self._strategy.on_order_retry(signal.code, stage)
                        except Exception:
                            self._logger.exception("전략 재시도 콜백 실패: %s", signal.code)
                except Exception:
                    self._logger.exception("전략 주문 재시도 처리 실패: %s", key)
        finally:
            self._strategy_retry_lock.release()

    def _clear_pending_order_by_execution(self, execution) -> None:
        """체결 이벤트를 기준으로 전략 미체결 재시도 상태를 정리한다."""
        with self._strategy_pending_lock:
            if not self._strategy_pending_orders:
                return
        side = str(getattr(execution, "side", "")).upper()
        code = str(getattr(execution, "code", ""))
        if not code:
            return
        with self._strategy_pending_lock:
            matches = [k for k in self._strategy_pending_orders.keys() if k[0] == code]
        if not matches:
            return
        remaining_qty = int(getattr(execution, "remaining_qty", 0) or 0)
        if side == "BUY":
            # 동일 종목 BUY 체결 시 가장 오래된 단계 pending 1건만 해제
            matches.sort(key=lambda k: (str(k[3]), int(k[2])))
            key = matches[0]
            if remaining_qty > 0:
                with self._strategy_pending_lock:
                    state = self._strategy_pending_orders.get(key)
                    if state is not None:
                        state["partial_fill"] = True
                        state["retry_disabled"] = True
                        state["partial_fill_at"] = self._clock.now()
                        state["partial_fill_price"] = float(getattr(execution, "price", 0) or 0)
                return
            with self._strategy_pending_lock:
                state = self._strategy_pending_orders.pop(key, None)
            if state and hasattr(self._strategy, "on_order_filled"):
                try:
                    self._strategy.on_order_filled(
                        code,
                        "BUY",
                        stage=int(key[2]),
                        price=float(getattr(execution, "price", 0) or 0),
                    )
                except Exception:
                    self._logger.exception("전략 BUY 체결 콜백 실패: %s", code)
            return
        if side == "SELL":
            with self._strategy_pending_lock:
                for key in matches:
                    self._strategy_pending_orders.pop(key, None)
            if hasattr(self._strategy, "on_order_filled"):
                try:
                    self._strategy.on_order_filled(
                        code,
                        "SELL",
                        stage=None,
                        price=float(getattr(execution, "price", 0) or 0),
                    )
                except Exception:
                    self._logger.exception("전략 SELL 체결 콜백 실패: %s", code)

    def _handle_strategy_order_status(self, data: dict) -> None:
        """체결이 아닌 주문 상태 이벤트를 반영해 재시도/정리를 제어한다."""
        status = str(self._chejan_field(data, "913") or "").strip()
        if not status:
            return
        code = self._normalize_chejan_code(data)
        if not code:
            return
        side_raw = clean_int(self._chejan_field(data, "907"))
        side = "SELL" if side_raw == 1 else "BUY" if side_raw == 2 else ""
        if side != "BUY":
            return
        if "거부" in status or "취소" in status:
            self._clear_pending_order_by_reject(code)
            return
        if "접수" in status or "확인" in status:
            self._mark_pending_order_acknowledged(code)

    def _mark_pending_order_acknowledged(self, code: str) -> None:
        """주문 접수/확인 상태를 받은 BUY pending은 추가 재전송하지 않는다."""
        if not code:
            return
        with self._strategy_pending_lock:
            matches = [k for k in self._strategy_pending_orders.keys() if k[0] == code]
            if not matches:
                return
            matches.sort(key=lambda k: (str(k[3]), int(k[2])))
            key = matches[0]
            state = self._strategy_pending_orders.get(key)
            if state is None:
                return
            state["accepted"] = True
            state["accepted_at"] = self._clock.now()
            state["retry_disabled"] = True

    def _clear_pending_order_by_reject(self, code: str) -> None:
        """주문 거부/취소 시 BUY pending을 해제하고 전략 상태를 정리한다."""
        if not code:
            return
        with self._strategy_pending_lock:
            matches = [k for k in self._strategy_pending_orders.keys() if k[0] == code]
        if not matches:
            return
        matches.sort(key=lambda k: (str(k[3]), int(k[2])))
        key = matches[0]
        with self._strategy_pending_lock:
            self._strategy_pending_orders.pop(key, None)
        if hasattr(self._strategy, "on_order_retry_exhausted"):
            try:
                self._strategy.on_order_retry_exhausted(code, int(key[2]))
            except Exception:
                self._logger.exception("전략 주문 거부 정리 실패: %s", code)

    def _execute_signal(
        self,
        signal: TradeSignal,
        allow_excluded: bool = False,
        candle_end: str = "",
        track_pending: bool = True,
    ) -> bool:
        """전략 신호를 주문으로 전환한다."""
        def clear_strategy_pending_on_fail() -> None:
            if not self._is_strategy_retry_target(signal):
                return
            stage = self._parse_signal_stage(getattr(signal, "tag", ""))
            if stage is None:
                return
            if hasattr(self._strategy, "on_order_retry_exhausted"):
                try:
                    self._strategy.on_order_retry_exhausted(signal.code, stage)
                except Exception:
                    self._logger.exception("전략 실패 정리 콜백 실패: %s", signal.code)

        if not self._allow_trading:
            self._logger.warning("주문 차단 상태: %s", signal)
            clear_strategy_pending_on_fail()
            return False
        if not allow_excluded and self._is_excluded_code(signal.code):
            self._logger.info("제외 종목 주문 차단: %s (%s)", self._get_name(signal.code), signal.reason)
            clear_strategy_pending_on_fail()
            return False
        if not self._account_no:
            self._logger.error("계좌 번호가 없어 주문을 중단합니다.")
            clear_strategy_pending_on_fail()
            return False
        # 시장가 주문도 수량 산정을 위해 기준가격(참고가)은 계산한다.
        ref_price = self._resolve_order_price(signal)
        if ref_price <= 0:
            self._logger.warning("주문 가격 계산 실패: %s", signal.code)
            clear_strategy_pending_on_fail()
            return False
        qty = int(signal.quantity)
        if signal.side == "BUY":
            qty = self._resolve_buy_quantity(signal, ref_price)
        else:
            sellable = self._portfolio.get_sellable(signal.code)
            if sellable > 0:
                qty = min(qty, sellable)
            else:
                held_qty = self._portfolio.get_qty(signal.code)
                if held_qty > 0:
                    qty = min(qty, held_qty)
        if qty <= 0:
            clear_strategy_pending_on_fail()
            return False

        order_type = 1 if signal.side == "BUY" else 2
        hoga_gb = "03"  # 시장가
        order_price = 0
        try:
            self._gateway.send_order(
                rqname="rsi_trade",
                screen=self._settings.order_screen,
                acc_no=self._account_no,
                order_type=order_type,
                code=signal.code,
                quantity=qty,
                price=order_price,
                hoga_gb=hoga_gb,
                order_no="",
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.error("주문 전송 실패: %s %s (%s)", signal.side, self._get_name(signal.code), exc)
            clear_strategy_pending_on_fail()
            return False
        name = self._get_name(signal.code)
        self._last_signal = f"{signal.side} {name} {qty} @ 시장가 ({signal.reason})"
        self._logger.info("주문 전송: %s", self._last_signal)
        if track_pending:
            self._register_strategy_pending_order(signal, qty=qty, candle_end=candle_end)
        return True

    def _resolve_buy_quantity(self, signal: TradeSignal, order_price: int) -> int:
        """매수 모드 설정에 따라 최종 주문 수량을 계산한다."""
        # 전략이 직접 수량을 계산한 경우(예: Livermore 피라미딩)는 신호 수량을 우선한다.
        tag = str(getattr(signal, "tag", "") or "")
        if tag.startswith("livermore:"):
            return max(0, int(signal.quantity))
        mode = str(getattr(self._settings, "buy_size_mode", "cash") or "cash").lower()
        if mode == "qty":
            fixed_qty = int(getattr(self._settings, "buy_qty", 0))
            if fixed_qty > 0:
                return fixed_qty
            return max(0, int(signal.quantity))
        cash = int(getattr(self._settings, "buy_cash", 0))
        if cash > 0 and order_price > 0:
            return self._order_sizer.buy_quantity(cash, order_price)
        return max(0, int(signal.quantity))

    def _resolve_order_price(self, signal: TradeSignal) -> int:
        """신호별 주문 기준가를 +5/-5호가로 계산한다."""
        # 최신 틱 가격을 우선 사용해 주문 기준가를 계산한다.
        base_price = int(self._last_prices.get(signal.code, 0))
        if base_price <= 0:
            base_price = int(signal.price)
        if base_price <= 0:
            base_price = int(self._portfolio.get_avg_price(signal.code))
        if base_price <= 0:
            return 0
        offset = int(getattr(self._settings, "order_hoga_offset_levels", 5))
        if offset <= 0:
            return base_price
        steps = offset if signal.side == "BUY" else -offset
        return self._shift_price_by_hoga(base_price, steps)

    def _shift_price_by_hoga(self, base_price: int, steps: int) -> int:
        """호가 단위 기준으로 가격을 단계 이동한다."""
        price = max(1, int(base_price))
        if steps == 0:
            return price
        if steps > 0:
            for _ in range(steps):
                price += self._get_hoga_unit(price)
            return price
        for _ in range(-steps):
            unit = self._get_hoga_unit(price)
            price = max(unit, price - unit)
        return price

    @staticmethod
    def _get_hoga_unit(price: int) -> int:
        """가격대별 호가 단위를 반환한다."""
        if price < 2_000:
            return 1
        if price < 5_000:
            return 5
        if price < 20_000:
            return 10
        if price < 50_000:
            return 50
        if price < 200_000:
            return 100
        if price < 500_000:
            return 500
        return 1_000

    def sell_all(self, code: str) -> None:
        """UI 요청으로 전량 매도한다."""
        if not code:
            return
        if self._is_excluded_code(code):
            self._logger.info("제외 종목 전량매도 차단: %s", self._get_name(code))
            return
        cached_sellable = self._portfolio.get_sellable(code)
        cached_qty = self._portfolio.get_qty(code)
        cached_avg_price = self._portfolio.get_avg_price(code)
        self._refresh_holdings_for_manual_sell()
        sellable = self._portfolio.get_sellable(code)
        qty = sellable if sellable > 0 else self._portfolio.get_qty(code)
        self._logger.info(
            "전량 매도 수량 판단: %s TR수량=%d TR매도가능=%d 캐시수량=%d 캐시매도가능=%d",
            self._get_name(code),
            self._portfolio.get_qty(code),
            sellable,
            cached_qty,
            cached_sellable,
        )
        # 보유조회(TR)가 일시적으로 비어도 직전 보유 수량으로 전량매도를 시도한다.
        if qty <= 0 and (cached_sellable > 0 or cached_qty > 0):
            qty = cached_sellable if cached_sellable > 0 else cached_qty
            self._logger.warning(
                "전량 매도 보정: 보유조회 공백으로 캐시 수량 사용 (%s, %d주)",
                self._get_name(code),
                qty,
            )
        if qty <= 0:
            self._logger.info("전량 매도 실패: 보유수량 없음 (%s)", self._get_name(code))
            return
        signal = TradeSignal(
            code=code,
            side="SELL",
            quantity=qty,
            reason="UI 전량매도",
            price=self._last_prices.get(code, 0) or cached_avg_price,
        )
        sent = self._execute_signal(signal)
        if sent:
            self._manual_sell_pending[code] = {
                "requested_qty": int(qty),
                "requested_at": self._clock.now(),
                "last_trace_at": None,
                "timeout_logged": False,
            }

    def _refresh_holdings_for_manual_sell(self) -> None:
        """수동 매도 전에 보유 종목을 최신화한다."""
        force_min_interval = float(getattr(self._settings, "holdings_force_min_interval_sec", 2.0))
        now = self._clock.now()
        force_refresh = True
        if self._last_holdings_refresh:
            if (now - self._last_holdings_refresh).total_seconds() < force_min_interval:
                force_refresh = False
        self._refresh_holdings(force=force_refresh)

    def change_condition_index(self, index: int) -> None:
        """조건식 인덱스를 변경한다."""
        with self._condition_lock:
            try:
                new_index = int(index)
            except (TypeError, ValueError):
                self._logger.error("조건식 인덱스가 숫자가 아닙니다: %s", index)
                return
            if new_index == self._settings.condition_index:
                return
            cond_map = self._load_condition_list(retry_seconds=0)
            new_name = cond_map.get(new_index, "")
            if not new_name:
                self._logger.error("조건식 인덱스 %s를 찾지 못했습니다.", new_index)
                return
            old_index = self._settings.condition_index
            old_name = self._condition_name or "-"
            self._logger.info("조건식 변경: %s(%s) -> %s(%s)", old_name, old_index, new_name, new_index)
            if self._condition_started and self._condition_name:
                self._gateway.stop_condition(
                    screen=self._settings.condition_screen,
                    cond_name=self._condition_name,
                    index=self._settings.condition_index,
                )
            self._settings.condition_index = new_index
            self._condition_started = False
            self._condition_name = new_name
            self._condition_log_emitted = False
            self._watchlist.reset_conditions()
            self._sync_real_registration()
            self._try_setup_condition(retry_seconds=0)
            self._bump_ui_version("condition")
            self._publish_status()

    def refresh_condition_list(self) -> None:
        """조건식 목록을 다시 로드한다."""
        with self._condition_lock:
            cond_map = self._load_condition_list(retry_seconds=0)
            if not cond_map:
                self._publish_status()
                return
            changed = False
            current_index = self._settings.condition_index
            new_name = cond_map.get(current_index, "")
            if new_name:
                if new_name != self._condition_name:
                    old_name = self._condition_name or "-"
                    if self._condition_started and old_name != "-":
                        self._gateway.stop_condition(
                            screen=self._settings.condition_screen,
                            cond_name=old_name,
                            index=current_index,
                        )
                    self._condition_name = new_name
                    self._gateway.send_condition(
                        screen=self._settings.condition_screen,
                        cond_name=new_name,
                        index=current_index,
                        search=1,
                    )
                    self._condition_started = True
                    self._logger.info("조건식 갱신: %s(%s) -> %s(%s)", old_name, current_index, new_name, current_index)
                    changed = True
                self._logger.info("조건식 목록 재수신 완료")
                if changed:
                    self._bump_ui_version("condition")
                self._publish_status()
                return

            current_name = self._condition_name or ""
            if current_name:
                matched_index = None
                for idx, name in cond_map.items():
                    if name == current_name:
                        matched_index = idx
                        break
                if matched_index is not None and matched_index != current_index:
                    self._logger.info(
                        "조건식 인덱스 갱신: %s(%s) -> %s(%s)",
                        current_name,
                        current_index,
                        current_name,
                        matched_index,
                    )
                    if self._condition_started:
                        self._gateway.stop_condition(
                            screen=self._settings.condition_screen,
                            cond_name=current_name,
                            index=current_index,
                        )
                    self._settings.condition_index = matched_index
                    self._condition_name = current_name
                    self._condition_started = False
                    self._condition_log_emitted = False
                    self._watchlist.reset_conditions()
                    self._sync_real_registration()
                    self._gateway.send_condition(
                        screen=self._settings.condition_screen,
                        cond_name=current_name,
                        index=matched_index,
                        search=1,
                    )
                    self._condition_started = True
                    self._logger.info("조건식 갱신: %s(%s)", current_name, matched_index)
                    self._logger.info("조건식 목록 재수신 완료")
                    self._bump_ui_version("condition")
                    self._publish_status()
                    return
            self._logger.info("조건식 목록 재수신 완료")
            self._publish_status()

    def change_strategy(self, strategy_name: str) -> None:
        """매매 전략을 변경한다."""
        if not strategy_name:
            return
        if strategy_name == self._strategy_name:
            return
        names = [item["name"] for item in self._strategy_items]
        if strategy_name not in names:
            self._logger.error("알 수 없는 전략: %s", strategy_name)
            return
        self._logger.info("전략 변경: %s -> %s", self._strategy_name, strategy_name)
        self._rebuild_strategy(strategy_name)
        self._bump_ui_version("strategy")
        self._publish_status()

    def _rebuild_strategy(self, strategy_name: Optional[str] = None) -> None:
        """현재 설정값 기준으로 전략 인스턴스를 다시 생성한다."""
        target_name = strategy_name or self._strategy_name
        cooldown = CooldownTracker(seconds=self._settings.cooldown_seconds, clock=self._clock)
        market_hours = MarketHours(
            start=self._settings.market_start,
            end=self._settings.market_end,
            timezone=self._settings.market_timezone,
        )
        strategy = create_strategy(
            target_name,
            self._settings,
            cooldown,
            self._order_sizer,
            market_hours,
        )
        actual_name = str(getattr(strategy, "name", "") or target_name)
        if actual_name != target_name:
            self._logger.warning(
                "전략 생성 이름 불일치: 요청=%s 실제=%s",
                target_name,
                actual_name,
            )
        self._strategy = strategy
        self._strategy_name = actual_name
        with self._strategy_pending_lock:
            self._strategy_pending_orders.clear()
        self._logger.info("전략 적용 완료: %s (%s)", self._strategy_name, self._strategy.__class__.__name__)
        for code in self._watchlist.get_tracked_codes():
            self._strategy.reset_code(code)

    def change_candle_config(self, source: str, value: int) -> None:
        """캔들 기준을 변경한다."""
        source = str(source or "").lower()
        if source not in ("tick", "minute"):
            self._logger.error("알 수 없는 캔들 소스: %s", source)
            return
        if value <= 0:
            self._logger.error("캔들 설정 값이 0 이하입니다: %s", value)
            return
        
        # 기존 rsi_period 저장
        prev_rsi_period = self._settings.rsi_period
        
        seeded_rsi_count = 0
        with self._aggregator_lock:
            if source == "minute":
                self._settings.candle_source = "minute"
                self._settings.minutes_per_candle = int(value)
                self._apply_minute_defaults()
                self._aggregator = TimeAggregator(minutes_per_candle=int(value))
                label = f"{value}분봉"
            else:
                self._settings.candle_source = "tick"
                self._settings.ticks_per_candle = int(value)
                # Restore tick defaults when switching to tick-based candles.
                self._apply_tick_defaults()
                self._aggregator = TickAggregator(ticks_per_candle=int(value))
                label = f"{value}틱봉"
            with self._rsi_trackers_lock:
                self._rsi_trackers.clear()
                self._last_rsi_values.clear()
            if source == "minute":
                seeded_rsi_count = self._seed_history_from_recent_ticks()
        self._last_rsi = "-"
        # Rebuild strategy to pick up any RSI default changes for both modes.
        self._rebuild_strategy(self._strategy_name)
        self._logger.info("캔들 기준 변경: %s", label)
        if source == "minute":
            self._logger.info(
                "분봉 기본값 적용: RSI 기간 %d, 과매수 %.1f, 부분매도 %.1f, 전량매도 %.1f, 틱 백필 %d틱 x %d봉 (적용 %d종목)",
                self._settings.rsi_period,
                self._settings.rsi_overbought,
                self._settings.rsi_sell_half,
                self._settings.rsi_sell_all,
                int(getattr(self._settings, "minute_backfill_tick_size", 20)),
                int(getattr(self._settings, "minute_backfill_candle_count", 20)),
                seeded_rsi_count,
            )
        else:
            self._logger.info(
                "틱봉 기본값 복원: RSI 기간 %d, 과매수 %.1f, 부분매도 %.1f, 전량매도 %.1f",
                self._settings.rsi_period,
                self._settings.rsi_overbought,
                self._settings.rsi_sell_half,
                self._settings.rsi_sell_all,
            )
        self._bump_ui_version("candle")
        # 실제로 rsi_period가 변경된 경우에만 bump
        if self._settings.rsi_period != prev_rsi_period:
            self._bump_ui_version("rsi_period")
        self._publish_status()

    def _apply_minute_defaults(self) -> None:
        """분봉 전환 시 사용할 RSI 및 리버모어 캔들 수 기본값을 적용한다."""
        # 분봉 모드 기본값 사용 (별도로 저장된 값)
        self._settings.rsi_period = getattr(self._settings, "minute_default_rsi_period", 8)
        self._settings.rsi_overbought = getattr(self._settings, "minute_default_rsi_overbought", 70.0)
        self._settings.rsi_sell_half = getattr(self._settings, "minute_default_rsi_sell_half", 59.0)
        self._settings.rsi_sell_all = getattr(self._settings, "minute_default_rsi_sell_all", 39.0)
        
        lv_period = getattr(self._settings, "minute_default_livermore_period", 8)
        self._settings.livermore_breakout_period = lv_period
        self._settings.livermore_exit_period = lv_period

    def _apply_tick_defaults(self) -> None:
        """틱봉 전환 시 사용할 RSI 및 리버모어 캔들 수 기본값을 복원한다."""
        # 틱 모드 기본값 사용 (별도로 저장된 값)
        self._settings.rsi_period = getattr(self._settings, "tick_default_rsi_period", 14)
        self._settings.rsi_overbought = getattr(self._settings, "tick_default_rsi_overbought", 70.0)
        self._settings.rsi_sell_half = getattr(self, "_tick_default_rsi_sell_half", getattr(self._settings, "rsi_sell_half", 39.0))
        self._settings.rsi_sell_all = getattr(self, "_tick_default_rsi_sell_all", getattr(self._settings, "rsi_sell_all", 29.0))
        
        lv_period = getattr(self._settings, "tick_default_livermore_period", 30)
        self._settings.livermore_breakout_period = lv_period
        self._settings.livermore_exit_period = lv_period

    def _seed_history_from_recent_ticks(self) -> int:
        """최근 틱 히스토리로 RSI 초기 상태와 전략의 역사 상태를 워밍업한다."""
        rsi_period = max(1, int(getattr(self._settings, "rsi_period", 14)))
        # 전략에 따라 필요한 캔들 수가 더 클 수 있으므로 충분히 확보한다.
        strategy_keep = 0
        if hasattr(self._strategy, "breakout_period"):
            strategy_keep = max(strategy_keep, getattr(self._strategy, "breakout_period", 0))
        if hasattr(self._strategy, "exit_period"):
            strategy_keep = max(strategy_keep, getattr(self._strategy, "exit_period", 0))
        
        window_size = max(rsi_period * 4, strategy_keep * 4)
        seeded_count = 0
        for code in self._watchlist.get_tracked_codes():
            if str(getattr(self._settings, "candle_source", "tick")).lower() == "minute":
                history = list(self._recent_minute_candles_by_code.get(code, []))
                if len(history) < rsi_period:
                    history = list(self._recent_candles_by_code.get(code, []))
            else:
                history = list(self._recent_candles_by_code.get(code, []))
            if len(history) < rsi_period:
                continue
            if len(history) > window_size:
                history = history[-window_size:]
            
            tracker = RsiTracker(period=rsi_period)
            last_rsi = None
            for candle in history:
                rsi = tracker.update(candle.close)
                if rsi is not None:
                    last_rsi = rsi
            
            # 전략의 seed_history 지원 여부 확인 후 백필
            if hasattr(self._strategy, "seed_history"):
                highs = [c.high for c in history]
                lows = [c.low for c in history]
                closes = [c.close for c in history]
                try:
                    self._strategy.seed_history(code, highs, lows, closes)
                except Exception as e:
                    self._logger.error("전략 히스토리 시딩 실패 (%s): %s", code, e)
            
            if last_rsi is not None:
                with self._rsi_trackers_lock:
                    self._rsi_trackers[code] = tracker
                    self._last_rsi_values[code] = last_rsi
                seeded_count += 1
        return seeded_count

    def change_rsi_period(self, period: int) -> None:
        """기간 설정을 변경하고 관련 지표/전략 기간을 함께 반영한다."""
        try:
            new_period = int(period)
        except (TypeError, ValueError):
            self._logger.error("RSI 기간이 숫자가 아닙니다: %s", period)
            return
        if new_period <= 0:
            self._logger.error("RSI 기간은 1 이상이어야 합니다: %s", period)
            return
        current_values = (
            int(getattr(self._settings, "rsi_period", 14)),
            int(getattr(self._settings, "minute_default_livermore_period", 5)),
            int(getattr(self._settings, "livermore_breakout_period", 20)),
            int(getattr(self._settings, "livermore_exit_period", 10)),
            int(getattr(self._settings, "livermore_adx_period", getattr(self._settings, "adx_period", 14))),
            int(getattr(self._settings, "donchian_breakout_period", 20)),
            int(getattr(self._settings, "donchian_exit_period", 10)),
            int(getattr(self._settings, "rsi_adx_period", getattr(self._settings, "adx_period", 14))),
        )
        if all(value == new_period for value in current_values):
            return

        self._settings.rsi_period = new_period
        self._settings.minute_default_livermore_period = new_period
        self._settings.livermore_breakout_period = new_period
        self._settings.livermore_exit_period = new_period
        self._settings.livermore_adx_period = new_period
        self._settings.donchian_breakout_period = new_period
        self._settings.donchian_exit_period = new_period
        self._settings.rsi_adx_period = new_period

        with self._rsi_trackers_lock:
            self._rsi_trackers.clear()
            self._last_rsi_values.clear()
        self._last_rsi = "-"
        self._rebuild_strategy(self._strategy_name)
        self._logger.info(
            "기간 설정 변경: %d (rsi/livermore/donchian/adx_period 동시 반영)",
            new_period,
        )
        self._bump_ui_version("rsi_period")
        self._bump_ui_version("strategy")
        self._publish_status()

    def change_rsi_thresholds(self, overbought: float, sell_half: float, sell_all: float) -> None:
        """RSI 매수/매도 기준값을 변경하고 전략에 즉시 반영한다."""
        try:
            new_overbought = float(overbought)
            new_sell_half = float(sell_half)
            new_sell_all = float(sell_all)
        except (TypeError, ValueError):
            self._logger.error(
                "RSI 기준값이 숫자가 아닙니다: overbought=%s sell_half=%s sell_all=%s",
                overbought,
                sell_half,
                sell_all,
            )
            return
        for label, value in (
            ("overbought", new_overbought),
            ("sell_half", new_sell_half),
            ("sell_all", new_sell_all),
        ):
            if value < 0.0 or value > 100.0:
                self._logger.error("RSI %s 기준값은 0~100 범위여야 합니다: %.2f", label, value)
                return

        current_values = (
            float(getattr(self._settings, "rsi_overbought", 70.0)),
            float(getattr(self._settings, "rsi_sell_half", 39.0)),
            float(getattr(self._settings, "rsi_sell_all", 29.0)),
        )
        new_values = (new_overbought, new_sell_half, new_sell_all)
        if all(abs(current - new) < 0.0001 for current, new in zip(current_values, new_values)):
            return

        self._settings.rsi_overbought = new_overbought
        self._settings.rsi_sell_half = new_sell_half
        self._settings.rsi_sell_all = new_sell_all
        self._rebuild_strategy(self._strategy_name)
        self._logger.info(
            "RSI 기준값 변경: overbought %.1f, sell_half %.1f, sell_all %.1f",
            new_overbought,
            new_sell_half,
            new_sell_all,
        )
        self._bump_ui_version("rsi_period")
        self._bump_ui_version("strategy")
        self._publish_status()

    def change_order_size_config(self, buy_mode: str, buy_value: int) -> None:
        """UI에서 변경한 매수 주문 금액/수량 설정을 반영한다."""
        buy_mode_norm = str(buy_mode or "cash").lower()
        if buy_mode_norm not in ("cash", "qty"):
            self._logger.error("알 수 없는 매수 모드: %s", buy_mode)
            return
        buy_num = max(0, int(buy_value))

        self._settings.buy_size_mode = buy_mode_norm
        if buy_mode_norm == "cash":
            self._settings.buy_cash = buy_num
        else:
            self._settings.buy_qty = buy_num
        self._logger.info(
            "주문 설정 변경: 매수 %s=%s",
            buy_mode_norm,
            buy_num,
        )
        self._bump_ui_version("buy_order")
        self._publish_status()

    def change_excluded_codes(self, raw_codes) -> None:
        """감시/자동매매 제외 종목 코드를 변경한다."""
        try:
            # 기존 _excluded_codes_set도 업데이트 (하위 호환성)
            normalized = self._normalize_excluded_codes(raw_codes)
            new_set = set(normalized)
            if new_set == self._excluded_codes_set:
                return
            
            # BlocklistManager에 동기화 (str/list 모두 처리)
            csv_str = raw_codes if isinstance(raw_codes, str) else ",".join(str(c) for c in (raw_codes or []))
            self._blocklist_manager.load_from_csv(csv_str)
            self._blocklist_manager.save()
            
            # settings 업데이트
            self._excluded_codes_set = new_set
            self._settings.excluded_codes = sorted(new_set)
            self._watchlist.set_excluded_codes(new_set)
            self._logger.info("제외 종목 변경: %s", ", ".join(normalized) if normalized else "-")
            self._sync_real_registration()
            self._bump_ui_version("exclude")
            self._publish_status()
        except Exception as e:
            self._logger.error("제외 종목 변경 실패: %s", e)

    def change_pyramiding_config(self, strategy_name: str, enabled: bool) -> None:
        """전략별 추가매수 피라미딩 사용 여부를 변경한다."""
        target = str(strategy_name or "").strip().lower()
        mapping = {
            "rsi_grid": "rsi_pyramiding_enabled",
            "livermore_pyramid": "livermore_pyramiding_enabled",
        }
        setting_key = mapping.get(target)
        if not setting_key:
            self._logger.error("피라미딩 설정 대상이 아닙니다: %s", strategy_name)
            return
        enabled_bool = bool(enabled)
        current = bool(getattr(self._settings, setting_key, True))
        current_strategy_state = None
        if target == str(self._strategy_name or "").strip().lower():
            current_strategy_state = bool(getattr(self._strategy, "pyramiding_enabled", current))
        if current == enabled_bool and (current_strategy_state is None or current_strategy_state == enabled_bool):
            return
        setattr(self._settings, setting_key, enabled_bool)
        self._rebuild_strategy(self._strategy_name)
        self._logger.info("피라미딩 설정 변경: %s -> %s", target, "ON" if enabled_bool else "OFF")
        self._bump_ui_version("strategy")
        self._publish_status()

    def change_cci_filter_config(self, strategy_name: str, enabled: bool) -> None:
        """전략별 CCI 필터 사용 여부를 변경한다."""
        target = str(strategy_name or "").strip().lower()
        mapping = {
            "rsi_grid": "rsi_use_cci_filter",
            "livermore_pyramid": "livermore_use_cci_filter",
        }
        setting_key = mapping.get(target)
        if not setting_key:
            self._logger.error("CCI 필터 설정 대상이 아닙니다: %s", strategy_name)
            return
        enabled_bool = bool(enabled)
        current = bool(getattr(self._settings, setting_key, False))
        current_strategy_state = None
        if target == str(self._strategy_name or "").strip().lower():
            current_strategy_state = bool(getattr(self._strategy, "use_cci_filter", current))
        if current == enabled_bool and (current_strategy_state is None or current_strategy_state == enabled_bool):
            return
        setattr(self._settings, setting_key, enabled_bool)
        self._rebuild_strategy(self._strategy_name)
        self._logger.info("CCI 필터 설정 변경: %s -> %s", target, "ON" if enabled_bool else "OFF")
        self._bump_ui_version("strategy")
        self._publish_status()

    def change_cci_threshold_config(self, strategy_name: str, entry_threshold: float, add_threshold: float) -> None:
        """전략별 CCI 진입/추가매수 기준값을 변경한다."""
        target = str(strategy_name or "").strip().lower()
        mapping = {
            "rsi_grid": ("rsi_cci_entry_threshold", "rsi_cci_add_threshold"),
            "livermore_pyramid": ("livermore_cci_entry_threshold", "livermore_cci_add_threshold"),
        }
        setting_keys = mapping.get(target)
        if not setting_keys:
            self._logger.error("CCI 기준값 설정 대상이 아닙니다: %s", strategy_name)
            return
        entry_key, add_key = setting_keys
        entry_value = float(entry_threshold)
        add_value = float(add_threshold)
        current_entry = float(getattr(self._settings, entry_key, 0.0))
        current_add = float(getattr(self._settings, add_key, 0.0))
        current_strategy_entry = None
        current_strategy_add = None
        if target == str(self._strategy_name or "").strip().lower():
            current_strategy_entry = float(getattr(self._strategy, "cci_entry_threshold", current_entry))
            current_strategy_add = float(getattr(self._strategy, "cci_add_threshold", current_add))
        if (
            current_entry == entry_value
            and current_add == add_value
            and (
                current_strategy_entry is None
                or (current_strategy_entry == entry_value and current_strategy_add == add_value)
            )
        ):
            return
        setattr(self._settings, entry_key, entry_value)
        setattr(self._settings, add_key, add_value)
        self._rebuild_strategy(self._strategy_name)
        self._logger.info(
            "CCI 기준값 변경: %s entry=%.1f add=%.1f",
            target,
            entry_value,
            add_value,
        )
        self._bump_ui_version("strategy")
        self._publish_status()

    def _is_excluded_code(self, code: str) -> bool:
        """종목코드가 제외 대상인지 확인한다."""
        # BlocklistManager 확인 (우선순위 1)
        if self._blocklist_manager is not None:
            try:
                if self._blocklist_manager.is_blocked(code=code):
                    return True
            except Exception:
                # BlocklistManager 오류 시 다음 단계로
                pass
        
        # 기존 _excluded_codes_set도 확인 (하위 호환성)
        normalized = normalize_code(code)
        return bool(normalized and normalized in self._excluded_codes_set)

    def _normalize_excluded_codes(self, raw_codes) -> List[str]:
        """입력값을 제외 종목 코드 리스트(중복 제거)로 정규화한다."""
        if raw_codes is None:
            return []
        tokens: List[str] = []
        if isinstance(raw_codes, str):
            tokens = re.split(r"[\s,;]+", raw_codes)
        elif isinstance(raw_codes, (list, tuple, set)):
            for item in raw_codes:
                if item is None:
                    continue
                tokens.extend(re.split(r"[\s,;]+", str(item)))
        else:
            tokens = re.split(r"[\s,;]+", str(raw_codes))

        reverse_name = {
            str(name).strip(): code for code, name in self._code_names.items() if str(name).strip()
        }
        normalized: List[str] = []
        seen = set()
        ignored: List[str] = []
        for token in tokens:
            value = str(token).strip()
            if not value:
                continue
            code = normalize_code(value)
            if not code:
                code = reverse_name.get(value, "")
            if not code:
                ignored.append(value)
                continue
            if code in seen:
                continue
            seen.add(code)
            normalized.append(code)
        if ignored:
            self._logger.warning("제외 종목 입력 무시(코드 해석 실패): %s", ", ".join(ignored))
        return normalized

    def _bump_ui_version(self, key: str) -> None:
        """UI 설정 동기화 버전을 증가시킨다."""
        current = int(self._ui_versions.get(key, 0))
        self._ui_versions[key] = current + 1

    def _load_condition_list(self, retry_seconds: int) -> Dict[int, str]:
        """조건식 목록을 로드한다."""
        cond_raw = ""
        attempts = max(1, retry_seconds) if retry_seconds > 0 else 1
        for _ in range(attempts):
            cond_raw = self._gateway.get_condition_name_list()
            if cond_raw:
                break
            if retry_seconds > 0:
                time.sleep(1.0)
        cond_map = parse_condition_list(cond_raw)
        if cond_map:
            self._condition_list = sorted(cond_map.items(), key=lambda x: x[0])
        if not cond_raw and not self._condition_log_emitted:
            self._logger.error("조건식 목록이 비어있습니다. HTS에서 조건식이 저장되어 있는지 확인하세요.")
            self._condition_log_emitted = True
        return cond_map

    def _refresh_holdings(self, force: bool) -> None:
        """계좌 보유 종목을 갱신한다."""
        if not self._account_no:
            return
        now = self._clock.now()
        interval = float( # 갱신 주기 설정
            getattr(self._settings, "holdings_refresh_seconds", self._settings.account_refresh_seconds) # 기본값은 계좌 갱신 주기와 동일
        )
        if not force and self._last_holdings_refresh: # 이전 갱신 시점이 있으면
            if (now - self._last_holdings_refresh).total_seconds() < interval: # 아직 갱신 주기가 지나지 않았으면
                return
        holdings = self._gateway.request_holdings(self._account_no, self._settings.account_password) # 보유 종목 조회
        if holdings is None:
            self._logger.warning("보유 종목 조회 실패")
            return
        self._apply_sell_sync_guard(holdings, now)
        self._log_pending_sell_trace(holdings, now)
        self._portfolio.update_from_holdings(holdings) # 포트폴리오 갱신
        self._watchlist.update_holdings(self._portfolio.get_codes()) # 감시 리스트 보유 상태 갱신
        self._cache_names(self._portfolio.get_codes(), holdings) # 종목명 캐시 갱신
        self._sync_real_registration() # 실시간 등록 갱신
        self._last_holdings_refresh = now # 마지막 갱신 시점 기록
        self._publish_status() # 상태 갱신

    def _apply_sell_sync_guard(self, holdings: Dict[str, Dict[str, int]], now: datetime.datetime) -> None:
        """매도 직후 stale TR 잔고가 복원되는 현상을 방지한다."""
        expired_codes: List[str] = []
        for code, guard in self._sell_sync_guard.items():
            guard_qty, guard_until = guard
            if now > guard_until:
                expired_codes.append(code)
                continue
            if code not in holdings:
                continue
            tr_qty = int(holdings[code].get("qty", 0))
            if tr_qty <= guard_qty:
                continue
            if guard_qty <= 0:
                holdings.pop(code, None)
            else:
                holdings[code]["qty"] = guard_qty
                holdings[code]["sellable"] = min(int(holdings[code].get("sellable", guard_qty)), guard_qty)
        for code in expired_codes:
            self._sell_sync_guard.pop(code, None)

    def _log_pending_sell_trace(self, holdings: Dict[str, Dict[str, int]], now: datetime.datetime) -> None:
        """수동 전량매도 후 TR 잔고 동기화 상태를 주기적으로 추적 로그로 남긴다."""
        clear_codes: List[str] = []
        for code, state in list(self._manual_sell_pending.items()):
            requested_qty = int(state.get("requested_qty", 0) or 0)
            requested_at = state.get("requested_at")
            if not isinstance(requested_at, datetime.datetime):
                requested_at = now
                state["requested_at"] = now
            elapsed = (now - requested_at).total_seconds()
            last_trace_at = state.get("last_trace_at")
            if code not in holdings:
                self._logger.info(
                    "수동 전량매도 TR반영: %s 보유수량 0주 확인 (요청 %d주, %.1fs)",
                    self._get_name(code),
                    requested_qty,
                    elapsed,
                )
                clear_codes.append(code)
                continue

            tr_qty = int(holdings[code].get("qty", 0))
            tr_sellable = int(holdings[code].get("sellable", 0))
            if tr_qty <= 0:
                self._logger.info(
                    "수동 전량매도 TR반영: %s 보유수량 0주 확인 (요청 %d주, %.1fs)",
                    self._get_name(code),
                    requested_qty,
                    elapsed,
                )
                clear_codes.append(code)
                continue

            if isinstance(last_trace_at, datetime.datetime):
                if (now - last_trace_at).total_seconds() < self._manual_sell_trace_interval_sec:
                    continue
            state["last_trace_at"] = now
            self._logger.warning(
                "수동 전량매도 대기: %s TR수량=%d TR매도가능=%d (요청 %d주, %.1fs)",
                self._get_name(code),
                tr_qty,
                tr_sellable,
                requested_qty,
                elapsed,
            )
            timeout_logged = bool(state.get("timeout_logged", False))
            if elapsed >= self._manual_sell_trace_timeout_sec and not timeout_logged:
                self._logger.warning(
                    "수동 전량매도 미체결 추정: %s %.1fs 경과, 주문체결/거부 여부를 HTS 주문내역에서 확인하세요.",
                    self._get_name(code),
                    elapsed,
                )
                state["timeout_logged"] = True

        for code in clear_codes:
            self._manual_sell_pending.pop(code, None)

    def _log_pending_order_status(self, data: dict, execution=None) -> None:
        """수동 전량매도 추적 대상의 체결/주문상태를 체결 이벤트 원본으로 로깅한다."""
        code = self._normalize_chejan_code(data)
        if not code or code not in self._manual_sell_pending:
            return
        status = str(self._chejan_field(data, "913") or "").strip()
        order_qty = clean_int(self._chejan_field(data, "900"))
        remaining = clean_int(self._chejan_field(data, "902"))
        filled = clean_int(self._chejan_field(data, "911"))
        price = clean_int(self._chejan_field(data, "910"))
        if execution is not None:
            self._logger.info(
                "주문상태(수동매도): %s 체결신호 수량=%d 잔량=%d 체결가=%s 상태=%s",
                self._get_name(code),
                int(execution.quantity),
                int(execution.remaining_qty),
                f"{int(execution.price):,}",
                status or "-",
            )
            return
        self._logger.info(
            "주문상태(수동매도): %s 상태=%s 주문수량=%d 미체결=%d 체결량=%d 체결가=%s",
            self._get_name(code),
            status or "-",
            order_qty,
            remaining,
            filled,
            f"{price:,}" if price > 0 else "-",
        )

    @staticmethod
    def _chejan_field(data: dict, fid: str):
        """체결 원본 데이터에서 문자열/정수 키를 모두 지원해 FID 값을 반환한다."""
        if fid in data:
            return data.get(fid)
        try:
            fid_int = int(fid)
        except ValueError:
            return None
        return data.get(fid_int)

    def _normalize_chejan_code(self, data: dict) -> str:
        """체결 이벤트에서 종목코드를 표준 6자리 코드로 정규화한다."""
        code_raw = self._chejan_field(data, "9001")
        if not code_raw:
            return ""
        return normalize_code(str(code_raw))

    def _sync_real_registration(self) -> None:
        """감시 리스트 변경 시 실시간 등록을 갱신한다."""
        codes = self._watchlist.get_tracked_codes()
        if self._pending_watchlist is not None and codes == self._pending_watchlist:
            return
        if codes == self._last_watchlist and self._pending_watchlist is None:
            return
        removed = set(self._last_watchlist) - set(codes)
        added = set(codes) - set(self._last_watchlist)
        # 틱봉 기반에서는 감시 해제 동안의 틱을 잃어버리므로, 재편입 시 RSI 연속성이 깨진다.
        # 따라서 기본적으로 감시 해제 시 RSI/전략 상태를 리셋한다.
        reset_rsi_on_untrack = bool(getattr(self._settings, "reset_rsi_on_untrack", False))
        with self._aggregator_lock:
            for code in removed:
                self._aggregator.reset(code)
                self._recent_minute_aggregator.reset(code)
                if reset_rsi_on_untrack:
                    with self._rsi_trackers_lock:
                        self._rsi_trackers.pop(code, None)
                        self._last_rsi_values.pop(code, None)
                    self._last_candle_end_time.pop(code, None)
                    self._strategy.reset_code(code)
                with self._strategy_pending_lock:
                    for key in [k for k in self._strategy_pending_orders.keys() if k[0] == code]:
                        self._strategy_pending_orders.pop(key, None)
                self._tick_counts.pop(code, None)
                self._last_tick_time.pop(code, None)
                self._watchlist_since.pop(code, None)
                self._recent_candles_by_code.pop(code, None)
                self._recent_minute_candles_by_code.pop(code, None)
                for signal_key in [k for k in self._signal_markers.keys() if k[0] == code]:
                    self._signal_markers.pop(signal_key, None)
        self._last_watchlist = list(codes)
        self._last_watchset = set(codes)
        now = self._clock.now()
        for code in added:
            self._watchlist_since[code] = now
            # 새로 추가된 종목은 과거 틱 데이터를 가져와 RSI를 웜업한다.
            self._warm_up_rsi(code)
        if added:
            self._cache_names(added)
        self._pending_watchlist = list(codes)
        self._flush_real_registration_if_due()

    def _flush_real_registration_if_due(self) -> None:
        """실시간 등록 갱신을 필요한 시점에 수행한다."""
        if self._pending_watchlist is None:
            return
        min_interval = float(getattr(self._settings, "real_reg_min_interval_sec", 0.0))
        now = self._clock.now()
        if self._last_real_reg_at:
            if (now - self._last_real_reg_at).total_seconds() < min_interval:
                return
        codes = self._pending_watchlist
        self._pending_watchlist = None
        self._apply_real_registration(codes)

    def _apply_real_registration(self, codes: List[str]) -> None:
        """실시간 등록을 실제로 수행한다."""
        if not codes:
            self._gateway.disconnect_real(self._settings.real_screen)
            self._logger.info("실시간 등록 해제: 감시 종목 없음")
            self._last_real_reg_at = self._clock.now()
            return
        self._gateway.set_real_reg(
            screen=self._settings.real_screen,
            codes=codes,
            fids=self._settings.real_fids,
            opt_type=0,
        )
        self._last_real_reg_at = self._clock.now()
        self._logger.info("실시간 등록: %d종목", len(codes))

    def _warm_up_rsi(self, code: str) -> None:
        """과거 데이터로 RSI 트래커와 전략 히스토리를 준비한다."""
        with self._rsi_trackers_lock:
            if code in self._rsi_trackers:
                return

        self._logger.info("RSI 웜업 시작: %s", self._get_name(code))
        candle_source = str(getattr(self._settings, "candle_source", "tick")).lower()
        history_candles: List[Candle] = []
        source_label = "캔들"
        source_count = 0

        if candle_source == "minute":
            history_candles = self._fetch_minute_history_candles(code)
            source_label = "분봉"
            source_count = len(history_candles)

        if not history_candles:
            records = self._fetch_tick_history_records(code, candle_source)
            if not records:
                self._logger.warning("RSI 웜업 실패 (데이터 없음): %s", code)
                return
            history_candles = self._build_history_candles_from_tick_records(code, records, candle_source)
            source_label = "틱"
            source_count = len(records)

        if not history_candles:
            self._logger.warning("RSI 웜업 실패 (캔들 생성 실패): %s", code)
            return

        rsi_period = int(getattr(self._settings, "rsi_period", 14))
        tracker = RsiTracker(period=rsi_period)
        warmed_candles = 0
        last_close = 0
        for candle in history_candles:
            tracker.update(candle.close)
            last_close = int(candle.close)
            warmed_candles += 1

        if warmed_candles <= 0:
            return

        with self._rsi_trackers_lock:
            self._rsi_trackers[code] = tracker
        if hasattr(self._strategy, "seed_history"):
            highs = [c.high for c in history_candles]
            lows = [c.low for c in history_candles]
            closes = [c.close for c in history_candles]
            try:
                self._strategy.seed_history(code, highs, lows, closes)
            except Exception as e:
                self._logger.error("전략 히스토리 시딩 실패 (%s): %s", code, e)

        if last_close > 0:
            preview = tracker.preview(last_close)
            if preview is not None:
                self._last_rsi_values[code] = preview

        self._logger.info(
            "초기 데이터 웜업 완료: %s (%s %d건 -> %d캔들 학습)",
            self._get_name(code),
            source_label,
            source_count,
            warmed_candles,
        )

    def _fetch_tick_history_records(self, code: str, candle_source: str) -> List[dict]:
        """틱 히스토리를 조회해 레코드 목록으로 반환한다."""
        try:
            if candle_source == "minute":
                tick_size = int(getattr(self._settings, "minute_backfill_tick_size", 20))
                candle_count = int(getattr(self._settings, "minute_backfill_candle_count", 20))
                request_count = max(1200, tick_size * candle_count * 5)
            else:
                request_count = 1200
            records = self._gateway.request_tick_history(code, count=request_count)
        except Exception as e:
            self._logger.error("RSI 웜업 중 틱 TR 요청 실패: %s", e)
            return []
        return list(reversed(records or []))

    def _fetch_minute_history_candles(self, code: str) -> List[Candle]:
        """분봉 히스토리를 직접 조회해 캔들 목록으로 반환한다."""
        if not hasattr(self._gateway, "request_minute_history"):
            return []
        try:
            minutes = int(getattr(self._settings, "minutes_per_candle", 1))
            candle_count = int(getattr(self._settings, "minute_backfill_candle_count", 20))
            records = self._gateway.request_minute_history(code, interval=minutes, count=candle_count)
        except Exception as e:
            self._logger.error("RSI 웜업 중 분봉 TR 요청 실패: %s", e)
            return []
        if not records:
            return []
        history_candles: List[Candle] = []
        for rec in reversed(list(records)):
            open_price = abs(clean_int(rec.get("시가") or rec.get("open") or 0))
            high_price = abs(clean_int(rec.get("고가") or rec.get("high") or 0))
            low_price = abs(clean_int(rec.get("저가") or rec.get("low") or 0))
            close_price = abs(clean_int(rec.get("현재가") or rec.get("close") or 0))
            volume = clean_int(rec.get("거래량") or rec.get("volume") or 0)
            end_time = str(rec.get("체결시간") or rec.get("time") or "")
            if open_price <= 0 or high_price <= 0 or low_price <= 0 or close_price <= 0:
                continue
            history_candles.append(
                Candle(
                    code=code,
                    open=open_price,
                    high=high_price,
                    low=low_price,
                    close=close_price,
                    volume=volume,
                    tick_count=0,
                    end_time=end_time,
                )
            )
        candle_count = int(getattr(self._settings, "minute_backfill_candle_count", 20))
        if candle_count > 0 and len(history_candles) > candle_count:
            history_candles = history_candles[-candle_count:]
        return history_candles

    def _build_history_candles_from_tick_records(self, code: str, records: List[dict], candle_source: str) -> List[Candle]:
        """틱 레코드를 캔들로 집계한다."""
        if candle_source == "minute":
            minutes = int(getattr(self._settings, "minutes_per_candle", 1))
            candle_count = int(getattr(self._settings, "minute_backfill_candle_count", 20))
            temp_agg = TimeAggregator(minutes_per_candle=minutes)
        else:
            candle_count = 0
            ticks = int(getattr(self._settings, "ticks_per_candle", 20))
            temp_agg = TickAggregator(ticks_per_candle=ticks)
        history_candles: List[Candle] = []
        for rec in records:
            price = clean_int(rec.get("현재가") or rec.get("close") or 0)
            vol = clean_int(rec.get("거래량") or rec.get("volume") or 0)
            t = str(rec.get("체결시간") or rec.get("time") or "")
            if price == 0:
                continue
            tick = Tick(code=code, price=abs(price), volume=vol, time=t)
            candle = temp_agg.update(tick)
            if candle:
                history_candles.append(candle)
        if candle_source == "minute":
            last_candle = temp_agg.get_current_candle(code)
            if last_candle:
                history_candles.append(last_candle)
            if candle_count > 0 and len(history_candles) > candle_count:
                history_candles = history_candles[-candle_count:]
        return history_candles

    def _publish_status(self) -> None:
        """상태 정보를 UI 버스로 전달한다."""
        realtime = self._collect_realtime_status()
        watchlist_names = ", ".join([self._get_name(code) for code in self._watchlist.get_tracked_codes()])
        holdings_summary = self._build_holdings_summary()
        holdings_items = self._build_holdings_items()
        rsi_summary = self._build_rsi_summary()
        rsi_items = self._build_rsi_items()
        account_summary = self._build_account_summary()
        daily_trade_details = self._daily_tracker.details()
        daily_trade_items = self._daily_tracker.detail_items()
        excluded_items = self._build_excluded_items()
        condition_name = self._condition_name or "-"
        buy_mode = str(getattr(self._settings, "buy_size_mode", "cash") or "cash").lower()
        buy_value = int(getattr(self._settings, "buy_cash", 0)) if buy_mode == "cash" else int(
            getattr(self._settings, "buy_qty", 0)
        )
        snapshot = StatusSnapshot(
            server_mode="모의" if self._server_mode == "1" else "실전",
            account_no=self._mask_account(self._account_no),
            condition_index=self._settings.condition_index,
            condition_name=condition_name,
            strategy_name=self._strategy_name,
            candle_source=getattr(self._settings, "candle_source", "tick"),
            ticks_per_candle=getattr(self._settings, "ticks_per_candle", 0),
            minutes_per_candle=getattr(self._settings, "minutes_per_candle", 0),
            rsi_period=int(getattr(self._settings, "rsi_period", 14)),
            rsi_overbought=float(getattr(self._settings, "rsi_overbought", 70.0)),
            rsi_sell_half=float(getattr(self._settings, "rsi_sell_half", 39.0)),
            rsi_sell_all=float(getattr(self._settings, "rsi_sell_all", 29.0)),
            condition_version=int(self._ui_versions.get("condition", 0)),
            strategy_version=int(self._ui_versions.get("strategy", 0)),
            candle_version=int(self._ui_versions.get("candle", 0)),
            rsi_period_version=int(self._ui_versions.get("rsi_period", 0)),
            buy_order_version=int(self._ui_versions.get("buy_order", 0)),
            exclude_version=int(self._ui_versions.get("exclude", 0)),
            buy_size_mode=buy_mode,
            buy_size_value=buy_value,
            excluded_codes_text=", ".join(sorted(self._excluded_codes_set)),
            excluded_items=excluded_items,
            watchlist_count=len(self._watchlist.get_tracked_codes()),
            holding_count=self._portfolio.count(),
            last_signal=self._last_signal,
            last_rsi=self._last_rsi,
            last_update=self._clock.now(),
            realtime_status=realtime["text"],
            realtime_status_level=realtime["level"],
            real_ingress_queue_size=int(realtime["real_ingress_queue_size"]),
            tick_compute_queue_size=int(realtime["tick_queue_size"]),
            tick_compute_queue_capacity=int(realtime["tick_queue_capacity"]),
            tick_drop_count=int(realtime["tick_drop_count"]),
            tr_limit_wait_ms_1s=float(realtime["tr_wait_ms"]),
            order_limit_wait_ms_1s=float(realtime["order_wait_ms"]),
            watchlist_names=watchlist_names,
            holdings_summary=holdings_summary,
            rsi_summary=rsi_summary,
            rsi_items=rsi_items,
            account_summary=account_summary,
            daily_trade_details=daily_trade_details,
            daily_trade_items=daily_trade_items,
            condition_items=[{"index": idx, "name": name} for idx, name in self._condition_list],
            strategy_items=self._build_strategy_items(),
            holdings_items=holdings_items,
        )
        self._status_bus.publish(snapshot)

    def _build_strategy_items(self) -> List[dict]:
        """UI용 전략 목록과 전략별 부가 설정 상태를 생성한다."""
        items: List[dict] = []
        for item in self._strategy_items:
            row = dict(item)
            name = str(row.get("name", "") or "")
            if name == "rsi_grid":
                row["pyramiding_enabled"] = bool(getattr(self._settings, "rsi_pyramiding_enabled", True))
                row["cci_filter_enabled"] = bool(getattr(self._settings, "rsi_use_cci_filter", False))
                row["cci_entry_threshold"] = float(getattr(self._settings, "rsi_cci_entry_threshold", 50.0))
                row["cci_add_threshold"] = float(getattr(self._settings, "rsi_cci_add_threshold", 100.0))
            elif name == "livermore_pyramid":
                row["pyramiding_enabled"] = bool(getattr(self._settings, "livermore_pyramiding_enabled", True))
                row["cci_filter_enabled"] = bool(getattr(self._settings, "livermore_use_cci_filter", False))
                row["cci_entry_threshold"] = float(getattr(self._settings, "livermore_cci_entry_threshold", 80.0))
                row["cci_add_threshold"] = float(getattr(self._settings, "livermore_cci_add_threshold", 100.0))
            items.append(row)
        return items

    def _build_excluded_items(self) -> List[dict]:
        """제외 종목 UI용 코드/이름 목록을 생성한다."""
        items: List[dict] = []
        for code in sorted(self._excluded_codes_set):
            items.append(
                {
                    "code": str(code),
                    "name": self._get_name(code),
                }
            )
        return items

    def _collect_realtime_status(self) -> Dict[str, object]:
        """실시간 처리 상태를 계산해 UI 요약 문자열과 경고 레벨을 반환한다."""
        real_ingress_queue_size = 0
        ingress_drop_count = 0
        if hasattr(self._gateway, "get_real_ingress_size"):
            try:
                real_ingress_queue_size = int(self._gateway.get_real_ingress_size())
            except Exception:
                real_ingress_queue_size = 0
        if hasattr(self._gateway, "get_real_ingress_drop_count"):
            try:
                ingress_drop_count = int(self._gateway.get_real_ingress_drop_count())
            except Exception:
                ingress_drop_count = 0
        tick_queue_size, tick_queue_capacity, shard_max_ratio = self._get_tick_queue_stats()
        tick_drop_count = int(self._tick_drop_count) + max(0, int(ingress_drop_count))

        tr_wait_ms = 0.0
        order_wait_ms = 0.0
        if hasattr(self._gateway, "get_rate_limit_wait_ms"):
            try:
                wait_stats = self._gateway.get_rate_limit_wait_ms() or {}
                tr_wait_ms = float(wait_stats.get("tr", 0.0) or 0.0)
                order_wait_ms = float(wait_stats.get("order", 0.0) or 0.0)
            except Exception:
                tr_wait_ms = 0.0
                order_wait_ms = 0.0

        queue_ratio = 0.0
        if tick_queue_capacity > 0:
            queue_ratio = float(tick_queue_size) / float(tick_queue_capacity)
        warn_queue_ratio = float(getattr(self._settings, "ui_realtime_warn_queue_ratio", 0.7))
        warn_drop_count = int(getattr(self._settings, "ui_realtime_warn_drop_count", 1))
        warn_limit_wait_ms = float(getattr(self._settings, "ui_realtime_warn_limit_wait_ms", 200.0))
        level = "ok"
        if (
            max(queue_ratio, shard_max_ratio) >= warn_queue_ratio
            or tick_drop_count >= warn_drop_count
            or tr_wait_ms >= warn_limit_wait_ms
            or order_wait_ms >= warn_limit_wait_ms
        ):
            level = "warn"

        text = (
            f"수신Q {real_ingress_queue_size} | "
            f"연산Q {tick_queue_size}/{tick_queue_capacity}({queue_ratio * 100:.0f}%) | "
            f"샤드최대 {shard_max_ratio * 100:.0f}% | "
            f"수신/처리 {self._total_ticks_received}/{self._total_ticks_processed} | "
            f"드롭 T{int(self._tick_drop_count)}/R{int(ingress_drop_count)} | "
            f"TR대기 {tr_wait_ms:.0f}ms | "
            f"주문대기 {order_wait_ms:.0f}ms"
        )
        return {
            "text": text,
            "level": level,
            "real_ingress_queue_size": real_ingress_queue_size,
            "tick_queue_size": tick_queue_size,
            "tick_queue_capacity": tick_queue_capacity,
            "tick_drop_count": tick_drop_count,
            "tr_wait_ms": tr_wait_ms,
            "order_wait_ms": order_wait_ms,
        }

    def _get_tick_queue_stats(self) -> Tuple[int, int, float]:
        """샤드 큐 전체 점유율과 최대 샤드 점유율을 계산한다."""
        total_size = 0
        total_capacity = 0
        max_ratio = 0.0
        for tick_queue in self._tick_shard_queues:
            try:
                size = int(tick_queue.qsize())
            except Exception:
                size = 0
            cap = int(getattr(tick_queue, "maxsize", 0) or 0)
            total_size += size
            total_capacity += cap
            if cap > 0:
                max_ratio = max(max_ratio, float(size) / float(cap))
        return total_size, total_capacity, max_ratio

    def _log_tick_health(self) -> None:
        """틱 수신 누락만 요약 로그로 출력한다."""
        interval = float(
            getattr(
                self._settings,
                "tick_missing_log_interval_sec",
                getattr(self._settings, "tick_log_interval_sec", 30.0),
            )
        )
        threshold = float(getattr(self._settings, "tick_missing_threshold_sec", 5.0))
        now = self._clock.now()
        if self._last_tick_log and (now - self._last_tick_log).total_seconds() < interval:
            return
        self._last_tick_log = now
        missing = []
        for code in self._last_watchlist:
            last_time = self._last_tick_time.get(code)
            if last_time is None:
                since = self._watchlist_since.get(code, now)
                if (now - since).total_seconds() >= threshold:
                    missing.append(self._get_name(code))
                continue
            delay = (now - last_time).total_seconds()
            if delay >= threshold:
                missing.append(self._get_name(code))
        if missing:
            self._logger.warning("틱 미수신 종목: %s", ", ".join(missing))

    @staticmethod
    def _mask_account(account: str) -> str:
        """계좌 번호를 그대로 표시한다."""
        if not account:
            return "-"
        return account

    def _validate_mode(self, mode: str, server_gubun: str) -> bool:
        """모의/실전 모드를 검증한다."""
        if mode == "paper" and server_gubun != "1":
            self._logger.error("모의 모드인데 실전 서버에 접속했습니다. 주문을 중지합니다.")
            return False
        if mode == "live" and server_gubun == "1":
            self._logger.error("실전 모드인데 모의 서버에 접속했습니다. 주문을 중지합니다.")
            return False
        return True

    def _try_setup_condition(self, retry_seconds: int) -> None:
        """조건식 목록을 읽고 실시간 조건식을 등록한다."""
        with self._condition_lock:
            if self._condition_started:
                return
            cond_map = self._load_condition_list(retry_seconds)
            self._condition_name = cond_map.get(self._settings.condition_index, "")
            if not self._condition_name:
                self._logger.error("조건식 인덱스 %s를 찾지 못했습니다.", self._settings.condition_index)
                return
            self._logger.info("조건식 선택: %s(%s)", self._condition_name, self._settings.condition_index)
            self._gateway.send_condition(
                screen=self._settings.condition_screen,
                cond_name=self._condition_name,
                index=self._settings.condition_index,
                search=1,
            )
            self._condition_started = True

    def _get_name(self, code: str) -> str:
        """종목명을 캐시에서 가져오거나 조회한다."""
        if not code:
            return ""
        name = self._code_names.get(code)
        if name:
            return name
        name = self._gateway.get_master_code_name(code)
        if not name:
            name = code
        self._code_names[code] = name
        return name

    def _cache_names(self, codes, holdings_data: Optional[Dict[str, Dict[str, int]]] = None) -> None:
        """종목명 캐시를 갱신한다."""
        for code in codes:
            if code in self._code_names:
                continue
            name = ""
            if holdings_data and code in holdings_data:
                name = str(holdings_data[code].get("name", "") or "").strip()
            if not name:
                name = self._gateway.get_master_code_name(code)
            if name:
                self._code_names[code] = name

    def _build_holdings_summary(self) -> str:
        """보유 종목 요약을 생성한다."""
        lines: List[str] = []
        for code, pos in self._portfolio.get_positions().items():
            name = self._get_name(code)
            last_price = self._last_prices.get(code, 0)
            avg_price = pos.avg_price
            if avg_price > 0 and last_price > 0:
                value = last_price * pos.qty
                pnl_amount = (last_price - avg_price) * pos.qty
                pnl_rate = (last_price - avg_price) / avg_price * 100.0
                lines.append(
                    f"{name} {pos.qty}주 평균 {avg_price:,}원 현재 {last_price:,}원 "
                    f"평가 {value:,}원 ({pnl_rate:.2f}%, {pnl_amount:+,}원)"
                )
            else:
                lines.append(f"{name} {pos.qty}주")
        return "\n".join(lines) if lines else "-"

    def _build_holdings_items(self) -> List[dict]:
        """보유 종목 상세 목록을 생성한다."""
        items: List[dict] = []
        for code, pos in self._portfolio.get_positions().items():
            name = self._get_name(code)
            last_price = self._last_prices.get(code, 0)
            avg_price = pos.avg_price
            value = last_price * pos.qty if last_price > 0 else 0
            pnl_amount = (last_price - avg_price) * pos.qty if avg_price > 0 and last_price > 0 else 0
            pnl_rate = (last_price - avg_price) / avg_price * 100.0 if avg_price > 0 and last_price > 0 else 0.0
            items.append(
                {
                    "code": code,
                    "name": name,
                    "qty": pos.qty,
                    "avg_price": avg_price,
                    "last_price": last_price,
                    "value": value,
                    "pnl_amount": pnl_amount,
                    "pnl_rate": pnl_rate,
                }
            )
        return items

    def _build_rsi_summary(self) -> str:
        """RSI 요약을 생성한다."""
        tracked = self._watchlist.get_tracked_codes()
        if not tracked:
            return "-"
        lines = []
        for code in tracked:
            value = self._last_rsi_values.get(code)
            if value is None:
                lines.append(f"{self._get_name(code)} -")
            else:
                lines.append(f"{self._get_name(code)} {value:.2f}")
        return "\n".join(lines)

    def _build_rsi_items(self) -> List[dict]:
        """RSI 요약 목록을 생성한다."""
        items: List[dict] = []
        tracked = self._watchlist.get_tracked_codes()
        for code in tracked:
            item = {
                "code": code,
                "name": self._get_name(code),
                "value": self._last_rsi_values.get(code),
            }
            if hasattr(self._aggregator, "get_current_candle"):
                lock = self._get_aggregator_lock_for(code)
                with lock:
                    current_candle = self._aggregator.get_current_candle(code)
                if current_candle is not None:
                    item["in_progress_close"] = int(current_candle.close)
                    item["in_progress_end_time"] = str(current_candle.end_time or "")
            items.append(item)
        return items

    def _build_account_summary(self) -> str:
        """계좌 요약을 생성한다."""
        lines: List[str] = []
        fee_rate = float(getattr(self._settings, "fee_rate", 0.0))
        
        # 계좌 현금 정보
        deposit = 0
        orderable = 0
        if self._account_info:
            deposit = self._account_info.get("deposit", 0)
            orderable = self._account_info.get("orderable", 0)

        # 보유 주식 평가액 계산
        total_buy = 0
        total_value = 0
        for code, pos in self._portfolio.get_positions().items():
            avg_price = pos.avg_price
            last_price = self._last_prices.get(code, 0)
            if avg_price > 0:
                total_buy += avg_price * pos.qty
            if last_price > 0:
                total_value += last_price * pos.qty

        # 추정자산 = 예수금 + 보유 주식 평가액
        estimated_asset = deposit + total_value
        lines.append(f"추정자산 {int(estimated_asset):,}원 | 예수금 {int(deposit):,}원 | 주문가능 {int(orderable):,}원")

        # 보유 주식 손익 계산
        fee_total = 0
        net_buy = 0.0
        net_value = 0.0
        unrealized_pnl = 0.0
        if total_buy > 0 and total_value > 0:
            buy_fee = total_buy * fee_rate
            sell_fee = total_value * fee_rate
            net_buy = total_buy + buy_fee
            net_value = total_value - sell_fee
            unrealized_pnl = net_value - net_buy
            unrealized_rate = (unrealized_pnl / net_buy) * 100.0 if net_buy > 0 else 0.0
            fee_total = int(buy_fee + sell_fee)
            lines.append(
                f"보유중: 총매입 {int(net_buy):,}원 | 평가 {int(net_value):,}원 | "
                f"미실현손익 {int(unrealized_pnl):+,}원 ({unrealized_rate:.2f}%) | "
                f"수수료 {fee_total:,}원"
            )

        # 당일 + 누적 손익
        daily_pnl = int(self._daily_tracker.net_pnl)
        daily_rate = self._daily_tracker.profit_rate
        
        # 총 손익 = 미실현 손익 + 당일 실현 손익
        total_realized = daily_pnl
        unrealized_pnl_val = (net_value - net_buy) if (total_buy > 0 and total_value > 0) else 0
        total_pnl = int(unrealized_pnl_val + total_realized)
        total_rate = (total_pnl / estimated_asset * 100.0) if estimated_asset > 0 else 0.0
        
        lines.append(
            f"당일 실현손익 {daily_pnl:+,}원 / 당일 실현수익률 {daily_rate:.2f}% | "
            f"총손익: {total_pnl:+,}원 ({total_rate:.2f}%)"
        )

        return "\n".join(lines) if lines else "잔고 요약 없음"

    def _refresh_account_info(self, force: bool) -> None:
        """계좌 예수금 정보를 갱신한다."""
        if not self._account_no:
            return
        now = self._clock.now()
        interval = float(getattr(self._settings, "account_refresh_seconds", 30.0))
        if not force and self._last_account_refresh:
            if (now - self._last_account_refresh).total_seconds() < interval:
                return
        info = self._gateway.request_deposit(self._account_no, self._settings.account_password)
        if info:
            self._account_info = dict(info)
            self._last_account_refresh = now

    def reconcile_order_history(self) -> None:
        """게이트웨이에서 주문/체결 이력을 조회해 DailyTradeTracker와 동기화한다.

        게이트웨이가 `request_order_history`를 지원하면 호출하고, 반환된 레코드를
        간단히 파싱해 아직 기록되지 않은 체결을 `DailyTradeTracker`에 추가한다.
        """
        if not hasattr(self._gateway, "request_order_history"):
            self._logger.debug("게이트웨이가 주문/체결 이력 조회를 지원하지 않습니다.")
            return
        try:
            records = self._gateway.request_order_history(self._account_no, self._settings.account_password)
        except Exception:
            self._logger.exception("주문/체결 이력 조회 실패")
            return
        if not records:
            return
        added = 0
        for rec in records:
            try:
                # 다양한 TR 포맷을 감안해 유연하게 필드 해석
                if isinstance(rec, dict):
                    code = normalize_code(rec.get("code") or rec.get("종목번호") or rec.get("9001") or "")
                    side_raw = rec.get("side") or rec.get("매도구분") or rec.get("907")
                    side = "SELL" if str(side_raw) in ("1", "S", "SELL") else "BUY" if str(side_raw) in ("2", "B", "BUY") else ""
                    qty = int(rec.get("qty") or rec.get("체결수량") or rec.get("900") or 0)
                    price = int(rec.get("price") or rec.get("체결가") or rec.get("910") or 0)
                    exec_time = str(rec.get("time") or rec.get("체결시간") or "")
                    name = str(rec.get("name") or rec.get("종목명") or "")
                else:
                    continue
                if not code or not side or qty <= 0 or price <= 0:
                    continue
                key = (code, side, int(qty), int(price), exec_time)
                if key in self._seen_executions:
                    continue
                self._daily_tracker.record(code=code, side=side, qty=qty, price=price, name=name)
                self._seen_executions.add(key)
                added += 1
            except Exception:
                self._logger.exception("주문/체결 레코드 파싱 실패: %s", rec)
        if added:
            # 동기화를 위해 보유/계좌 정보도 갱신
            try:
                self._refresh_holdings(force=True)
                self._refresh_account_info(force=False)
            except Exception:
                self._logger.exception("주문/체결 동기화 후 보유/계좌 갱신 실패")
        self._logger.info("주문/체결 이력 동기화 완료: 신규 추가 %d건", added)
