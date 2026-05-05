"""broker/alpaca/mapping/order_data.py — schema mapping coverage.

Verifies the Alpaca → OpenAlgo legacy v1 translation for orders,
trades, positions, and holdings. Inputs mirror Alpaca's actual REST
response shapes (per a paper-trading sweep).
"""

from __future__ import annotations

import pytest

from broker.alpaca.mapping.order_data import (
    calculate_order_statistics,
    calculate_portfolio_statistics,
    map_order_data,
    map_portfolio_data,
    map_position_data,
    map_trade_data,
    transform_holdings_data,
    transform_order_data,
    transform_positions_data,
    transform_tradebook_data,
)


# ---------------------------------------------------------------------------
# Order book
# ---------------------------------------------------------------------------


def _alpaca_order(**overrides):
    base = {
        "id": "alp-order-1",
        "client_order_id": "client-1",
        "created_at": "2026-05-05T13:51:31Z",
        "submitted_at": "2026-05-05T13:51:31Z",
        "asset_id": "asset-1",
        "symbol": "AAPL",
        "exchange": "NASDAQ",
        "asset_class": "us_equity",
        "qty": "1",
        "filled_qty": "0",
        "type": "limit",
        "side": "buy",
        "time_in_force": "day",
        "limit_price": "180.00",
        "stop_price": None,
        "status": "new",
    }
    base.update(overrides)
    return base


def test_map_order_data_unwraps_envelope():
    rows = map_order_data({"status": "success", "data": [_alpaca_order(), _alpaca_order(id="alp-order-2")]})
    assert len(rows) == 2
    assert rows[0]["id"] == "alp-order-1"


def test_map_order_data_handles_none_envelope():
    assert map_order_data({"status": "success", "data": None}) == []


def test_map_order_data_passes_through_bare_list():
    assert map_order_data([_alpaca_order()])[0]["id"] == "alp-order-1"


def test_calculate_order_statistics_counts_buy_sell_and_status():
    rows = [
        _alpaca_order(side="buy",  status="filled"),
        _alpaca_order(side="buy",  status="new"),
        _alpaca_order(side="sell", status="rejected"),
        _alpaca_order(side="sell", status="canceled"),  # cancelled, not rejected
        _alpaca_order(side="sell", status="partially_filled"),  # open
    ]
    stats = calculate_order_statistics(rows)
    assert stats == {
        "total_buy_orders": 2,
        "total_sell_orders": 3,
        "total_completed_orders": 1,   # filled
        "total_open_orders": 2,        # new + partially_filled
        "total_rejected_orders": 1,
    }


def test_transform_order_data_translates_status_type_action():
    rows = [
        _alpaca_order(side="buy",  type="market",      status="filled",   limit_price=None),
        _alpaca_order(side="sell", type="stop_limit",  status="canceled", limit_price="170.00", stop_price="172.00"),
        _alpaca_order(side="sell", type="trailing_stop", status="rejected"),
    ]
    out = transform_order_data(rows)
    assert out[0]["action"] == "BUY"
    assert out[0]["pricetype"] == "MARKET"
    assert out[0]["order_status"] == "complete"
    assert out[0]["price"] == 0.0
    assert out[0]["trigger_price"] == 0.0

    assert out[1]["action"] == "SELL"
    assert out[1]["pricetype"] == "SL"          # stop_limit → SL
    assert out[1]["order_status"] == "cancelled"
    assert out[1]["price"] == 170.0
    assert out[1]["trigger_price"] == 172.0

    assert out[2]["pricetype"] == "SL-M"         # trailing_stop → SL-M
    assert out[2]["order_status"] == "rejected"


def test_transform_order_data_handles_dict_input():
    out = transform_order_data(_alpaca_order())
    assert len(out) == 1
    assert out[0]["orderid"] == "alp-order-1"


def test_transform_order_data_quantity_stays_int_when_whole():
    out = transform_order_data([_alpaca_order(qty="3")])
    assert out[0]["quantity"] == 3
    assert isinstance(out[0]["quantity"], int)


def test_transform_order_data_fractional_quantity_stays_float():
    out = transform_order_data([_alpaca_order(qty="0.722616449")])
    # Fractional crypto / equity sizes: must NOT be coerced to int.
    assert isinstance(out[0]["quantity"], float)
    assert out[0]["quantity"] == pytest.approx(0.722616449)


def test_transform_order_data_unknown_status_falls_back_to_open():
    out = transform_order_data([_alpaca_order(status="alpaca_invented_a_new_status")])
    assert out[0]["order_status"] == "open"


def test_transform_order_data_unknown_type_uppercases():
    out = transform_order_data([_alpaca_order(type="weird_new_type")])
    assert out[0]["pricetype"] == "WEIRD_NEW_TYPE"


# ---------------------------------------------------------------------------
# Trade book
# ---------------------------------------------------------------------------


def _alpaca_fill(**overrides):
    base = {
        "id": "fill-1",
        "activity_type": "FILL",
        "transaction_time": "2026-05-05T14:00:00Z",
        "order_id": "alp-order-1",
        "symbol": "AAPL",
        "exchange": "NASDAQ",
        "side": "buy",
        "qty": "10",
        "price": "180.50",
        "cum_qty": "10",
        "leaves_qty": "0",
    }
    base.update(overrides)
    return base


def test_map_trade_data_unwraps_envelope():
    out = map_trade_data({"status": "success", "data": [_alpaca_fill()]})
    assert len(out) == 1
    assert out[0]["id"] == "fill-1"


def test_transform_tradebook_data_calculates_trade_value():
    out = transform_tradebook_data([_alpaca_fill(qty="10", price="180.50")])
    assert out[0]["quantity"] == 10
    assert out[0]["average_price"] == 180.50
    assert out[0]["trade_value"] == 1805.0


