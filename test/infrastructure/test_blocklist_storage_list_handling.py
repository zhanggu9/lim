"""
SettingsBasedBlocklistStorage list 입력 처리 테스트.

settings.excluded_codes가 list로 저장될 때 정상 처리하는지 확인한다.
"""
import pytest
from infrastructure.blocklist_storage import SettingsBasedBlocklistStorage
from use_cases.blocklist_manager import BlocklistManager


class TestSettingsBasedBlocklistStorageListHandling:
    """List 입력 처리 테스트."""
    
    def test_load_with_empty_list(self):
        """빈 list를 처리할 수 있다."""
        settings = {"excluded_codes": []}
        storage = SettingsBasedBlocklistStorage(settings)
        result = storage.load()
        
        assert result == ""
        assert isinstance(result, str)
    
    def test_load_with_single_item_list(self):
        """단일 항목 list를 처리할 수 있다."""
        settings = {"excluded_codes": ["000001"]}
        storage = SettingsBasedBlocklistStorage(settings)
        result = storage.load()
        
        assert result == "000001"
        assert isinstance(result, str)
    
    def test_load_with_multiple_item_list(self):
        """여러 항목 list를 처리할 수 있다."""
        settings = {"excluded_codes": ["000001", "000002", "000003"]}
        storage = SettingsBasedBlocklistStorage(settings)
        result = storage.load()
        
        assert result == "000001,000002,000003"
        assert isinstance(result, str)
    
    def test_load_with_whitespace_in_list(self):
        """list의 항목에 공백이 있어도 처리한다."""
        settings = {"excluded_codes": ["  000001  ", "  000002  "]}
        storage = SettingsBasedBlocklistStorage(settings)
        result = storage.load()
        
        assert result == "000001,000002"
        assert isinstance(result, str)
    
    def test_load_with_string_input(self):
        """기존의 문자열 입력도 여전히 작동한다."""
        settings = {"excluded_codes": "000001,000002"}
        storage = SettingsBasedBlocklistStorage(settings)
        result = storage.load()
        
        assert result == "000001,000002"
        assert isinstance(result, str)
    
    def test_load_with_missing_key(self):
        """excluded_codes 키가 없을 때 빈 문자열을 반환한다."""
        settings = {}
        storage = SettingsBasedBlocklistStorage(settings)
        result = storage.load()
        
        assert result == ""
        assert isinstance(result, str)
    
    def test_load_with_none_value(self):
        """None 값을 처리한다."""
        settings = {"excluded_codes": None}
        storage = SettingsBasedBlocklistStorage(settings)
        result = storage.load()
        
        assert result == ""
        assert isinstance(result, str)
    
    def test_blocklist_manager_with_list_input(self):
        """BlocklistManager가 list 입력을 처리할 수 있다."""
        settings = {"excluded_codes": ["000001", "000002"]}
        storage = SettingsBasedBlocklistStorage(settings)
        manager = BlocklistManager(repository=storage)
        
        # load()를 호출해도 오류가 발생하지 않아야 함
        manager.load()
        
        # blocklist가 정상적으로 로드되었는지 확인
        assert manager.is_blocked(code="000001")
        assert manager.is_blocked(code="000002")
    
    def test_save_and_load_cycle_with_list(self):
        """List에서 시작하여 save/load 사이클이 작동한다."""
        # 초기 list
        settings = {"excluded_codes": ["000001", "000002"]}
        manager1 = BlocklistManager(repository=SettingsBasedBlocklistStorage(settings))
        manager1.load()
        
        # 추가하기
        manager1.add_code(code="000003")
        manager1.save()
        
        # 같은 settings에서 새로운 manager 생성
        manager2 = BlocklistManager(repository=SettingsBasedBlocklistStorage(settings))
        manager2.load()
        
        # 모든 항목이 로드되었는지 확인
        assert manager2.is_blocked(code="000001")
        assert manager2.is_blocked(code="000002")
        assert manager2.is_blocked(code="000003")
    
    def test_load_with_mixed_type_list(self):
        """List의 항목이 여러 타입일 때도 처리한다."""
        settings = {"excluded_codes": ["000001", 2, "000003"]}
        storage = SettingsBasedBlocklistStorage(settings)
        result = storage.load()
        
        # 모든 항목이 문자열로 변환되어야 함
        assert "000001" in result
        assert "2" in result
        assert "000003" in result
