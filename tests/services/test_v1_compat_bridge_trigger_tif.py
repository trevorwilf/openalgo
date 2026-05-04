"""Regression: ``_v1_order_to_normalized`` honors ``trigger_price`` +
``time_in_force`` from the v1 placeorder body.

Without these fields, two real-world flows break:

* **STOP / SL-M / SL** orders fail v2 validation with
  ``order_type=STOP requires trigger_price``. The bridge returns 502
  and the legacy India-shaped /api/v1/placeorder caller (TradingView,
  Amibroker) sees a generic broker error instead of placing the stop.

* **GTC / IOC / FOK** time-in-force values silently downgrade to DAY,
  which materially changes the order's behavior on Alpaca (a GTC
  becomes a DAY-only).

Both fields are now read from the body with India-shaped fallbacks
(``triggerprice`` etc.) preserved.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from services.v1_compat_bridge import _v1_order_to_normalized


def _v1_body(**kw):
    base = {
        "symbol": "AAPL",
        "exchange": "XNAS",
        "action": "BUY",
        "quantity": "1",
    }
    base.update(kw)
    return base


def test_trigger_price_passthrough_for_stop_orders():
    """STOP order_type requires trigger_price; the bridge must read it."""
    norm = _v1_order_to_normalized(
        _v1_body(price_type="SL-M", trigger_price="175.00")
    )
    assert norm.order_type.value == "STOP"
    assert norm.trigger_price == Decimal("175.00")


def test_trigger_price_passthrough_for_stop_limit_orders():
    """STOP_LIMIT requires both trigger_price and price."""
    norm = _v1_order_to_normalized(
        _v1_body(price_type="SL", trigger_price="175.00", price="174.50")
    )
    assert norm.order_type.value == "STOP_LIMIT"
    assert norm.trigger_price == Decimal("175.00")
    assert norm.price == Decimal("174.50")


def test_trigger_price_legacy_field_name():
    """Legacy India-shaped callers send ``triggerprice`` (no underscore)."""
    norm = _v1_order_to_normalized(
        _v1_body(price_type="SL-M", triggerprice="175.00")
    )
    assert norm.trigger_price == Decimal("175.00")


def test_trigger_price_omitted_for_market_order():
    norm = _v1_order_to_normalized(_v1_body(price_type="MARKET"))
    assert norm.trigger_price is None


def test_stop_order_without_trigger_price_raises():
    """No trigger → v2 validator raises; the bridge surfaces it."""
    with pytest.raises(Exception):
        _v1_order_to_normalized(_v1_body(price_type="SL-M"))


def test_time_in_force_default_is_day():
    norm = _v1_order_to_normalized(_v1_body(price_type="MARKET"))
    assert norm.time_in_force.value == "DAY"


def test_time_in_force_gtc_passthrough():
    norm = _v1_order_to_normalized(
        _v1_body(price_type="LIMIT", price="100", time_in_force="GTC")
    )
    assert norm.time_in_force.value == "GTC"


def test_time_in_force_ioc_passthrough():
    norm = _v1_order_to_normalized(
        _v1_body(price_type="LIMIT", price="100", time_in_force="IOC")
    )
    assert norm.time_in_force.value == "IOC"


def test_time_in_force_legacy_validity_field():
    """Legacy India-shaped callers may send ``validity`` instead."""
    norm = _v1_order_to_normalized(
        _v1_body(price_type="LIMIT", price="100", validity="GTC")
    )
    assert norm.time_in_force.value == "GTC"


def test_time_in_force_case_insensitive():
    norm = _v1_order_to_normalized(
        _v1_body(price_type="LIMIT", price="100", time_in_force="gtc")
    )
    assert norm.time_in_force.value == "GTC"
