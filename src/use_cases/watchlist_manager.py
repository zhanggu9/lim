from __future__ import annotations

from typing import List, Set


class WatchlistManager:
    """조건식 종목과 보유 종목을 합쳐 감시 리스트를 관리한다."""

    def __init__(self, max_total: int, include_holdings: bool = True) -> None:
        """감시 리스트 제한 수를 초기화한다."""
        self._max_total = max_total
        self._include_holdings = bool(include_holdings)
        self._excluded: Set[str] = set()
        self._holdings: Set[str] = set()
        self._condition_set: Set[str] = set()
        self._tracked: List[str] = []

    def set_excluded_codes(self, codes: Set[str]) -> None:
        """감시/매매 제외 종목 코드를 설정한다."""
        normalized = {code for code in codes if code}
        self._excluded = normalized
        if not self._excluded:
            return
        self._holdings = {code for code in self._holdings if code not in self._excluded}
        self._condition_set = {code for code in self._condition_set if code not in self._excluded}
        self._tracked = [code for code in self._tracked if code not in self._excluded]

    def get_excluded_codes(self) -> Set[str]:
        """현재 제외 종목 집합을 반환한다."""
        return set(self._excluded)

    def update_holdings(self, codes: Set[str]) -> None:
        """보유 종목을 갱신하고 감시 리스트에 반영한다."""
        previous = set(self._holdings)
        self._holdings = {code for code in set(codes) if code and code not in self._excluded}
        if not self._include_holdings:
            # 보유 종목 자동 편입을 끈 경우, 감시 리스트는 조건식 종목만 유지한다.
            self._tracked = [code for code in self._tracked if code in self._condition_set]
            return
        removed = previous - self._holdings
        for code in removed:
            if code in self._tracked and code not in self._condition_set:
                self._tracked.remove(code)
        for code in self._holdings:
            if code not in self._tracked:
                self._tracked.append(code)
        self._trim_to_limit()

    def apply_condition_snapshot(self, codes) -> None:
        """조건식 전체 목록 스냅샷을 반영한다."""
        if isinstance(codes, (list, tuple)):
            ordered = [c for c in codes if c and c not in self._excluded]
        else:
            ordered = sorted({c for c in set(codes) if c and c not in self._excluded})
        new_set = set(ordered)
        removed = self._condition_set - new_set
        for code in removed:
            self.apply_condition_event(code, "D")
        for code in ordered:
            if code not in self._condition_set:
                self.apply_condition_event(code, "I")

    def apply_condition_event(self, code: str, event_type: str) -> None:
        """조건식 편입/이탈 이벤트를 반영한다."""
        if not code:
            return
        if code in self._excluded:
            self._condition_set.discard(code)
            if code in self._tracked:
                self._tracked.remove(code)
            return
        if event_type == "I":
            self._condition_set.add(code)
            if code in self._tracked:
                return
            if self._can_add(code):
                self._tracked.append(code)
        elif event_type == "D":
            self._condition_set.discard(code)
            if self._include_holdings and code in self._holdings:
                return
            if code in self._tracked:
                self._tracked.remove(code)

    def get_tracked_codes(self) -> List[str]:
        """현재 감시 중인 종목 리스트를 반환한다."""
        return list(self._tracked)

    def get_condition_codes(self) -> Set[str]:
        """현재 조건식에 편입된 종목 집합을 반환한다."""
        return set(self._condition_set)

    def reset_conditions(self) -> None:
        """조건식 집합을 초기화한다."""
        removed = set(self._condition_set)
        self._condition_set.clear()
        for code in removed:
            if self._include_holdings and code in self._holdings:
                continue
            if code in self._tracked:
                self._tracked.remove(code)

    def _can_add(self, code: str) -> bool:
        """감시 리스트에 종목을 추가할 수 있는지 확인한다."""
        if not self._include_holdings:
            return len(self._tracked) < max(0, self._max_total)
        if code in self._holdings:
            return True
        holdings_count = len(self._holdings)
        allowed = self._max_total - holdings_count
        non_holding_tracked = [c for c in self._tracked if c not in self._holdings]
        return len(non_holding_tracked) < max(0, allowed)

    def _trim_to_limit(self) -> None:
        """제한 초과 시 비보유 종목을 제거한다."""
        if len(self._tracked) <= self._max_total:
            return
        if not self._include_holdings:
            self._tracked = self._tracked[: self._max_total]
            return
        trimmed: List[str] = []
        for code in self._tracked:
            if code in self._holdings:
                trimmed.append(code)
        for code in self._tracked:
            if len(trimmed) >= self._max_total:
                break
            if code in self._holdings:
                continue
            if code in self._condition_set:
                trimmed.append(code)
        self._tracked = trimmed
