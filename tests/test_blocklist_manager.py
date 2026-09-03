"""
Blocklist Use Cases 테스트.

TDD: 비즈니스 로직과 의존성을 정의한다.
"""
import pytest
from domain.blocklist import Blocklist, ExcludedCode
from use_cases.blocklist_manager import BlocklistManager, BlocklistObserver


class MockBlocklistObserver(BlocklistObserver):
    """테스트용 Mock Observer."""

    def __init__(self):
        self.events = []

    def on_blocklist_changed(self, blocklist: Blocklist) -> None:
        """Blocklist 변경 시 이벤트를 기록한다."""
        self.events.append(("changed", len(blocklist)))

    def on_code_added(self, excluded_code: ExcludedCode) -> None:
        """종목 추가 시 이벤트를 기록한다."""
        self.events.append(("added", str(excluded_code)))

    def on_code_removed(self, excluded_code: ExcludedCode) -> None:
        """종목 제거 시 이벤트를 기록한다."""
        self.events.append(("removed", str(excluded_code)))


class MockBlocklistRepository:
    """테스트용 Mock Repository."""

    def __init__(self):
        self.saved_csv = None
        self.load_count = 0

    def save(self, csv_string: str) -> None:
        """CSV를 저장한다."""
        self.saved_csv = csv_string

    def load(self) -> str:
        """저장된 CSV를 로드한다."""
        self.load_count += 1
        return self.saved_csv or ""


