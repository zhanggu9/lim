"""
Blocklist와 TradingEngine 통합 테스트.

TDD: 매거 주문이 제외 종목일 때 차단되는지 확인한다.
"""
import pytest
from domain.blocklist import Blocklist, ExcludedCode
from use_cases.blocklist_manager import BlocklistManager
from infrastructure.blocklist_storage import SettingsBasedBlocklistStorage


class MockTradingEngine:
    """테스트용 TradingEngine (단순화된 버전)."""
    
    def __init__(self, blocklist_manager: BlocklistManager):
        self._blocklist_manager = blocklist_manager
        self._orders = []  # 실행된 주문 목록
    
    def execute_trade_signal(self, code: str, side: str, quantity: int, price: int) -> bool:
        """거래 신호를 실행하고, 제외 종목이면 거부한다."""
        # 제외 종목 확인
        if self._blocklist_manager.is_blocked(code=code):
            # 차단됨 - 주문 실행 안 함
            return False
        
        # 허가됨 - 주문 실행
        self._orders.append({
            "code": code,
            "side": side,
            "quantity": quantity,
            "price": price,
        })
        return True
    
    def get_executed_orders(self):
        """실행된 주문 목록을 반환한다."""
        return self._orders


class TestBlocklistWithTradingEngine:
    """Blocklist와 TradingEngine 통합 테스트."""

    def test_blocked_code_prevents_order(self):
        """제외 종목의 주문은 실행되지 않는다."""
        settings = {}
        storage = SettingsBasedBlocklistStorage(settings)
        blocklist_manager = BlocklistManager(repository=storage)
        engine = MockTradingEngine(blocklist_manager)
        
        # 종목 추가
        blocklist_manager.add_code(code="000001")
        
        # 주문 시도
        result = engine.execute_trade_signal(code="000001", side="BUY", quantity=100, price=50000)
        
        assert result is False
        assert len(engine.get_executed_orders()) == 0

    def test_non_blocked_code_allows_order(self):
        """제외 대상이 아닌 종목의 주문은 실행된다."""
        settings = {}
        storage = SettingsBasedBlocklistStorage(settings)
        blocklist_manager = BlocklistManager(repository=storage)
        engine = MockTradingEngine(blocklist_manager)
        
        # 다른 종목은 추가하지 않음
        blocklist_manager.add_code(code="000002")
        
        # 주문 시도
        result = engine.execute_trade_signal(code="000001", side="BUY", quantity=100, price=50000)
        
        assert result is True
        assert len(engine.get_executed_orders()) == 1

    def test_adding_code_to_blocklist_after_load(self):
        """Blocklist 로드 후 종목을 추가할 수 있다."""
        settings = {}
        storage = SettingsBasedBlocklistStorage(settings)
        blocklist_manager = BlocklistManager(repository=storage)
        engine = MockTradingEngine(blocklist_manager)
        
        # 초기 로드 (빈 상태)
        blocklist_manager.load()
        
        # 종목 추가
        blocklist_manager.add_code(code="000001")
        
        # 새로 생성한 엔진도 같은 blocklist 사용
        engine2 = MockTradingEngine(blocklist_manager)
        result = engine2.execute_trade_signal(code="000001", side="BUY", quantity=100, price=50000)
        
        assert result is False

    def test_removing_code_from_blocklist_allows_order(self):
        """제외 종목을 제거하면 주문이 실행된다."""
        settings = {}
        storage = SettingsBasedBlocklistStorage(settings)
        blocklist_manager = BlocklistManager(repository=storage)
        engine = MockTradingEngine(blocklist_manager)
        
        # 종목 추가
        blocklist_manager.add_code(code="000001")
        assert not engine.execute_trade_signal(code="000001", side="BUY", quantity=100, price=50000)
        
        # 종목 제거
        blocklist_manager.remove_code(code="000001")
        result = engine.execute_trade_signal(code="000001", side="BUY", quantity=100, price=50000)
        
        assert result is True

    def test_blocked_by_name(self):
        """명칭으로 등록해도 차단된다."""
        settings = {}
        storage = SettingsBasedBlocklistStorage(settings)
        blocklist_manager = BlocklistManager(repository=storage)
        
        # 명칭으로 추가
        blocklist_manager.add_name(name="삼성전자")
        
        # Note: 실제로는 코드 기반 확인만 하므로,
        # 이를 위해서는 코드-명칭 매핑이 필요하다.
        # 여기서는 코드 기반만 테스트한다.
        assert blocklist_manager.is_blocked(name="삼성전자")

    def test_persistence_across_instances(self):
        """설정에 저장되어 인스턴스 재생성 후에도 유지된다."""
        settings = {}
        
        # 첫 번째 인스턴스
        storage1 = SettingsBasedBlocklistStorage(settings)
        manager1 = BlocklistManager(repository=storage1)
        manager1.add_code(code="000001")
        manager1.save()
        
        # 두 번째 인스턴스 (같은 settings 사용)
        storage2 = SettingsBasedBlocklistStorage(settings)
        manager2 = BlocklistManager(repository=storage2)
        manager2.load()
        
        # 첫 번째에서 추가한 종목이 두 번째에서도 있어야 함
        assert manager2.is_blocked(code="000001")
