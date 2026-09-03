from use_cases.order_sizer import OrderSizer


def test_order_sizer_floor():
    """매수 금액을 가격으로 나눠 내림한다."""
    sizer = OrderSizer()
    assert sizer.buy_quantity(cash=1_000_000, price=3333) == 300


def test_order_sizer_sell_ratio_floor():
    """매도 수량도 내림으로 계산한다."""
    sizer = OrderSizer()
    assert sizer.sell_quantity(position_qty=3, ratio=0.5) == 1
    assert sizer.sell_quantity(position_qty=3, ratio=1.0) == 3
