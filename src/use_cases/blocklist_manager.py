"""
Blocklist Manager Use Case.

Clean Architecture의 Use Cases Layer로, 비즈니스 로직을 조율한다.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Optional

from domain.blocklist import Blocklist, ExcludedCode


class BlocklistRepository(ABC):
    """Blocklist 저장소 인터페이스."""

    @abstractmethod
    def save(self, csv_string: str) -> None:
        """CSV 형식으로 저장한다."""
        pass

    @abstractmethod
    def load(self) -> str:
        """저장된 CSV를 로드한다."""
        pass


class BlocklistObserver(ABC):
    """Blocklist 변경 옵저버 인터페이스."""

    @abstractmethod
    def on_blocklist_changed(self, blocklist: Blocklist) -> None:
        """Blocklist가 변경되었을 때 호출된다."""
        pass

    @abstractmethod
    def on_code_added(self, excluded_code: ExcludedCode) -> None:
        """종목이 추가되었을 때 호출된다."""
        pass

    @abstractmethod
    def on_code_removed(self, excluded_code: ExcludedCode) -> None:
        """종목이 제거되었을 때 호출된다."""
        pass


class BlocklistManager:
    """Blocklist를 관리하는 유즈 케이스."""

    def __init__(self, repository: BlocklistRepository) -> None:
        """BlocklistManager를 초기화한다."""
        self._blocklist = Blocklist()
        self._repository = repository
        self._observers: List[BlocklistObserver] = []

    @property
    def repo(self) -> BlocklistRepository:
        """Repository를 반환한다."""
        return self._repository

    def subscribe(self, observer: BlocklistObserver) -> None:
        """옵저버를 등록한다."""
        if observer not in self._observers:
            self._observers.append(observer)

    def unsubscribe(self, observer: BlocklistObserver) -> None:
        """옵저버를 등록 해제한다."""
        self._observers.discard(observer)

    def add_code(self, code: str) -> None:
        """코드를 추가한다."""
        excluded_code = ExcludedCode(code=code)
        self._blocklist.add(excluded_code)
        self._notify_all()
        self._notify_added(excluded_code)
        self.save()

    def add_name(self, name: str) -> None:
        """명칭을 추가한다."""
        excluded_code = ExcludedCode(name=name)
        self._blocklist.add(excluded_code)
        self._notify_all()
        self._notify_added(excluded_code)
        self.save()

    def remove_code(self, code: str) -> None:
        """코드를 제거한다."""
        # 코드로 찾아서 제거
        to_remove = None
        for ec in self._blocklist:
            if ec.normalized_code == code.upper():
                to_remove = ec
                break
        if to_remove:
            self._blocklist.remove(to_remove)
            self._notify_all()
            self._notify_removed(to_remove)
            self.save()

    def remove_name(self, name: str) -> None:
        """명칭을 제거한다."""
        # 명칭으로 찾아서 제거
        to_remove = None
        for ec in self._blocklist:
            if ec.normalized_name == name.strip():
                to_remove = ec
                break
        if to_remove:
            self._blocklist.remove(to_remove)
            self._notify_all()
            self._notify_removed(to_remove)
            self.save()

    def is_blocked(self, code: Optional[str] = None, name: Optional[str] = None) -> bool:
        """코드나 명칭이 차단되어 있는지 확인한다."""
        return self._blocklist.contains(code=code, name=name)

    def clear(self) -> None:
        """모든 차단 종목을 제거한다."""
        self._blocklist.clear()
        self._notify_all()
        self.save()

    def load(self) -> None:
        """Repository에서 로드한다."""
        csv = self._repository.load()
        self.load_from_csv(csv)

    def load_from_csv(self, csv_string: str) -> None:
        """CSV 문자열로부터 로드한다."""
        self._blocklist = Blocklist.from_csv(csv_string)
        self._notify_all()

    def save(self) -> None:
        """Repository에 저장한다."""
        csv = self.to_csv()
        self._repository.save(csv)

    def to_csv(self) -> str:
        """CSV 문자열로 변환한다."""
        return self._blocklist.to_csv()

    def get_codes(self) -> List[str]:
        """모든 차단 코드를 반환한다."""
        return self._blocklist.get_codes()

    def get_names(self) -> List[str]:
        """모든 차단 명칭을 반환한다."""
        return self._blocklist.get_names()

    def __len__(self) -> int:
        """차단 종목 개수를 반환한다."""
        return len(self._blocklist)

    def _notify_all(self) -> None:
        """모든 옵저버에게 Blocklist 변경을 통지한다."""
        for observer in self._observers:
            observer.on_blocklist_changed(self._blocklist)

    def _notify_added(self, excluded_code: ExcludedCode) -> None:
        """모든 옵저버에게 종목 추가를 통지한다."""
        for observer in self._observers:
            observer.on_code_added(excluded_code)

    def _notify_removed(self, excluded_code: ExcludedCode) -> None:
        """모든 옵저버에게 종목 제거를 통지한다."""
        for observer in self._observers:
            observer.on_code_removed(excluded_code)