def test_transform_tradebook_data_translates_action():
    out = transform_tradebook_data([_alpaca_fill(side="sell")])
    assert out[0]["action"] == "SELL"


def test_transform_tradebook_data_handles_empty():
    assert transform_tradebook_data([]) == []
    assert transform_tradebook_data(None) == []


# ---------------------------------------------------------------------------
# Position book
# ---------------------------------------------------------------------------


def _alpaca_position(**overrides):
    base = {
        "asset_id": "asset-1",
        "symbol": "AAPL",
        "exchange": "NASDAQ",
        "asset_class": "us_equity",
        "qty": "10",
        "qty_available": "10",
        "avg_entry_price": "200.00",
        "side": "long",
        "market_value": "2050.00",   # current LTP = 205.00
        "cost_basis": "2000.00",
        "unrealized_pl": "50.00",
        "current_price": "205.00",
    }
    base.update(overrides)
    return base


def test_map_position_data_unwraps_envelope():
    rows = map_position_data({"status": "success", "data": [_alpaca_position()]})
    assert rows[0]["symbol"] == "AAPL"


def test_map_position_data_handles_empty():
    assert map_position_data({"status": "success", "data": None}) == []
    assert map_position_data([]) == []


def test_transform_positions_data_long_position_signs_positive():
    out = transform_positions_data([_alpaca_position(side="long", qty="10")])
    assert out[0]["quantity"] == 10
    assert out[0]["pnl"] == 50.00
    assert out[0]["average_price"] == "200.00"
    assert out[0]["ltp"] == 205.0


def test_transform_positions_data_short_position_signs_negative():
    """Regression: Alpaca returns positive qty + side='short'. The v1
    schema expects signed quantity (negative for short).
    """
    out = transform_positions_data([_alpaca_position(side="short", qty="5")])
    assert out[0]["quantity"] == -5


def test_transform_positions_data_fractional_short():
    """Fractional short — sign preserved, type stays float."""
    out = transform_positions_data([_alpaca_position(side="short", qty="0.5", market_value="-100.0")])
    assert out[0]["quantity"] == -0.5
    assert isinstance(out[0]["quantity"], float)


def test_transform_positions_data_zero_qty_falls_back_to_current_price_for_ltp():
    """Defensive: a flat-but-still-listed position shouldn't divide by zero."""
    out = transform_positions_data([
        _alpaca_position(qty="0", market_value="0", current_price="180.0")
    ])
    assert out[0]["ltp"] == 180.0


# ---------------------------------------------------------------------------
# Holdings
# ---------------------------------------------------------------------------


def test_transform_holdings_data_calculates_pnl_percent():
    out = transform_holdings_data([_alpaca_position(
        qty="10",
        avg_entry_price="200.00",
        current_price="220.00",
        unrealized_pl="200.00",
    )])
    assert out[0]["quantity"] == 10
    assert out[0]["average_price"] == 200.0
    assert out[0]["pnl"] == 200.00
    assert out[0]["pnlpercent"] == 10.0


def test_transform_holdings_data_zero_avg_price_emits_zero_pnlpct():
    """Pre-fix-style guard: zero avg_entry_price must not raise."""
    out = transform_holdings_data([_alpaca_position(avg_entry_price="0", current_price="100")])
    assert out[0]["pnlpercent"] == 0.0


def test_transform_holdings_data_falls_back_to_market_value_when_current_price_missing():
    """Older Alpaca responses lacked ``current_price`` — derive LTP
    from market_value / qty.
    """
    raw = _alpaca_position(qty="10", market_value="2200.00", avg_entry_price="200.00", unrealized_pl="200.00")
    raw.pop("current_price", None)
    out = transform_holdings_data([raw])
    # last_price = 2200 / 10 = 220 → pnlpercent = 10.0
    assert out[0]["pnlpercent"] == 10.0


def test_calculate_portfolio_statistics_totals():
    rows = [
        _alpaca_position(qty="10", avg_entry_price="200.00", current_price="220.00", unrealized_pl="200.00"),
        _alpaca_position(symbol="MSFT", qty="5", avg_entry_price="300.00", current_price="320.00", unrealized_pl="100.00"),
    ]
    stats = calculate_portfolio_statistics(rows)
    # holdings = 10*220 + 5*320 = 2200 + 1600 = 3800
    # invvalue = 10*200 + 5*300 = 2000 + 1500 = 3500
    # pnl = 200 + 100 = 300; pct = 300/3500*100 = 8.57
    assert stats["totalholdingvalue"] == 3800.0
    assert stats["totalinvvalue"] == 3500.0
    assert stats["totalprofitandloss"] == 300.0
    assert stats["totalpnlpercentage"] == pytest.approx(8.57, abs=0.01)


def test_calculate_portfolio_statistics_empty_returns_zero():
    assert calculate_portfolio_statistics([]) == {
        "totalholdingvalue": 0.0,
        "totalinvvalue": 0.0,
        "totalprofitandloss": 0.0,
        "totalpnlpercentage": 0.0,
    }


def test_map_portfolio_data_aliases_position_data():
    rows = map_portfolio_data({"status": "success", "data": [_alpaca_position()]})
    assert rows[0]["symbol"] == "AAPL"


# ---------------------------------------------------------------------------
# Defense — malformed inputs don't crash
# ---------------------------------------------------------------------------


def test_transform_order_data_skips_non_dict_rows():
    out = transform_order_data([_alpaca_order(), "garbage", 42, _alpaca_order(id="alp-2")])
    assert len(out) == 2


def test_transform_positions_data_skips_non_dict_rows():
    out = transform_positions_data([_alpaca_position(), "garbage", _alpaca_position(symbol="MSFT")])
    assert len(out) == 2
