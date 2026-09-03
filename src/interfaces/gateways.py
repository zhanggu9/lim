from __future__ import annotations

from typing import List, Optional, Protocol, Dict, Any


class BrokerGateway(Protocol):
    """브로커(키움) 연동 인터페이스를 정의한다."""

    def get_account_numbers(self) -> List[str]:
        """계좌 번호 목록을 반환한다."""
        raise NotImplementedError

    def get_server_gubun(self) -> str:
        """모의/실전 서버 구분 값을 반환한다."""
        raise NotImplementedError

    def request_holdings(self, account_no: str, password: str) -> Dict[str, Dict[str, int]]:
        """보유 종목 정보를 조회한다."""
        raise NotImplementedError

    def request_order_history(self, account_no: str, password: str) -> Optional[list]:
        """계좌의 주문/체결 이력을 조회한다(선택적). 구현체가 없으면 None을 반환할 수 있음."""
        raise NotImplementedError

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
        """주문을 전송한다."""
        raise NotImplementedError

    def get_master_code_name(self, code: str) -> str:
        """종목코드로 종목명을 반환한다."""
        raise NotImplementedError

    def request_deposit(self, account_no: str, password: str) -> Dict[str, int]:
        """예수금/출금가능/주문가능 금액을 조회한다."""
        raise NotImplementedError

    def request_account_summary(self, account_no: str, password: str) -> Dict[str, float]:
        """계좌 평가 요약 정보를 조회한다."""
        raise NotImplementedError


class ConditionGateway(Protocol):
    """조건식 검색 관련 인터페이스를 정의한다."""

    def get_condition_name_list(self) -> str:
        """조건식 목록 문자열을 반환한다."""
        raise NotImplementedError

    def send_condition(self, screen: str, cond_name: str, index: int, search: int) -> None:
        """조건식을 전송한다."""
        raise NotImplementedError

    def stop_condition(self, screen: str, cond_name: str, index: int) -> None:
        """조건식 검색을 중지한다."""
        raise NotImplementedError

    def get_tr_condition(self) -> Optional[Dict[str, Any]]:
        """조건식 TR 결과를 반환한다."""
        raise NotImplementedError

    def get_real_condition(self) -> Optional[Dict[str, Any]]:
        """실시간 조건식 편입/이탈 이벤트를 반환한다."""
        raise NotImplementedError


class MarketDataGateway(Protocol):
    """실시간 체결 데이터 인터페이스를 정의한다."""

    def set_real_reg(self, screen: str, codes: List[str], fids: List[str], opt_type: int) -> None:
        """실시간 등록을 수행한다."""
        raise NotImplementedError

    def disconnect_real(self, screen: str) -> None:
        """실시간 등록을 해제한다."""
        raise NotImplementedError

    def get_real_data(self) -> Optional[Dict[str, Any]]:
        """실시간 체결 데이터를 반환한다."""
        raise NotImplementedError

    def request_tick_history(self, code: str, count: int = 1200) -> List[Dict[str, Any]]:
        """과거 틱 데이터를 조회한다."""
        raise NotImplementedError

    def request_minute_history(self, code: str, interval: int = 1, count: int = 20) -> List[Dict[str, Any]]:
        """과거 분봉 데이터를 조회한다."""
        raise NotImplementedError


class ChejanGateway(Protocol):
    """체결/잔고 이벤트 인터페이스를 정의한다."""

    def get_chejan_data(self) -> Optional[Dict[str, Any]]:
        """체결/잔고 이벤트 데이터를 반환한다."""
        raise NotImplementedError
