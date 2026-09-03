from __future__ import annotations

from typing import Any, Dict, Optional

from domain.entities import Tick
from infrastructure.kiwoom.kiwoom_parser import clean_price, clean_int


def _get_field(data: Dict[str, Any], fid: Optional[str]) -> Optional[str]:
    """FID 값을 문자열로 가져온다."""
    if not fid:
        return None
    if fid in data:
        return str(data.get(fid))
    try:
        fid_int = int(fid)
    except ValueError:
        return None
    if fid_int in data:
        return str(data.get(fid_int))
    return None


def parse_tick(
    data: Dict[str, Any],
    price_fid: str,
    volume_fid: Optional[str] = None,
    time_fid: Optional[str] = None,
    default_volume: int = 0,
    default_time: str = "",
) -> Optional[Tick]:
    """실시간 데이터 딕셔너리에서 Tick을 생성한다."""
    code = str(data.get("code", "")).strip()
    if not code:
        return None
    price = clean_price(_get_field(data, price_fid))
    volume_text = _get_field(data, volume_fid)
    time = str(_get_field(data, time_fid) or default_time or "")
    volume = clean_int(volume_text) if volume_text is not None else int(default_volume)
    if price <= 0:
        return None
    return Tick(code=code, price=price, volume=volume, time=time)
