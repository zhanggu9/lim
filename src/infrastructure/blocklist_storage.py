"""
Blocklist Storage 구현.

Clean Architecture의 Infrastructure Layer로, 영속성을 담당한다.
"""
from __future__ import annotations
from typing import Dict, Any
import json
from pathlib import Path

from use_cases.blocklist_manager import BlocklistRepository


class SettingsBasedBlocklistStorage(BlocklistRepository):
    """Settings 객체를 기반으로 Blocklist를 저장/로드한다."""

    EXCLUDED_CODES_KEY = "excluded_codes"

    def __init__(self, settings: Dict[str, Any]) -> None:
        """Settings 객체로 초기화한다."""
        self._settings = settings

    def save(self, csv_string: str) -> None:
        """CSV 문자열을 settings에 저장한다."""
        self._settings[self.EXCLUDED_CODES_KEY] = csv_string

    def load(self) -> str:
        """Settings에서 CSV 문자열을 로드한다."""
        value = self._settings.get(self.EXCLUDED_CODES_KEY, "")
        
        # list 타입일 경우 쉼표로 구분된 문자열로 변환
        if isinstance(value, list):
            return ",".join(str(item).strip() for item in value if item)
        
        # 문자열 타입일 경우 그대로 반환
        if isinstance(value, str):
            return value
        
        # 그 외의 타입은 빈 문자열 반환
        return ""


class FileBasedBlocklistStorage(BlocklistRepository):
    """파일 시스템에 Blocklist를 저장/로드한다."""

    def __init__(self, file_path: str) -> None:
        """파일 경로로 초기화한다."""
        self._file_path = Path(file_path)
        # 디렉토리가 없으면 생성
        self._file_path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, csv_string: str) -> None:
        """CSV 문자열을 파일에 저장한다."""
        with open(self._file_path, "w", encoding="utf-8") as f:
            f.write(csv_string)

    def load(self) -> str:
        """파일에서 CSV 문자열을 로드한다."""
        if not self._file_path.exists():
            return ""
        with open(self._file_path, "r", encoding="utf-8") as f:
            return f.read().strip()


class JsonBasedBlocklistStorage(BlocklistRepository):
    """JSON 파일에 Blocklist를 저장/로드한다."""

    def __init__(self, file_path: str) -> None:
        """파일 경로로 초기화한다."""
        self._file_path = Path(file_path)
        # 디렉토리가 없으면 생성
        self._file_path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, csv_string: str) -> None:
        """CSV 문자열을 JSON 파일에 저장한다."""
        data = {
            "excluded_codes": csv_string,
            "items": [item.strip() for item in csv_string.split(",") if item.strip()],
        }
        with open(self._file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self) -> str:
        """JSON 파일에서 CSV 문자열을 로드한다."""
        if not self._file_path.exists():
            return ""
        with open(self._file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("excluded_codes", "")


class CompositeBlocklistStorage(BlocklistRepository):
    """여러 저장소에 중복 저장하는 Composite 패턴."""

    def __init__(self, storages: list[BlocklistRepository]) -> None:
        """여러 저장소로 초기화한다."""
        self._storages = storages

    def save(self, csv_string: str) -> None:
        """모든 저장소에 저장한다."""
        for storage in self._storages:
            storage.save(csv_string)

    def load(self) -> str:
        """첫 번째 저장소에서 로드한다."""
        if not self._storages:
            return ""
        return self._storages[0].load()
