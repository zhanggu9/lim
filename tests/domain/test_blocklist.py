"""
Blocklist 도메인 엔티티 테스트.

TDD 방식: 테스트를 먼저 작성하고 구현을 함.
"""
import pytest
from domain.blocklist import Blocklist, ExcludedCode


class TestExcludedCode:
    """ExcludedCode (값 객체) 테스트."""

    def test_create_with_code(self):
        """코드로 ExcludedCode를 생성할 수 있다."""
        code = ExcludedCode(code="000001")
        assert code.code == "000001"

    def test_create_with_name(self):
        """명칭으로 ExcludedCode를 생성할 수 있다."""
        code = ExcludedCode(name="삼성전자")
        assert code.name == "삼성전자"

    def test_normalize_code_to_uppercase(self):
        """코드는 대문자로 정규화된다."""
        code = ExcludedCode(code="naver")
        assert code.normalized_code == "NAVER"

    def test_normalize_name_stripped(self):
        """명칭의 공백은 제거된다."""
        code = ExcludedCode(name="  삼성전자  ")
        assert code.normalized_name == "삼성전자"

    def test_equality_by_code(self):
        """같은 코드면 같은 ExcludedCode다."""
        code1 = ExcludedCode(code="000001")
        code2 = ExcludedCode(code="000001")
        assert code1 == code2

    def test_equality_by_name(self):
        """같은 명칭이면 같은 ExcludedCode다."""
        code1 = ExcludedCode(name="삼성전자")
        code2 = ExcludedCode(name="삼성전자")
        assert code1 == code2

    def test_code_or_name_required(self):
        """코드나 명칭 중 하나는 필수다."""
        with pytest.raises(ValueError):
            ExcludedCode()

    def test_string_representation(self):
        """문자열 표현이 있다."""
        code = ExcludedCode(code="000001", name="삼성전자")
        assert "000001" in str(code) or "삼성전자" in str(code)


class TestBlocklist:
    """Blocklist (엔티티) 테스트."""

    def test_create_empty_blocklist(self):
        """빈 Blocklist를 생성할 수 있다."""
        blocklist = Blocklist()
        assert len(blocklist) == 0
        assert blocklist.is_empty()

    def test_add_excluded_code(self):
        """제외 종목을 추가할 수 있다."""
        blocklist = Blocklist()
        code = ExcludedCode(code="000001")
        blocklist.add(code)
        assert len(blocklist) == 1
        assert code in blocklist

    def test_add_duplicate_code_not_allowed(self):
        """중복 종목 추가는 무시된다."""
        blocklist = Blocklist()
        code1 = ExcludedCode(code="000001")
        code2 = ExcludedCode(code="000001")
        blocklist.add(code1)
        blocklist.add(code2)
        assert len(blocklist) == 1

    def test_remove_excluded_code(self):
        """제외 종목을 제거할 수 있다."""
        blocklist = Blocklist()
        code = ExcludedCode(code="000001")
        blocklist.add(code)
        assert len(blocklist) == 1
        blocklist.remove(code)
        assert len(blocklist) == 0

    def test_contains_code(self):
        """코드로 포함 여부를 확인할 수 있다."""
        blocklist = Blocklist()
        blocklist.add(ExcludedCode(code="000001"))
        assert blocklist.contains(code="000001")
        assert not blocklist.contains(code="000002")

    def test_contains_name(self):
        """명칭으로 포함 여부를 확인할 수 있다."""
        blocklist = Blocklist()
        blocklist.add(ExcludedCode(name="삼성전자"))
        assert blocklist.contains(name="삼성전자")
        assert not blocklist.contains(name="SK하이닉스")

    def test_contains_case_insensitive_for_code(self):
        """코드 검색은 대소문자 구분 없다."""
        blocklist = Blocklist()
        blocklist.add(ExcludedCode(code="NAVER"))
        assert blocklist.contains(code="naver")
        assert blocklist.contains(code="NAVER")

    def test_clear_all(self):
        """모든 제외 종목을 제거할 수 있다."""
        blocklist = Blocklist()
        blocklist.add(ExcludedCode(code="000001"))
        blocklist.add(ExcludedCode(code="000002"))
        assert len(blocklist) == 2
        blocklist.clear()
        assert len(blocklist) == 0

    def test_get_all_codes(self):
        """모든 제외 종목 코드를 가져올 수 있다."""
        blocklist = Blocklist()
        blocklist.add(ExcludedCode(code="000001"))
        blocklist.add(ExcludedCode(code="000002"))
        codes = blocklist.get_codes()
        assert "000001" in codes
        assert "000002" in codes

    def test_get_all_names(self):
        """모든 제외 종목 명칭을 가져올 수 있다."""
        blocklist = Blocklist()
        blocklist.add(ExcludedCode(name="삼성전자"))
        blocklist.add(ExcludedCode(name="SK하이닉스"))
        names = blocklist.get_names()
        assert "삼성전자" in names
        assert "SK하이닉스" in names

    def test_from_csv_string(self):
        """CSV 문자열로부터 Blocklist를 생성할 수 있다."""
        csv = "000001,삼성전자,NAVER,네이버"
        blocklist = Blocklist.from_csv(csv)
        assert len(blocklist) == 4
        assert blocklist.contains(code="000001")
        assert blocklist.contains(name="삼성전자")

    def test_to_csv_string(self):
        """Blocklist를 CSV 문자열로 변환할 수 있다."""
        blocklist = Blocklist()
        blocklist.add(ExcludedCode(code="000001"))
        blocklist.add(ExcludedCode(name="삼성전자"))
        csv = blocklist.to_csv()
        assert "000001" in csv
        assert "삼성전자" in csv
