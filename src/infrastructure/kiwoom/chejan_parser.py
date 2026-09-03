from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from domain.entities import TradeExecution
from infrastructure.kiwoom.kiwoom_parser import clean_int, normalize_code


def _get_field(data: Dict[str, Any], fid: str) -> Optional[str]:
    """FID 값을 문자열로 가져온다."""
    if fid in data:
        return str(data.get(fid))
    try:
        fid_int = int(fid)
    except ValueError:
        return None
    if fid_int in data:
        return str(data.get(fid_int))
    return None


def parse_balance_event(data: Dict[str, Any]) -> Optional[Tuple[str, int, int, int, int]]:
    """잔고 이벤트에서 종목코드와 수량 정보를 추출한다."""
    code_raw = _get_field(data, "9001")
    if not code_raw:
        return None
    code = normalize_code(code_raw)
    qty = clean_int(_get_field(data, "930"))
    sellable = clean_int(_get_field(data, "933"))
    if sellable <= 0:
        sellable = qty
    avg_price = clean_int(_get_field(data, "931"))
    current_price = clean_int(_get_field(data, "10"))
    return code, qty, sellable, avg_price, current_price


def parse_order_event(data: Dict[str, Any]) -> Optional[TradeExecution]:
    """주문/체결 이벤트에서 체결 정보를 추출한다."""
    code_raw = _get_field(data, "9001")
    if not code_raw:
        return None
    code = normalize_code(code_raw)
    side_raw = clean_int(_get_field(data, "907"))
    side = "SELL" if side_raw == 1 else "BUY" if side_raw == 2 else ""
    qty = clean_int(_get_field(data, "911"))
    if qty <= 0:
        qty = clean_int(_get_field(data, "900"))
    price = clean_int(_get_field(data, "910"))
    if price <= 0:
        price = clean_int(_get_field(data, "10"))
    order_qty = clean_int(_get_field(data, "900"))
    remaining = clean_int(_get_field(data, "902"))
    # 접수 단계(미체결=주문수량)는 실제 체결이 아니므로 제외한다.
    if order_qty > 0 and remaining >= order_qty:
        return None
    if qty <= 0 or price <= 0 or not side:
        return None
    time = str(_get_field(data, "908") or "")
    name = str(_get_field(data, "302") or "").strip()
    order_no = str(_get_field(data, "9203") or "").strip()
    return TradeExecution(
        code=code,
        side=side,
        quantity=qty,
        price=price,
        time=time,
        name=name,
        order_no=order_no,
        order_qty=order_qty,
        remaining_qty=remaining,
    )
