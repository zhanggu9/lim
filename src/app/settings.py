from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class Settings:
    """애플리케이션 설정을 보관한다."""

    mode: str = "paper"
    account_password: str = "" # 계좌 비밀번호
    condition_index: int = 0 # 사용할 조건식 인덱스
    condition_refresh_seconds: float = 0.5 # 조건식 스냅샷 갱신 주기(초)
    condition_screen: str = "2000" # 조건식 화면번호
    max_total_symbols: int = 20 # 최대 종목 개수
    watchlist_include_holdings: bool = True # 감시 리스트에 보유 종목 자동 편입 여부
    excluded_codes: List[str] = field(default_factory=list) # 감시/자동매매 제외 종목 코드
    ticks_per_candle: int = 60 # 캔들당 틱 개수
    candle_source: str = "tick" # 캔들 소스 (tick/minute)
    minutes_per_candle: int = 1 # 분봉 캔들 분 단위
    minute_backfill_tick_size: int = 20 # 분봉 전환 시 RSI 워밍업용 틱봉 크기
    minute_backfill_candle_count: int = 20 # 분봉 전환 시 RSI 워밍업용 틱봉 개수
    minute_backfill_tick_buffer_size: int = 800 # 코드별 최근 틱 버퍼 최대 저장 개수
    minute_default_rsi_period: int = 9 # 분봉 전환 시 기본 RSI 기간
    minute_default_rsi_overbought: float = 70.0 # 분봉 전환 시 기본 RSI 과매수 기준
    minute_default_rsi_sell_half: float = 59.0 # 분봉 전환 시 기본 RSI 부분 매도 기준
    minute_default_rsi_sell_all: float = 39.0 # 분봉 전환 시 기본 RSI 전량 매도 기준
    minute_default_livermore_period: int = 3 # 분봉 전환 시 기본 Livermore 돌파/이탈 캔들 수
    tick_default_livermore_period: int = 60 # 틱봉 전환 시 기본 Livermore 돌파/이탈 캔들 수
    rsi_period: int = 14 # RSI 기간
    rsi_overbought: float = 70.0 # RSI 과매수 기준
    rsi_sell_half: float = 39.0 # RSI 부분 매도 기준
    rsi_sell_all: float = 29.0 # RSI 전량 매도 기준
    grid_step_percent: float = 1.3 # 그리드 상승 퍼센트
    rsi_stage_multipliers: List[float] = field(default_factory=lambda: [1.0, 1.0, 0.8, 0.6, 0.4, 0.2]) # RSI 단계별 비중 배수
    rsi_pyramiding_enabled: bool = True # RSI 추가매수 피라미딩 사용 여부
    rsi_entry_atr_mult: float = 1.0 # RSI 첫 진입 ATR 배수
    rsi_add_atr_mult: float = 1.0 # RSI 추가매수 ATR 배수
    rsi_atr_trailing_mult: float = 2.5 # RSI ATR 트레일링 배수
    rsi_atr_buffer_mult: float = 0.5 # RSI ATR 청산 버퍼(추가 배수)
    rsi_atr_period: int = 14 # RSI ATR 계산 기간
    rsi_profit_protect_atr_mult: float = 1.0 # RSI 수익권 진입 후 ATR 보호막 활성화 배수
    rsi_use_adx_filter: bool = False # RSI 첫 진입 ADX 필터 사용 여부
    rsi_adx_period: int = 14 # RSI 첫 진입 ADX 기간
    rsi_adx_threshold: float = 25.0 # RSI 첫 진입 ADX 기준값
    rsi_use_cci_filter: bool = False # RSI 진입/추가매수 CCI 필터 사용 여부
    rsi_cci_period: int = 20 # RSI CCI 계산 기간
    rsi_cci_entry_threshold: float = 0.0 # RSI 첫 진입 CCI 기준값
    rsi_cci_add_threshold: float = 100.0 # RSI 추가매수 CCI 기준값
    strategy_name: str = "rsi_grid" # 매매 전략 이름
    donchian_breakout_period: int = 20 # Donchian 상단 돌파 진입 기간
    donchian_exit_period: int = 10 # Donchian 하단 이탈 청산 기간
    livermore_breakout_period: int = 5 # Livermore 진입 Donchian 기간
    livermore_exit_period: int = 5 # Livermore 청산 Donchian 기간
    livermore_add_atr_mult: float = 1.8 # Livermore 추가매수 ATR 배수
    livermore_add_min_hoga_gap: int = 5 # Livermore 추가매수 최소 호가 간격
    livermore_atr_trailing_mult: float = 2.5 # Livermore ATR 트레일링 배수
    livermore_atr_buffer_mult: float = 0.5 # Livermore ATR 청산 버퍼(추가 배수)
    livermore_exit_confirm_bars: int = 2 # Livermore 청산 연속 확인 봉 수
    livermore_donchian_exit_ratio: float = 0.5 # Livermore Donchian 부분청산 비율
    livermore_use_adx_filter: bool = True # Livermore 첫 진입 ADX 상승/강세 필터 사용 여부
    livermore_adx_period: int = 14 # Livermore 진입 필터용 ADX 기간
    livermore_adx_threshold: float = 25.0 # Livermore 진입 필터용 ADX 기준값
    livermore_use_cci_filter: bool = True # Livermore 진입/추가매수 CCI 필터 사용 여부
    livermore_cci_period: int = 14 # Livermore CCI 기간
    livermore_cci_entry_threshold: float = 80.0 # Livermore 진입용 CCI 기준값
    livermore_cci_add_threshold: float = 100.0 # Livermore 추가매수용 CCI 기준값
    pullback_retrace_atr_mult: float = 0.8 # 눌림목 판단용 최소 ATR 되돌림 배수
    pullback_rebreak_buffer_atr_mult: float = 0.2 # 재돌파 확인용 ATR 버퍼 배수
    pullback_invalidate_atr_mult: float = 0.5 # 눌림 실패 무효화 ATR 배수
    pullback_max_bars: int = 6 # 눌림 후 재돌파 대기 최대 봉 수
    livermore_stage_multipliers: List[float] = field(default_factory=lambda: [1.0, 1.0, 0.8, 0.6, 0.4]) # 단계별 비중 배수
    livermore_pyramiding_enabled: bool = True # Livermore 추가매수 피라미딩 사용 여부
    livermore_retry_timeout_sec: float = 10.0 # Livermore 미체결 재시도 대기 시간(초)
    livermore_retry_max: int = 1 # Livermore 단계별 최대 재시도 횟수
    failure_buy_rsi: float = 30.0 # Failure Swing 매수 기준
    failure_sell_rsi: float = 70.0 # Failure Swing 매도 기준
    buy_cash: int = 1_000_000 # 종목별 매수 금액
    buy_size_mode: str = "cash" # 매수 주문 크기 모드(cash/qty)
    buy_qty: int = 0 # 매수 고정 수량(모드가 qty일 때 사용)
    sell_size_mode: str = "qty" # 매도 주문 크기 모드(cash/qty)
    sell_cash: int = 0 # 매도 금액(모드가 cash일 때 사용)
    sell_qty: int = 0 # 매도 고정 수량(모드가 qty일 때 사용)
    cooldown_seconds: int = 10 # 매수/매도 쿨다운 시간(초)
    fee_rate: float = 0.00015 # 수수료율
    order_screen: str = "6000"
    order_hoga_gb: str = "00" # 주문 호가 구분 ("00": 지정가, "03": 시장가)
    order_hoga_offset_levels: int = 5
    real_screen: str = "5000"
    real_fids: List[str] = field(default_factory=lambda: ["10"]) # 실시간 현재가만 수신하고 시간은 로컬 시계로 보정
    market_start: str = "09:00"
    market_end: str = "15:30"
    market_timezone: str = "Asia/Seoul"
    log_file: str = "logs/bot_{date}.log"
    daily_trade_log_file: str = "logs/trades_{date}.log"
    log_level: str = "INFO"
    simple_log_enabled: bool = False # 간편 로그 모드(파일에는 경고/에러 중심 저장)
    simple_log_level: str = "WARNING" # 간편 로그 파일 최소 레벨
    log_max_bytes: int = 1_000_000 # 회전 로그 파일 최대 크기(byte)
    log_backup_count: int = 3 # 회전 로그 보관 파일 개수
    chejan_log_enabled: bool = True # CHEJAN 원본 이벤트 파일 저장 여부
    ui_enabled: bool = True
    ui_refresh_ms: int = 500
    realtime_poll_sleep_sec: float = 0.01
    tick_compute_sleep_sec: float = 0.001
    tick_compute_batch_size: int = 1000
    tick_queue_maxsize: int = 50000
    tick_compute_shard_count: int = 20 # 틱 연산 샤드 큐 개수(기본 워커 수와 동일)
    queue_policy_mode: str = "hybrid" # 큐 정책 모드(hybrid/legacy_single_queue)
    tick_queue_soft_ratio: float = 0.80 # 틱 큐 소프트 임계 사용률
    tick_queue_hard_ratio: float = 0.95 # 틱 큐 하드 임계 사용률
    tick_queue_overload_wait_ms: float = 5.0 # 틱 큐 과부하 시 enqueue 대기 시간(ms)
    tick_queue_emergency_drop_batch: int = 20 # 틱 큐 긴급 드롭 개수
    real_ingress_soft_ratio: float = 0.80 # ingress 소프트 임계 사용률
    real_ingress_hard_ratio: float = 0.95 # ingress 하드 임계 사용률
    legacy_single_queue: bool = False # 기존 단일 틱 큐 경로 유지 여부
    api_rate_limit_per_sec: int = 4 # 하위호환용(legacy). 신규 설정은 tr/order 분리값을 사용
    global_rate_limit_per_sec: int = 4 # 전체 outbound 요청 제한(초당)
    tr_rate_limit_per_sec: int = 4 # TR/조회/조건/실시간등록 요청 제한(초당)
    order_rate_limit_per_sec: int = 4 # 주문 요청 제한(초당)
    real_ingress_buffer_maxsize: int = 5000 # 게이트웨이 실시간 ingress 버퍼 최대 길이
    real_ingress_drain_batch: int = 500 # 엔진 1회 루프에서 ingress 배치 드레인 개수
    ui_realtime_warn_queue_ratio: float = 0.7 # 실시간 상태 경고 큐 사용률 기준
    ui_realtime_warn_drop_count: int = 1 # 실시간 상태 경고 드롭 누적 기준
    ui_realtime_warn_limit_wait_ms: float = 200.0 # 실시간 상태 경고 레이트리밋 대기시간 기준(ms)
    real_reg_min_interval_sec: float = 0.5
    tick_log_interval_sec: float = 10.0
    tick_missing_threshold_sec: float = 5.0
    tick_missing_log_interval_sec: float = 30.0
    tick_start_log_enabled: bool = True
    account_refresh_seconds: float = 30.0
    holdings_refresh_seconds: float = 30.0
    holdings_force_min_interval_sec: float = 0.5
    reset_rsi_on_untrack: bool = False
    volatility_period: int = 14 # 변동성 계산 기간
    volatility_threshold: float = 1.5 # 변동성 중단값 (%) - 이 이상이면 추세 강한 것으로 그리드 우선
    adaptive_scalp_lookback: int = 3 # adaptive 스켈핑 최근 고점 돌파 확인 봉 수
    adaptive_scalp_breakout_buffer_pct: float = 0.10 # adaptive 스켈핑 고점 돌파 여유(%)
    adaptive_scalp_min_momentum_bars: int = 2 # adaptive 스켈핑 연속 상승 확인 봉 수
    adaptive_scalp_min_volatility_pct: float = 0.08 # adaptive 스켈핑 최소 변동성(%)
    adaptive_scalp_max_chase_atr_mult: float = 2.5 # adaptive 스켈핑 과도한 추격매수 제한 ATR 배수
    adaptive_scalp_stop_atr_mult: float = 1.4 # adaptive 스켈핑 손절 ATR 배수
    adaptive_scalp_trailing_atr_mult: float = 2.0 # adaptive 스켈핑 트레일링 ATR 배수
    adaptive_scalp_trailing_arm_atr_mult: float = 1.0 # adaptive 트레일링 활성화 최소 수익 ATR 배수
    adaptive_scalp_take_profit_atr_mult: float = 2.6 # adaptive 스켈핑 익절 ATR 배수
    adaptive_scalp_take_profit_pct: float = 1.6 # adaptive 스켈핑 최소 익절률(%)
    tick_compute_worker_count: int = 20 # 틱 처리 멀티워커 개수
    adx_period: int = 14 # ADX 계산 기간
    adx_threshold: float = 25.0 # ADX 기준값 (강한 추세 필터)
    adx_weak_threshold: float = 18.0 # ADX 약세 청산 기준값
    adx_exit_falling_bars: int = 3 # ADX 연속 하락 청산 캔들 수
    adx_use_weak_exit: bool = False # ADX 약세 강제청산 사용 여부
    atr_trailing_mult: float = 2.5 # ATR 트레일링 스탑 배수
    rsi_trace_log_enabled: bool = False # RSI/신호 상세 추적 로그 사용 여부

    @classmethod
    def load(cls, path: str) -> "Settings":
        """JSON 파일에서 설정을 읽어온다."""
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except FileNotFoundError:
            return cls()

        base = cls()
        legacy_api_limit = data.get("api_rate_limit_per_sec", None)
        has_tr_limit = "tr_rate_limit_per_sec" in data
        has_global_limit = "global_rate_limit_per_sec" in data
        for key, value in data.items():
            if hasattr(base, key):
                setattr(base, key, value)
        if legacy_api_limit is not None and not has_tr_limit:
            # 과거 단일 제한값(api_rate_limit_per_sec)을 신규 TR 제한값으로 흡수한다.
            base.tr_rate_limit_per_sec = int(legacy_api_limit)
        if legacy_api_limit is not None and not has_global_limit:
            # 과거 단일 제한값(api_rate_limit_per_sec)을 글로벌 제한값으로 흡수한다.
            base.global_rate_limit_per_sec = int(legacy_api_limit)
        return base

    def save(self, path: str) -> None:
        """현재 설정을 JSON 파일로 저장한다."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    def to_dict(self) -> Dict[str, Any]:
        """설정을 딕셔너리로 변환한다."""
        return {
            "mode": self.mode,
            "account_password": self.account_password,
            "condition_index": self.condition_index,
            "condition_refresh_seconds": self.condition_refresh_seconds,
            "condition_screen": self.condition_screen,
            "max_total_symbols": self.max_total_symbols,
            "watchlist_include_holdings": self.watchlist_include_holdings,
            "excluded_codes": self.excluded_codes,
            "ticks_per_candle": self.ticks_per_candle,
            "candle_source": self.candle_source,
            "minutes_per_candle": self.minutes_per_candle,
            "minute_backfill_tick_size": self.minute_backfill_tick_size,
            "minute_backfill_candle_count": self.minute_backfill_candle_count,
            "minute_backfill_tick_buffer_size": self.minute_backfill_tick_buffer_size,
            "minute_default_rsi_period": self.minute_default_rsi_period,
            "minute_default_rsi_overbought": self.minute_default_rsi_overbought,
            "minute_default_rsi_sell_half": self.minute_default_rsi_sell_half,
            "minute_default_rsi_sell_all": self.minute_default_rsi_sell_all,
            "minute_default_livermore_period": getattr(self, "minute_default_livermore_period", 5),
            "tick_default_livermore_period": getattr(self, "tick_default_livermore_period", 30),
            "rsi_period": self.rsi_period,
            "rsi_overbought": self.rsi_overbought,
            "rsi_sell_half": self.rsi_sell_half,
            "rsi_sell_all": self.rsi_sell_all,
            "grid_step_percent": self.grid_step_percent,
            "rsi_stage_multipliers": self.rsi_stage_multipliers,
            "rsi_pyramiding_enabled": self.rsi_pyramiding_enabled,
            "rsi_entry_atr_mult": self.rsi_entry_atr_mult,
            "rsi_add_atr_mult": self.rsi_add_atr_mult,
            "rsi_atr_trailing_mult": self.rsi_atr_trailing_mult,
            "rsi_atr_buffer_mult": self.rsi_atr_buffer_mult,
            "rsi_atr_period": self.rsi_atr_period,
            "rsi_profit_protect_atr_mult": self.rsi_profit_protect_atr_mult,
            "rsi_use_adx_filter": self.rsi_use_adx_filter,
            "rsi_adx_period": self.rsi_adx_period,
            "rsi_adx_threshold": self.rsi_adx_threshold,
            "rsi_use_cci_filter": self.rsi_use_cci_filter,
            "rsi_cci_period": self.rsi_cci_period,
            "rsi_cci_entry_threshold": self.rsi_cci_entry_threshold,
            "rsi_cci_add_threshold": self.rsi_cci_add_threshold,
            "strategy_name": self.strategy_name,
            "donchian_breakout_period": self.donchian_breakout_period,
            "donchian_exit_period": self.donchian_exit_period,
            "livermore_breakout_period": self.livermore_breakout_period,
            "livermore_exit_period": self.livermore_exit_period,
            "livermore_add_atr_mult": self.livermore_add_atr_mult,
            "livermore_add_min_hoga_gap": self.livermore_add_min_hoga_gap,
            "livermore_atr_trailing_mult": self.livermore_atr_trailing_mult,
            "livermore_atr_buffer_mult": self.livermore_atr_buffer_mult,
            "livermore_exit_confirm_bars": self.livermore_exit_confirm_bars,
            "livermore_donchian_exit_ratio": self.livermore_donchian_exit_ratio,
            "livermore_use_adx_filter": self.livermore_use_adx_filter,
            "livermore_adx_period": self.livermore_adx_period,
            "livermore_adx_threshold": self.livermore_adx_threshold,
            "livermore_use_cci_filter": self.livermore_use_cci_filter,
            "livermore_cci_period": self.livermore_cci_period,
            "livermore_cci_entry_threshold": self.livermore_cci_entry_threshold,
            "livermore_cci_add_threshold": self.livermore_cci_add_threshold,
            "pullback_retrace_atr_mult": self.pullback_retrace_atr_mult,
            "pullback_rebreak_buffer_atr_mult": self.pullback_rebreak_buffer_atr_mult,
            "pullback_invalidate_atr_mult": self.pullback_invalidate_atr_mult,
            "pullback_max_bars": self.pullback_max_bars,
            "livermore_stage_multipliers": self.livermore_stage_multipliers,
            "livermore_pyramiding_enabled": self.livermore_pyramiding_enabled,
            "livermore_retry_timeout_sec": self.livermore_retry_timeout_sec,
            "livermore_retry_max": self.livermore_retry_max,
            "failure_buy_rsi": self.failure_buy_rsi,
            "failure_sell_rsi": self.failure_sell_rsi,
            "buy_cash": self.buy_cash,
            "buy_size_mode": self.buy_size_mode,
            "buy_qty": self.buy_qty,
            "cooldown_seconds": self.cooldown_seconds,
            "fee_rate": self.fee_rate,
            "order_screen": self.order_screen,
            "order_hoga_gb": self.order_hoga_gb,
            "order_hoga_offset_levels": self.order_hoga_offset_levels,
            "real_screen": self.real_screen,
            "real_fids": self.real_fids,
            "market_start": self.market_start,
            "market_end": self.market_end,
            "market_timezone": self.market_timezone,
            "log_file": self.log_file,
            "daily_trade_log_file": self.daily_trade_log_file,
            "log_level": self.log_level,
            "simple_log_enabled": self.simple_log_enabled,
            "simple_log_level": self.simple_log_level,
            "log_max_bytes": self.log_max_bytes,
            "log_backup_count": self.log_backup_count,
            "chejan_log_enabled": self.chejan_log_enabled,
            "ui_enabled": self.ui_enabled,
            "ui_refresh_ms": self.ui_refresh_ms,
            "realtime_poll_sleep_sec": self.realtime_poll_sleep_sec,
            "tick_compute_sleep_sec": self.tick_compute_sleep_sec,
            "tick_compute_batch_size": self.tick_compute_batch_size,
            "tick_queue_maxsize": self.tick_queue_maxsize,
            "tick_compute_shard_count": self.tick_compute_shard_count,
            "queue_policy_mode": self.queue_policy_mode,
            "tick_queue_soft_ratio": self.tick_queue_soft_ratio,
            "tick_queue_hard_ratio": self.tick_queue_hard_ratio,
            "tick_queue_overload_wait_ms": self.tick_queue_overload_wait_ms,
            "tick_queue_emergency_drop_batch": self.tick_queue_emergency_drop_batch,
            "real_ingress_soft_ratio": self.real_ingress_soft_ratio,
            "real_ingress_hard_ratio": self.real_ingress_hard_ratio,
            "legacy_single_queue": self.legacy_single_queue,
            "global_rate_limit_per_sec": self.global_rate_limit_per_sec,
            "tr_rate_limit_per_sec": self.tr_rate_limit_per_sec,
            "order_rate_limit_per_sec": self.order_rate_limit_per_sec,
            "real_ingress_buffer_maxsize": self.real_ingress_buffer_maxsize,
            "real_ingress_drain_batch": self.real_ingress_drain_batch,
            "ui_realtime_warn_queue_ratio": self.ui_realtime_warn_queue_ratio,
            "ui_realtime_warn_drop_count": self.ui_realtime_warn_drop_count,
            "ui_realtime_warn_limit_wait_ms": self.ui_realtime_warn_limit_wait_ms,
            "real_reg_min_interval_sec": self.real_reg_min_interval_sec,
            "tick_log_interval_sec": self.tick_log_interval_sec,
            "tick_missing_threshold_sec": self.tick_missing_threshold_sec,
            "tick_missing_log_interval_sec": self.tick_missing_log_interval_sec,
            "tick_start_log_enabled": self.tick_start_log_enabled,
            "account_refresh_seconds": self.account_refresh_seconds,
            "holdings_refresh_seconds": self.holdings_refresh_seconds,
            "holdings_force_min_interval_sec": self.holdings_force_min_interval_sec,
            "reset_rsi_on_untrack": self.reset_rsi_on_untrack,
            "volatility_period": self.volatility_period,
            "volatility_threshold": self.volatility_threshold,
            "adaptive_scalp_lookback": self.adaptive_scalp_lookback,
            "adaptive_scalp_breakout_buffer_pct": self.adaptive_scalp_breakout_buffer_pct,
            "adaptive_scalp_min_momentum_bars": self.adaptive_scalp_min_momentum_bars,
            "adaptive_scalp_min_volatility_pct": self.adaptive_scalp_min_volatility_pct,
            "adaptive_scalp_max_chase_atr_mult": self.adaptive_scalp_max_chase_atr_mult,
            "adaptive_scalp_stop_atr_mult": self.adaptive_scalp_stop_atr_mult,
            "adaptive_scalp_trailing_atr_mult": self.adaptive_scalp_trailing_atr_mult,
            "adaptive_scalp_trailing_arm_atr_mult": self.adaptive_scalp_trailing_arm_atr_mult,
            "adaptive_scalp_take_profit_atr_mult": self.adaptive_scalp_take_profit_atr_mult,
            "adaptive_scalp_take_profit_pct": self.adaptive_scalp_take_profit_pct,
            "tick_compute_worker_count": self.tick_compute_worker_count,
            "adx_period": self.adx_period,
            "adx_threshold": self.adx_threshold,
            "adx_weak_threshold": self.adx_weak_threshold,
            "adx_exit_falling_bars": self.adx_exit_falling_bars,
            "adx_use_weak_exit": self.adx_use_weak_exit,
            "atr_trailing_mult": self.atr_trailing_mult,
            "rsi_trace_log_enabled": self.rsi_trace_log_enabled,
        }