class TestBlocklistManager:
    """BlocklistManager Use Case 테스트."""

    def test_create_manager(self):
        """BlocklistManager를 생성할 수 있다."""
        repo = MockBlocklistRepository()
        manager = BlocklistManager(repository=repo)
        assert manager is not None
        assert manager.repo == repo

    def test_add_code(self):
        """코드를 추가할 수 있다."""
        repo = MockBlocklistRepository()
        manager = BlocklistManager(repository=repo)
        manager.add_code(code="000001")
        assert manager.is_blocked(code="000001")

    def test_add_name(self):
        """명칭을 추가할 수 있다."""
        repo = MockBlocklistRepository()
        manager = BlocklistManager(repository=repo)
        manager.add_name(name="삼성전자")
        assert manager.is_blocked(name="삼성전자")

    def test_remove_code(self):
        """코드를 제거할 수 있다."""
        repo = MockBlocklistRepository()
        manager = BlocklistManager(repository=repo)
        manager.add_code(code="000001")
        assert manager.is_blocked(code="000001")
        manager.remove_code(code="000001")
        assert not manager.is_blocked(code="000001")

    def test_remove_name(self):
        """명칭을 제거할 수 있다."""
        repo = MockBlocklistRepository()
        manager = BlocklistManager(repository=repo)
        manager.add_name(name="삼성전자")
        assert manager.is_blocked(name="삼성전자")
        manager.remove_name(name="삼성전자")
        assert not manager.is_blocked(name="삼성전자")

    def test_is_blocked_by_code(self):
        """코드로 차단 여부를 확인할 수 있다."""
        repo = MockBlocklistRepository()
        manager = BlocklistManager(repository=repo)
        manager.add_code(code="000001")
        assert manager.is_blocked(code="000001")
        assert not manager.is_blocked(code="000002")

    def test_is_blocked_by_name(self):
        """명칭으로 차단 여부를 확인할 수 있다."""
        repo = MockBlocklistRepository()
        manager = BlocklistManager(repository=repo)
        manager.add_name(name="삼성전자")
        assert manager.is_blocked(name="삼성전자")
        assert not manager.is_blocked(name="SK하이닉스")

    def test_is_blocked_case_insensitive_for_code(self):
        """코드 검색은 대소문자 구분이 없다."""
        repo = MockBlocklistRepository()
        manager = BlocklistManager(repository=repo)
        manager.add_code(code="NAVER")
        assert manager.is_blocked(code="naver")
        assert manager.is_blocked(code="NAVER")

    def test_clear_all(self):
        """모든 차단 종목을 제거할 수 있다."""
        repo = MockBlocklistRepository()
        manager = BlocklistManager(repository=repo)
        manager.add_code(code="000001")
        manager.add_code(code="000002")
        assert len(manager) == 2
        manager.clear()
        assert len(manager) == 0

    def test_save_to_repository(self):
        """Repository에 저장된다."""
        repo = MockBlocklistRepository()
        manager = BlocklistManager(repository=repo)
        manager.add_code(code="000001")
        manager.add_name(name="삼성전자")
        manager.save()
        assert repo.saved_csv is not None
        assert "000001" in repo.saved_csv

    def test_load_from_repository(self):
        """Repository에서 로드된다."""
        repo = MockBlocklistRepository()
        repo.saved_csv = "000001,삼성전자"
        manager = BlocklistManager(repository=repo)
        manager.load()
        assert manager.is_blocked(code="000001")

    def test_observer_notified_on_add(self):
        """종목 추가 시 Observer가 통지된다."""
        repo = MockBlocklistRepository()
        manager = BlocklistManager(repository=repo)
        observer = MockBlocklistObserver()
        manager.subscribe(observer)
        
        manager.add_code(code="000001")
        
        assert len(observer.events) > 0
        # "added" 또는 "changed" 이벤트가 있어야 한다.
        event_types = [e[0] for e in observer.events]
        assert "added" in event_types or "changed" in event_types

    def test_observer_notified_on_remove(self):
        """종목 제거 시 Observer가 통지된다."""
        repo = MockBlocklistRepository()
        manager = BlocklistManager(repository=repo)
        manager.add_code(code="000001")
        
        observer = MockBlocklistObserver()
        manager.subscribe(observer)
        manager.remove_code(code="000001")
        
        assert len(observer.events) > 0
        event_types = [e[0] for e in observer.events]
        assert "removed" in event_types or "changed" in event_types

    def test_multiple_observers(self):
        """여러 Observer가 동시에 통지된다."""
        repo = MockBlocklistRepository()
        manager = BlocklistManager(repository=repo)
        observer1 = MockBlocklistObserver()
        observer2 = MockBlocklistObserver()
        
        manager.subscribe(observer1)
        manager.subscribe(observer2)
        
        manager.add_code(code="000001")
        
        assert len(observer1.events) > 0
        assert len(observer2.events) > 0

    def test_get_all_codes(self):
        """모든 차단 코드를 가져올 수 있다."""
        repo = MockBlocklistRepository()
        manager = BlocklistManager(repository=repo)
        manager.add_code(code="000001")
        manager.add_code(code="000002")
        codes = manager.get_codes()
        assert "000001" in codes
        assert "000002" in codes

    def test_get_all_names(self):
        """모든 차단 명칭을 가져올 수 있다."""
        repo = MockBlocklistRepository()
        manager = BlocklistManager(repository=repo)
        manager.add_name(name="삼성전자")
        manager.add_name(name="SK하이닉스")
        names = manager.get_names()
        assert "삼성전자" in names
        assert "SK하이닉스" in names

    def test_to_csv(self):
        """CSV 문자열로 변환할 수 있다."""
        repo = MockBlocklistRepository()
        manager = BlocklistManager(repository=repo)
        manager.add_code(code="000001")
        manager.add_name(name="삼성전자")
        csv = manager.to_csv()
        assert len(csv) > 0
        # 000001 또는 삼성전자가 포함되어야 한다.
        assert "000001" in csv or "삼성전자" in csv

    def test_from_csv(self):
        """CSV 문자열로부터 생성할 수 있다."""
        repo = MockBlocklistRepository()
        manager = BlocklistManager(repository=repo)
        manager.load_from_csv("000001,삼성전자")
        assert manager.is_blocked(code="000001")
        assert manager.is_blocked(name="삼성전자")

    def test_durata_protection_on_ui_input(self):
        """UI에서의 입력을 정규화한다."""
        repo = MockBlocklistRepository()
        manager = BlocklistManager(repository=repo)
        # 공백이 있는 입력
        manager.add_name(name="  삼성전자  ")
        # 정규화되어 공백 없이 저장되어야 한다.
        assert manager.is_blocked(name="삼성전자")
