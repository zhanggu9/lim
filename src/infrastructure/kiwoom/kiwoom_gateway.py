from __future__ import annotations

import queue
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

import pandas as pd
import pykiwoom

from infrastructure.kiwoom.kiwoom_parser import clean_float, clean_int, normalize_code
from infrastructure.kiwoom.outbound_dispatcher import OutboundDispatcher
from infrastructure.kiwoom.rate_limiter import AsyncRateLimiter
from interfaces.gateways import BrokerGateway, ChejanGateway, ConditionGateway, MarketDataGateway


class PyKiwoomGateway(BrokerGateway, ConditionGateway, MarketDataGateway, ChejanGateway):
    """pykiwoom 기반 OpenAPI 게이트웨이."""

    def __init__(self, logger, settings=None) -> None:
        self._logger = logger
        self._manager = pykiwoom.KiwoomManager()
        self._settings = settings

        legacy_limit = int(getattr(settings, "api_rate_limit_per_sec", 4)) if settings else 4
        tr_limit = int(getattr(settings, "tr_rate_limit_per_sec", legacy_limit)) if settings else legacy_limit
        order_limit = int(getattr(settings, "order_rate_limit_per_sec", legacy_limit)) if settings else legacy_limit
        global_limit = int(getattr(settings, "global_rate_limit_per_sec", legacy_limit)) if settings else legacy_limit

        self._tr_rate_limiter = AsyncRateLimiter(max_calls=tr_limit, period_sec=1.0)
        self._order_rate_limiter = AsyncRateLimiter(max_calls=order_limit, period_sec=1.0)
        self._global_rate_limiter = AsyncRateLimiter(max_calls=global_limit, period_sec=1.0)
        self._dispatcher = OutboundDispatcher(
            tr_limiter=self._tr_rate_limiter,
            order_limiter=self._order_rate_limiter,
            global_limiter=self._global_rate_limiter,
        )

        self._real_ingress_maxsize = max(
            1,
            int(getattr(settings, "real_ingress_buffer_maxsize", 5000)) if settings else 5000,
        )
        self._queue_policy_mode = (
            str(getattr(settings, "queue_policy_mode", "hybrid") or "hybrid").lower()
            if settings
            else "hybrid"
        )
        self._real_ingress_soft_ratio = min(
            0.99,
            max(0.05, float(getattr(settings, "real_ingress_soft_ratio", 0.80)) if settings else 0.80),
        )
        self._real_ingress_hard_ratio = min(
            1.0,
            max(
                self._real_ingress_soft_ratio,
                float(getattr(settings, "real_ingress_hard_ratio", 0.95)) if settings else 0.95,
            ),
        )
        self._real_ingress_emergency_drop_batch = max(
            1,
            int(getattr(settings, "tick_queue_emergency_drop_batch", 20)) if settings else 20,
        )
        self._real_ingress: Deque[Dict[str, Any]] = deque()
        self._real_ingress_lock = threading.Lock()
        self._real_ingress_drop_count = 0
        self._last_real_ingress_drop_log_ts = 0.0

    def get_account_numbers(self) -> List[str]:
        accounts = self._dispatch_tr(lambda: self._call_method(("GetLoginInfo", "ACCNO")))
        return list(accounts or [])

    def get_server_gubun(self) -> str:
        value = self._dispatch_tr(lambda: self._call_method(("GetLoginInfo", "GetServerGubun")))
        return str(value or "").strip()

    def request_holdings(self, account_no: str, password: str) -> Dict[str, Dict[str, int]]:
        holdings: Dict[str, Dict[str, int]] = {}
        next_flag = "0"
        while True:
            tr_cmd = {
                "rqname": "opw00018_req",
                "trcode": "opw00018",
                "next": next_flag,
                "screen": "0111",
                "input": {
                    "계좌번호": account_no,
                    "비밀번호": password or "0000",
                    "비밀번호입력매체구분": "00",
                    "조회구분": "2",
                },
                "output": ["종목번호", "종목명", "보유수량", "매도가능수량", "매입가"],
            }
            data, remain = self._dispatch_tr(lambda cmd=tr_cmd: self._call_tr(cmd))
            if isinstance(data, pd.DataFrame):
                for _, row in data.iterrows():
                    code = normalize_code(row.get("종목번호", ""))
                    if not code:
                        continue
                    holdings[code] = {
                        "qty": clean_int(row.get("보유수량", 0)),
                        "sellable": clean_int(row.get("매도가능수량", 0)),
                        "avg_price": clean_int(row.get("매입가", 0)),
                        "name": str(row.get("종목명", "") or "").strip(),
                    }
            if remain == 1:
                next_flag = "2"
                continue
            break
        return holdings

    def send_order(
        self,
        rqname: str,
        screen: str,
        acc_no: str,
        order_type: int,
        code: str,
        quantity: int,
        price: int,
        hoga_gb: str,
        order_no: str = "",
    ) -> None:
        cmd = {
            "rqname": rqname,
            "screen": screen,
            "acc_no": acc_no,
            "order_type": order_type,
            "code": code,
            "quantity": quantity,
            "price": price,
            "hoga_gb": hoga_gb,
            "order_no": order_no,
        }
        self._dispatch_order(lambda: self._manager.put_order(cmd))

    def get_master_code_name(self, code: str) -> str:
        if not code:
            return ""
        value = self._dispatch_tr(lambda: self._call_method(("GetMasterCodeName", code)))
        return str(value or "").strip()

    def request_deposit(self, account_no: str, password: str) -> Dict[str, int]:
        tr_cmd = {
            "rqname": "opw00001_req",
            "trcode": "opw00001",
            "next": "0",
            "screen": "0101",
            "input": {
                "계좌번호": account_no,
                "비밀번호": password or "0000",
                "비밀번호입력매체구분": "00",
                "조회구분": "1",
            },
            "output": ["예수금", "출금가능금액", "주문가능금액", "D+2추정예수금"],
        }
        data, _ = self._dispatch_tr(lambda: self._call_tr(tr_cmd))
        result: Dict[str, int] = {}
        if isinstance(data, pd.DataFrame) and not data.empty:
            row = data.iloc[0]
            result["deposit"] = clean_int(row.get("예수금", 0))
            result["withdrawable"] = clean_int(row.get("출금가능금액", 0))
            result["orderable"] = clean_int(row.get("주문가능금액", 0))
            result["d2_deposit"] = clean_int(row.get("D+2추정예수금", 0))
        return result

    def request_account_summary(self, account_no: str, password: str) -> Dict[str, float]:
        tr_cmd = {
            "rqname": "opw00018_sum_req",
            "trcode": "opw00018",
            "next": "0",
            "screen": "0112",
            "input": {
                "계좌번호": account_no,
                "비밀번호": password or "0000",
                "비밀번호입력매체구분": "00",
                "조회구분": "2",
            },
            "output": ["총매입금액", "총평가손익금액", "총수익률(%)"],
        }
        data, _ = self._dispatch_tr(lambda: self._call_tr(tr_cmd))
        result: Dict[str, float] = {}
        if isinstance(data, pd.DataFrame) and not data.empty:
            row = data.iloc[0]
            result["total_buy"] = float(clean_int(row.get("총매입금액", 0)))
            result["total_profit"] = float(clean_int(row.get("총평가손익금액", 0)))
            result["total_profit_rate"] = clean_float(row.get("총수익률(%)", 0))
        return result

    def get_condition_name_list(self):
        self._dispatch_tr(lambda: self._call_method(("GetConditionLoad", True)))
        result = ""
        for _ in range(3):
            result = self._dispatch_tr(lambda: self._call_cond_method({"func_name": "GetConditionNameList"}))
            if result:
                break
            time.sleep(0.3)
        return result

    def send_condition(self, screen: str, cond_name: str, index: int, search: int) -> None:
        cmd = {
            "func_name": "SendCondition",
            "screen": screen,
            "cond_name": cond_name,
            "index": index,
            "search": search,
        }
        self._dispatch_tr(lambda: self._manager.put_cond(cmd))

    def stop_condition(self, screen: str, cond_name: str, index: int) -> None:
        cmd = {"func_name": "SendConditionStop", "screen": screen, "cond_name": cond_name, "index": index}
        self._dispatch_tr(lambda: self._manager.put_cond(cmd))

    def get_tr_condition(self) -> Optional[Dict[str, Any]]:
        return self._try_get(self._manager.tr_cond_dqueue)

    def get_real_condition(self) -> Optional[Dict[str, Any]]:
        return self._try_get(self._manager.real_cond_dqueue)

    def set_real_reg(self, screen: str, codes: List[str], fids: List[str], opt_type: int) -> None:
        cmd = {
            "func_name": "SetRealReg",
            "screen": screen,
            "code_list": codes,
            "fid_list": fids,
            "opt_type": opt_type,
        }
        self._dispatch_tr(lambda: self._manager.put_real(cmd))

    def disconnect_real(self, screen: str) -> None:
        cmd = {"func_name": "DisConnectRealData", "screen": screen}
        self._dispatch_tr(lambda: self._manager.put_real(cmd))

    def drain_real_data(self, max_items: int) -> List[Dict[str, Any]]:
        target = max(1, int(max_items))
        self._pump_real_queue()
        drained: List[Dict[str, Any]] = []
        with self._real_ingress_lock:
            for _ in range(min(target, len(self._real_ingress))):
                drained.append(self._real_ingress.popleft())
        return drained

    def get_real_data(self) -> Optional[Dict[str, Any]]:
        items = self.drain_real_data(1)
        return items[0] if items else None

    def get_real_ingress_size(self) -> int:
        self._pump_real_queue()
        with self._real_ingress_lock:
            return len(self._real_ingress)

    def request_tick_history(self, code: str, count: int = 1200) -> List[Dict[str, Any]]:
        """과거 틱 데이터를 조회한다(최대 1200개)."""
        tr_cmd = {
            "rqname": "opt10079_req",
            "trcode": "opt10079",
            "next": "0",
            "screen": "0105",
            "input": {
                "종목코드": code,
                "틱범위": "1",
                "수정주가구분": "1",
            },
            "output": ["현재가", "거래량", "체결시간"],
        }
        max_rows = max(1, int(count))
        records: List[Dict[str, Any]] = []
        next_flag = "0"
        while len(records) < max_rows:
            tr_cmd["next"] = next_flag
            data, remain = self._dispatch_tr(lambda cmd=dict(tr_cmd): self._call_tr(cmd))
            if isinstance(data, pd.DataFrame) and not data.empty:
                records.extend(data.to_dict("records"))
            if remain != 1 or not isinstance(data, pd.DataFrame) or data.empty:
                break
            next_flag = "2"
        if len(records) > max_rows:
            records = records[:max_rows]
        return records

    def request_minute_history(self, code: str, interval: int = 1, count: int = 20) -> List[Dict[str, Any]]:
        """과거 분봉 데이터를 연속조회로 가져온다."""
        max_rows = max(1, int(count))
        records: List[Dict[str, Any]] = []
        next_flag = "0"
        while len(records) < max_rows:
            tr_cmd = {
                "rqname": "opt10080_req",
                "trcode": "opt10080",
                "next": next_flag,
                "screen": "0106",
                "input": {
                    "종목코드": code,
                    "틱범위": str(max(1, int(interval))),
                    "수정주가구분": "1",
                },
                "output": ["체결시간", "시가", "고가", "저가", "현재가", "거래량"],
            }
            data, remain = self._dispatch_tr(lambda cmd=tr_cmd: self._call_tr(cmd))
            if isinstance(data, pd.DataFrame) and not data.empty:
                records.extend(data.to_dict("records"))
            if remain != 1 or not isinstance(data, pd.DataFrame) or data.empty:
                break
            next_flag = "2"
        if len(records) > max_rows:
            records = records[:max_rows]
        return records

    def get_real_ingress_drop_count(self) -> int:
        return int(self._real_ingress_drop_count)

    def get_rate_limit_wait_ms(self) -> Dict[str, float]:
        dispatcher = self._dispatcher
        return {
            "global": dispatcher._global_limiter.get_wait_ms_last_sec(1.0),
            "tr": dispatcher._tr_limiter.get_wait_ms_last_sec(1.0),
            "order": dispatcher._order_limiter.get_wait_ms_last_sec(1.0),
        }

    def get_chejan_data(self) -> Optional[Dict[str, Any]]:
        return self._try_get(self._manager.chejan_dqueue)

    def request_order_history(self, account_no: str, password: str) -> Optional[list]:
        tr_cmd = None
        try:
            tr_cmd = getattr(self._settings, "order_history_tr_cmd", None)
        except Exception:
            tr_cmd = None
        if not tr_cmd:
            self._logger.warning("order_history TR 명령이 설정되어 있지 않아 주문/체결 이력 조회를 건너뜁니다.")
            return []
        data, _ = self._dispatch_tr(lambda cmd=tr_cmd: self._call_tr(cmd))
        return data

    def close(self) -> None:
        self._dispatcher.close()

    def _dispatch_tr(self, action):
        return self._dispatcher.submit("tr", action)

    def _dispatch_order(self, action):
        return self._dispatcher.submit("order", action)

    def _call_method(self, payload):
        self._manager.put_method(payload)
        return self._manager.get_method()

    def _call_tr(self, cmd):
        self._manager.put_tr(cmd)
        return self._manager.get_tr()

    def _call_cond_method(self, cmd):
        self._manager.put_cond(cmd)
        return self._manager.get_cond(method=True)

    def _pump_real_queue(self) -> None:
        """Kiwoom manager 실시간 큐를 ingress 버퍼로 이동한다."""
        soft_mark = int(self._real_ingress_maxsize * self._real_ingress_soft_ratio)
        hard_mark = int(self._real_ingress_maxsize * self._real_ingress_hard_ratio)
        while True:
            if self._queue_policy_mode == "hybrid":
                with self._real_ingress_lock:
                    if len(self._real_ingress) >= soft_mark:
                        break
            data = self._try_get(self._manager.real_dqueues)
            if data is None:
                break
            with self._real_ingress_lock:
                current_size = len(self._real_ingress)
                if self._queue_policy_mode == "hybrid" and current_size >= hard_mark:
                    drop_count = min(self._real_ingress_emergency_drop_batch, current_size)
                    for _ in range(drop_count):
                        self._real_ingress.popleft()
                    self._real_ingress_drop_count += drop_count
                    self._log_real_ingress_drop(drop_count, len(self._real_ingress))
                elif current_size >= self._real_ingress_maxsize:
                    self._real_ingress.popleft()
                    self._real_ingress_drop_count += 1
                    self._log_real_ingress_drop(1, len(self._real_ingress))
                self._real_ingress.append(data)

    def _log_real_ingress_drop(self, dropped: int, current_size: int) -> None:
        now = time.monotonic()
        if now - self._last_real_ingress_drop_log_ts < 5.0:
            return
        self._logger.warning(
            "실시간 ingress 드롭: 이번=%d 누적=%d 버퍼=%d/%d",
            int(dropped),
            int(self._real_ingress_drop_count),
            int(current_size),
            int(self._real_ingress_maxsize),
        )
        self._last_real_ingress_drop_log_ts = now

    @staticmethod
    def _try_get(target_queue) -> Optional[Dict[str, Any]]:
        try:
            return target_queue.get_nowait()
        except queue.Empty:
            return None
