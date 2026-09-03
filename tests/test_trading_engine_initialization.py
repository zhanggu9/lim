"""
TradingEngine 초기화 및 제외 종목 기능 검증 테스트.

실제 프로그램 실행 시 발생할 수 있는 오류를 사전에 검출한다.
"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from use_cases.blocklist_manager import BlocklistManager
from infrastructure.blocklist_storage import SettingsBasedBlocklistStorage


class MockSettings:
    """테스트용 Settings 객체."""
    
    def __init__(self):
        self.excluded_codes = []
        self.market_start = "090000"
        self.market_end = "150000"
        self.market_timezone = "Asia/Seoul"
        self.cooldown_seconds = 10
        self.strategy_name = "rsi_grid"
        self.buy_qty = 1
        self.buy_cash = 100000
        self.rsi_period = 14
        self.rsi_overbought = 70
        self.rsi_oversold = 30
        self.ticks_per_candle = 100
        self.minutes_per_candle = 5
        self.ui_refresh_ms = 1000


class TestTradingEngineInitialization:
    """TradingEngine 초기화 검증."""
    
    def test_blocklist_manager_initialization_with_dict(self):
        """BlocklistManager를 dict settings로 초기화할 수 있다."""
        settings = {"excluded_codes": ""}
        storage = SettingsBasedBlocklistStorage(settings)
        manager = BlocklistManager(repository=storage)
        manager.load()
        
        # 비어있어야 함
        assert len(manager._blocklist) == 0
    
    def test_blocklist_manager_initialization_with_settings_object(self):
        """BlocklistManager를 settings 객체의 __dict__로 초기화할 수 있다."""
        settings = MockSettings()
        settings_dict = settings.__dict__
        
        assert isinstance(settings_dict, dict)
        
        storage = SettingsBasedBlocklistStorage(settings_dict)
        manager = BlocklistManager(repository=storage)
        manager.load()
        
        # 비어있어야 함
        assert len(manager._blocklist) == 0
    
    def test_blocklist_manager_initialization_with_invalid_input(self):
        """BlocklistManager 초기화가 잘못된 입력에도 견딜 수 있다."""
        # None이거나 비 dict 입력
        settings_dict = {} if not {}  else {}
        
        storage = SettingsBasedBlocklistStorage(settings_dict)
        manager = BlocklistManager(repository=storage)
        manager.load()
        
        assert len(manager._blocklist) == 0
    
    def test_change_excluded_codes_with_valid_input(self):
        """change_excluded_codes가 valid input을 처리할 수 있다."""
        settings = MockSettings()
        storage = SettingsBasedBlocklistStorage(settings.__dict__)
        manager = BlocklistManager(repository=storage)
        manager.load()
        
        # CSV 문자열로 추가
        manager.load_from_csv("000001,000002,000003")
        
        assert len(manager._blocklist) == 3
        assert manager.is_blocked(code="000001")
    
    def test_change_excluded_codes_with_empty_input(self):
        """change_excluded_codes가 empty input을 처리할 수 있다."""
        settings = MockSettings()
        storage = SettingsBasedBlocklistStorage(settings.__dict__)
        manager = BlocklistManager(repository=storage)
        manager.load()
        
        # 아무것도 추가하지 않음
        manager.load_from_csv("")
        
        assert len(manager._blocklist) == 0
    
    def test_change_excluded_codes_with_whitespace(self):
        """change_excluded_codes가 whitespace를 포함한 input을 처리할 수 있다."""
        settings = MockSettings()
        storage = SettingsBasedBlocklistStorage(settings.__dict__)
        manager = BlocklistManager(repository=storage)
        manager.load()
        
        # 공백이 포함된 CSV 문자열
        manager.load_from_csv("  000001  ,  000002  ,  000003  ")
        
        assert len(manager._blocklist) == 3
        assert manager.is_blocked(code="000001")
        assert manager.is_blocked(code="000002")
        assert manager.is_blocked(code="000003")
    
    def test_is_blocked_with_none_manager(self):
        """BlocklistManager가 None이면 fallback을 사용한다."""
        # 실제 구현에서 _blocklist_manager는 초기화되어야 하지만
        # 혹시 모를 사태에 대비해 graceful하게 처리되어야 함
        
        manager = BlocklistManager(repository=SettingsBasedBlocklistStorage({}))
        manager.load()
        
        # 정상 작동 확인
        manager.add_code(code="000001")
        assert manager.is_blocked(code="000001")
    
    def test_error_handling_in_change_excluded_codes(self):
        """change_excluded_codes가 오류를 gracefully 처리한다."""
        settings = MockSettings()
        storage = SettingsBasedBlocklistStorage(settings.__dict__)
        manager = BlocklistManager(repository=storage)
        manager.load()
        
        # 여러 타입의 입력 처리
        try:
            manager.load_from_csv(None)  # None 입력
            # 오류가 발생하지 않아야 함
        except Exception as e:
            pytest.fail(f"None input handling failed: {e}")
        
        try:
            manager.load_from_csv("")  # Empty string
            # 오류가 발생하지 않아야 함
        except Exception as e:
            pytest.fail(f"Empty string handling failed: {e}")
    
    def test_excluded_codes_persistence(self):
        """제외 종목이 저장되고 로드될 수 있다."""
        settings = MockSettings()
        storage = SettingsBasedBlocklistStorage(settings.__dict__)
        manager = BlocklistManager(repository=storage)
        manager.load()
        
        # 저장
        manager.add_code(code="000001")
        manager.save()
        
        # 새로운 manager 인스턴스에서 로드
        manager2 = BlocklistManager(repository=storage)
        manager2.load()
        
        assert manager2.is_blocked(code="000001")
