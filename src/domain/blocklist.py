"""
Blocklist 도메인 엔티티.

Clean Architecture의 Domain Layer로, 비즈니스 로직의 핵심을 담는다.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Set


@dataclass(frozen=True)
class ExcludedCode:
    """제외 종목을 나타내는 값 객체."""

    code: Optional[str] = None
    name: Optional[str] = None

    def __post_init__(self) -> None:
        """값을 정규화한다."""
        if self.code is None and self.name is None:
            raise ValueError("코드나 명칭 중 하나는 필수입니다.")

    @property
    def normalized_code(self) -> Optional[str]:
        """대문자로 정규화된 코드를 반환한다."""
        return self.code.upper() if self.code else None

    @property
    def normalized_name(self) -> Optional[str]:
        """공백이 제거된 명칭을 반환한다."""
        return self.name.strip() if self.name else None

    def __eq__(self, other: object) -> bool:
        """같은 코드나 명칭이면 같다."""
        if not isinstance(other, ExcludedCode):
            return False
        if self.normalized_code and other.normalized_code:
            return self.normalized_code == other.normalized_code
        if self.normalized_name and other.normalized_name:
            return self.normalized_name == other.normalized_name
        return False

    def __hash__(self) -> int:
        """해시값을 계산한다."""
        if self.normalized_code:
            return hash(self.normalized_code)
        if self.normalized_name:
            return hash(self.normalized_name)
        return hash((self.code, self.name))

    def __str__(self) -> str:
        """문자열 표현을 반환한다."""
        if self.code and self.name:
            return f"{self.code}({self.name})"
        return self.code or self.name or ""


class Blocklist:
    """제외 종목 목록을 관리하는 엔티티."""

    def __init__(self) -> None:
        """빈 Blocklist를 초기화한다."""
        self._codes: Set[ExcludedCode] = set()

    def add(self, excluded_code: ExcludedCode) -> None:
        """제외 종목을 추가한다. 중복은 무시된다."""
        if excluded_code not in self._codes:
            self._codes.add(excluded_code)

    def remove(self, excluded_code: ExcludedCode) -> None:
        """제외 종목을 제거한다."""
        self._codes.discard(excluded_code)

    def contains(self, code: Optional[str] = None, name: Optional[str] = None) -> bool:
        """코드나 명칭이 포함되어 있는지 확인한다."""
        if code:
            normalized = code.upper()
            return any(ec.normalized_code == normalized for ec in self._codes)
        if name:
            normalized = name.strip()
            return any(ec.normalized_name == normalized for ec in self._codes)
        return False

    def clear(self) -> None:
        """모든 제외 종목을 제거한다."""
        self._codes.clear()

    def is_empty(self) -> bool:
        """비어있는지 확인한다."""
        return len(self._codes) == 0

    def __len__(self) -> int:
        """제외 종목 개수를 반환한다."""
        return len(self._codes)

    def __contains__(self, excluded_code: ExcludedCode) -> bool:
        """포함 연산자를 구현한다."""
        return excluded_code in self._codes

    def __iter__(self):
        """반복 가능하게 만든다."""
        return iter(self._codes)

    def get_codes(self) -> List[str]:
        """코드로 된 리스트를 반환한다."""
        return [ec.code for ec in self._codes if ec.code]

    def get_names(self) -> List[str]:
        """명칭으로 된 리스트를 반환한다."""
        return [ec.name for ec in self._codes if ec.name]

    def to_csv(self) -> str:
        """CSV 문자열로 변환한다."""
        items = []
        for ec in self._codes:
            if ec.code:
                items.append(ec.code)
            if ec.name:
                items.append(ec.name)
        return ",".join(items)

    @staticmethod
    def from_csv(csv_string: str) -> Blocklist:
        """CSV 문자열로부터 Blocklist를 생성한다."""
        blocklist = Blocklist()
        if not csv_string or not csv_string.strip():
            return blocklist
        
        items = [item.strip() for item in csv_string.split(",") if item.strip()]
        for item in items:
            # 숫자로만 이루어진 항목은 코드, 한글이 있으면 명칭으로 판단
            if item.isalnum() and len(item) <= 6 and item.isdigit():
                blocklist.add(ExcludedCode(code=item))
            else:
                blocklist.add(ExcludedCode(name=item))
        
        return blocklist
