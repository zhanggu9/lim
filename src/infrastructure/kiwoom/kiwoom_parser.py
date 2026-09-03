from __future__ import annotations

from typing import Dict


def clean_int(value: str) -> int:
    """키움 문자열 숫자를 정수로 변환한다."""
    if value is None:
        return 0
    text = str(value).strip()
    if not text:
        return 0
    text = text.replace(",", "").replace("+", "")
    try:
        return int(text)
    except ValueError:
        try:
            return int(float(text))
        except ValueError:
            return 0


def clean_price(value: str) -> int:
    """현재가 문자열을 절대값 정수로 변환한다."""
    return abs(clean_int(value))


def clean_float(value: str) -> float:
    """키움 문자열 숫자를 실수로 변환한다."""
    if value is None:
        return 0.0
    text = str(value).strip()
    if not text:
        return 0.0
    text = text.replace(",", "").replace("+", "")
    try:
        return float(text)
    except ValueError:
        return 0.0


def normalize_code(code: str) -> str:
    """종목코드를 정규화한다."""
    if not code:
        return ""
    text = str(code).strip()
    if text.startswith("A") and len(text) == 7:
        return text[1:]
    return text


def parse_condition_list(raw) -> Dict[int, str]:
    """조건식 목록을 인덱스-이름으로 변환한다."""
    result: Dict[int, str] = {}
    if isinstance(raw, list):
        for item in raw:
            if not item or len(item) != 2:
                continue
            index_str, name = item
            try:
                result[int(index_str)] = str(name)
            except ValueError:
                continue
        return result

    for item in (raw or "").split(";"):
        if not item:
            continue
        if "^" not in item:
            continue
        index_str, name = item.split("^", 1)
        try:
            result[int(index_str)] = name
        except ValueError:
            continue
    return result
