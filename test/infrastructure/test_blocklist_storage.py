"""
Blocklist Storage 테스트.

TDD: 저장소의 저장/로드 기능을 테스트한다.
"""
import pytest
import tempfile
from pathlib import Path

from infrastructure.blocklist_storage import (
    SettingsBasedBlocklistStorage,
    FileBasedBlocklistStorage,
    JsonBasedBlocklistStorage,
    CompositeBlocklistStorage,
)


class TestSettingsBasedBlocklistStorage:
    """Settings 기반 저장소 테스트."""

    def test_save_and_load(self):
        """저장하고 로드할 수 있다."""
        settings = {}
        storage = SettingsBasedBlocklistStorage(settings)
        
        csv = "000001,삼성전자"
        storage.save(csv)
        
        loaded = storage.load()
        assert loaded == csv

    def test_load_empty_if_not_saved(self):
        """저장된 것이 없으면 빈 문자열을 반환한다."""
        settings = {}
        storage = SettingsBasedBlocklistStorage(settings)
        
        loaded = storage.load()
        assert loaded == ""

    def test_overwrite_on_save(self):
        """저장하면 이전 값을 덮어쓴다."""
        settings = {}
        storage = SettingsBasedBlocklistStorage(settings)
        
        storage.save("000001")
        storage.save("000002")
        
        loaded = storage.load()
        assert loaded == "000002"


class TestFileBasedBlocklistStorage:
    """파일 기반 저장소 테스트."""

    def test_save_and_load(self):
        """파일에 저장하고 로드할 수 있다."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "blocklist.txt"
            storage = FileBasedBlocklistStorage(str(file_path))
            
            csv = "000001,삼성전자"
            storage.save(csv)
            
            loaded = storage.load()
            assert loaded == csv

    def test_load_empty_if_not_saved(self):
        """저장된 파일이 없으면 빈 문자열을 반환한다."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "blocklist.txt"
            storage = FileBasedBlocklistStorage(str(file_path))
            
            loaded = storage.load()
            assert loaded == ""

    def test_creates_directory_if_not_exists(self):
        """디렉토리가 없으면 생성한다."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "subdir" / "blocklist.txt"
            storage = FileBasedBlocklistStorage(str(file_path))
            
            csv = "000001"
            storage.save(csv)
            
            assert file_path.exists()
            assert file_path.parent.exists()

    def test_file_persistence(self):
        """다시 생성한 저장소에서도 로드 가능하다."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "blocklist.txt"
            
            # 첫 번째 저장
            storage1 = FileBasedBlocklistStorage(str(file_path))
            csv = "000001,삼성전자"
            storage1.save(csv)
            
            # 두 번째 로드
            storage2 = FileBasedBlocklistStorage(str(file_path))
            loaded = storage2.load()
            
            assert loaded == csv


class TestJsonBasedBlocklistStorage:
    """JSON 기반 저장소 테스트."""

    def test_save_and_load(self):
        """JSON에 저장하고 로드할 수 있다."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "blocklist.json"
            storage = JsonBasedBlocklistStorage(str(file_path))
            
            csv = "000001,삼성전자"
            storage.save(csv)
            
            loaded = storage.load()
            assert loaded == csv

    def test_load_empty_if_not_saved(self):
        """저장된 파일이 없으면 빈 문자열을 반환한다."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "blocklist.json"
            storage = JsonBasedBlocklistStorage(str(file_path))
            
            loaded = storage.load()
            assert loaded == ""

    def test_json_structure(self):
        """JSON 구조가 올바르다."""
        import json
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "blocklist.json"
            storage = JsonBasedBlocklistStorage(str(file_path))
            
            csv = "000001,삼성전자"
            storage.save(csv)
            
            # 직접 파일 읽어서 구조 확인
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            assert "excluded_codes" in data
            assert "items" in data
            assert data["excluded_codes"] == csv


class TestCompositeBlocklistStorage:
    """Composite 저장소 테스트."""

    def test_save_to_multiple_storages(self):
        """여러 저장소에 모두 저장된다."""
        storage1_dict = {}
        storage2_dict = {}
        
        storage1 = SettingsBasedBlocklistStorage(storage1_dict)
        storage2 = SettingsBasedBlocklistStorage(storage2_dict)
        
        composite = CompositeBlocklistStorage([storage1, storage2])
        
        csv = "000001"
        composite.save(csv)
        
        assert storage1_dict.get("excluded_codes") == csv
        assert storage2_dict.get("excluded_codes") == csv

    def test_load_from_first_storage(self):
        """첫 번째 저장소에서 로드한다."""
        storage1_dict = {"excluded_codes": "000001"}
        storage2_dict = {"excluded_codes": "000002"}
        
        storage1 = SettingsBasedBlocklistStorage(storage1_dict)
        storage2 = SettingsBasedBlocklistStorage(storage2_dict)
        
        composite = CompositeBlocklistStorage([storage1, storage2])
        
        loaded = composite.load()
        assert loaded == "000001"
