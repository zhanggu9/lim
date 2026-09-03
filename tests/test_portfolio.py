from use_cases.portfolio import Portfolio


def test_update_from_holdings_defaults_sellable_to_qty():
    portfolio = Portfolio()
    holdings = {
        "000001": {
            "qty": 10,
            "sellable": 0,
            "avg_price": 1500,
        }
    }

    portfolio.update_from_holdings(holdings)

    assert portfolio.get_qty("000001") == 10
    assert portfolio.get_sellable("000001") == 10


def test_update_from_holdings_ignores_zero_qty_rows():
    portfolio = Portfolio()
    holdings = {
        "000001": {
            "qty": 0,
            "sellable": 0,
            "avg_price": 1500,
        }
    }

    portfolio.update_from_holdings(holdings)

    assert portfolio.count() == 0
    assert portfolio.get_qty("000001") == 0
