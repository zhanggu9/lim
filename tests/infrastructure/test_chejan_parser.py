from infrastructure.kiwoom.chejan_parser import parse_order_event


def test_parse_order_event_extracts_fields():
    data = {
        "gubun": "0",
        "9001": "A005930",
        "907": "1",
        "910": "70000",
        "911": "3",
        "908": "090000",
        "302": "삼성전자",
        "900": "5",
        "902": "0",
    }

    event = parse_order_event(data)

    assert event is not None
    assert event.code == "005930"
    assert event.side == "SELL"
    assert event.quantity == 3
    assert event.price == 70000
    assert event.time == "090000"
    assert event.name == "삼성전자"
    assert event.order_qty == 5
    assert event.remaining_qty == 0


def test_parse_order_event_ignores_unfilled_accept_status():
    data = {
        "gubun": "0",
        "9001": "A005930",
        "907": "1",
        "910": "70000",
        "911": "5",
        "900": "5",
        "902": "5",
    }

    event = parse_order_event(data)

    assert event is None
