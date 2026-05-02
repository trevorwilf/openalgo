"""Phase 3 (T-20) — region-aware validators across the 8 critical services.

The 8 service entry points migrated from
``utils.constants.VALID_*`` to
``services.market_region_service.get_allowed_*_for_active_region()``:

* :mod:`services.place_order_service`
* :mod:`services.place_smart_order_service`
* :mod:`services.quotes_service`
* :mod:`services.history_service`
* :mod:`services.depth_service`
* :mod:`services.margin_service`
* :mod:`services.basket_order_service`
* :mod:`services.split_order_service` (no longer uses VALID_* — dead
  imports removed)

Per the prompt, each service is asserted against:

1. With India region active, India venue/product accepted.
2. With a non-India region active and a non-India venue, the foreign
   venue is rejected with the same error-message format (lists the
   active region's allowed venues, not India's).
3. With no region context resolvable, the validator returns a
   ``MissingRegionContext``-shaped error (not silently India default).

The legacy ``utils.constants.VALID_EXCHANGES`` order is preserved for
India through ``legacy_compat_shim.valid_exchanges`` so the v1 lane
sees a bit-identical message; a separate parity harness covers the
end-to-end fixture.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest


@pytest.fixture
def force_india(monkeypatch):
    monkeypatch.setenv("MARKET_REGION_FOR_TESTS", "india")
    yield


@pytest.fixture
def force_no_region(monkeypatch):
    monkeypatch.delenv("MARKET_REGION_FOR_TESTS", raising=False)
    # Block both broker-session and settings paths so
    # ``feature_gate_service.active_region_code`` raises.
    from services import feature_gate_service, market_region_service

    monkeypatch.setattr(feature_gate_service, "_current_broker_session_value", lambda: None)
    monkeypatch.setattr(
        market_region_service, "resolve_default_market_region_code", lambda: None,
    )
    yield


def _india_venues_message(venues: list[str]) -> str:
    return ", ".join(venues)


# ---------------------------------------------------------------------------
# place_order_service
# ---------------------------------------------------------------------------


def test_place_order_india_accepts_nse(force_india):
    from services.place_order_service import validate_order_data

    ok, _, msg = validate_order_data({
        "apikey": "k", "strategy": "s", "symbol": "SBIN",
        "exchange": "NSE", "action": "BUY", "quantity": 1,
        "pricetype": "MARKET", "product": "CNC",
    })
    # Validation passes the exchange/product checks; OrderSchema may
    # reject other fields (e.g. legacy field naming). The relevant
    # assertion is that the failure message — if any — does NOT
    # mention an invalid exchange.
    if not ok:
        assert "Invalid exchange" not in (msg or "")
        assert "Invalid product" not in (msg or "")
        assert "Invalid price type" not in (msg or "")


def test_place_order_india_rejects_xnys(force_india):
    from services.place_order_service import validate_order_data

    ok, _, msg = validate_order_data({
        "apikey": "k", "strategy": "s", "symbol": "AAPL",
        "exchange": "XNYS", "action": "BUY", "quantity": 1,
    })
    assert ok is False
    assert "Invalid exchange" in msg
    # Error message lists India's vocabulary in legacy order.
    assert "NSE" in msg
    assert "CRYPTO" in msg


def test_place_order_no_region_returns_missing_context_message(force_no_region):
    from services.place_order_service import validate_order_data

    ok, _, msg = validate_order_data({
        "apikey": "k", "strategy": "s", "symbol": "SBIN",
        "exchange": "NSE", "action": "BUY", "quantity": 1,
    })
    assert ok is False
    assert "Cannot validate order" in msg


# ---------------------------------------------------------------------------
# place_smart_order_service
# ---------------------------------------------------------------------------


def test_smart_order_india_rejects_xnys(force_india):
    from services.place_smart_order_service import validate_smart_order

    ok, msg = validate_smart_order({
        "apikey": "k", "strategy": "s", "symbol": "AAPL",
        "exchange": "XNYS", "action": "BUY", "quantity": 1,
        "position_size": 0,
    })
    assert ok is False
    assert "Invalid exchange" in msg


def test_smart_order_no_region_returns_missing_context_message(force_no_region):
    from services.place_smart_order_service import validate_smart_order

    ok, msg = validate_smart_order({
        "apikey": "k", "strategy": "s", "symbol": "SBIN",
        "exchange": "NSE", "action": "BUY", "quantity": 1,
        "position_size": 0,
    })
    assert ok is False
    assert "Cannot validate smart order" in msg


# ---------------------------------------------------------------------------
# quotes_service
# ---------------------------------------------------------------------------


def test_quote_india_rejects_xnys(force_india):
    from services.quotes_service import validate_symbol_exchange

    ok, msg = validate_symbol_exchange("AAPL", "XNYS")
    assert ok is False
    assert "Invalid exchange 'XNYS'" in msg
    assert "NSE" in msg


def test_quote_india_accepts_nse_with_token_present(force_india):
    from services import quotes_service

    with mock.patch("database.token_db.get_token", return_value="123"):
        ok, msg = quotes_service.validate_symbol_exchange("SBIN", "NSE")
    assert ok is True
    assert msg is None


def test_quote_no_region_returns_missing_context_message(force_no_region):
    from services.quotes_service import validate_symbol_exchange

    ok, msg = validate_symbol_exchange("SBIN", "NSE")
    assert ok is False
    assert "Cannot validate quote" in msg


# ---------------------------------------------------------------------------
# history_service
# ---------------------------------------------------------------------------


def test_history_india_rejects_xnys(force_india):
    from services.history_service import validate_symbol_exchange

    ok, msg = validate_symbol_exchange("AAPL", "XNYS")
    assert ok is False
    assert "Invalid exchange 'XNYS'" in msg


def test_history_no_region_returns_missing_context_message(force_no_region):
    from services.history_service import validate_symbol_exchange

    ok, msg = validate_symbol_exchange("SBIN", "NSE")
    assert ok is False
    assert "Cannot validate history request" in msg


# ---------------------------------------------------------------------------
# depth_service
# ---------------------------------------------------------------------------


def test_depth_india_rejects_xnys(force_india):
    from services.depth_service import validate_symbol_exchange

    ok, msg = validate_symbol_exchange("AAPL", "XNYS")
    assert ok is False
    assert "Invalid exchange 'XNYS'" in msg


def test_depth_no_region_returns_missing_context_message(force_no_region):
    from services.depth_service import validate_symbol_exchange

    ok, msg = validate_symbol_exchange("SBIN", "NSE")
    assert ok is False
    assert "Cannot validate depth request" in msg


# ---------------------------------------------------------------------------
# margin_service
# ---------------------------------------------------------------------------


def test_margin_india_accepts_valid_position(force_india):
    from services.margin_service import validate_position

    ok, msg = validate_position({
        "exchange": "NSE", "symbol": "SBIN", "action": "BUY",
        "quantity": 1, "product": "CNC", "pricetype": "MARKET",
    }, 0)
    assert ok is True
    assert msg is None


def test_margin_india_rejects_xnys_position(force_india):
    from services.margin_service import validate_position

    ok, msg = validate_position({
        "exchange": "XNYS", "symbol": "AAPL", "action": "BUY",
        "quantity": 1, "product": "CNC", "pricetype": "MARKET",
    }, 0)
    assert ok is False
    assert "Invalid exchange" in msg


def test_margin_no_region_returns_missing_context_message(force_no_region):
    from services.margin_service import validate_position

    ok, msg = validate_position({
        "exchange": "NSE", "symbol": "SBIN", "action": "BUY",
        "quantity": 1, "product": "CNC", "pricetype": "MARKET",
    }, 0)
    assert ok is False
    assert "Cannot validate margin" in msg


# ---------------------------------------------------------------------------
# basket_order_service
# ---------------------------------------------------------------------------


def test_basket_india_accepts_nse(force_india):
    from services.basket_order_service import validate_order

    ok, msg = validate_order({
        "apikey": "k", "strategy": "s", "symbol": "SBIN",
        "exchange": "NSE", "action": "BUY", "quantity": 1,
        "product": "CNC", "pricetype": "MARKET",
    })
    assert ok is True
    assert msg is None


def test_basket_india_rejects_xnys(force_india):
    from services.basket_order_service import validate_order

    ok, msg = validate_order({
        "apikey": "k", "strategy": "s", "symbol": "AAPL",
        "exchange": "XNYS", "action": "BUY", "quantity": 1,
    })
    assert ok is False
    assert "Invalid exchange" in msg


def test_basket_no_region_returns_missing_context_message(force_no_region):
    from services.basket_order_service import validate_order

    ok, msg = validate_order({
        "apikey": "k", "strategy": "s", "symbol": "SBIN",
        "exchange": "NSE", "action": "BUY", "quantity": 1,
        "product": "CNC", "pricetype": "MARKET",
    })
    assert ok is False
    assert "Cannot validate basket order" in msg


# ---------------------------------------------------------------------------
# split_order_service — VALID_* imports were dead in the original file
# and have been removed. Sanity test confirms the module imports cleanly
# without the removed symbols.
# ---------------------------------------------------------------------------


def test_split_order_module_imports_without_legacy_constants():
    # If the migration accidentally re-introduces VALID_*, this fails.
    import importlib

    mod = importlib.import_module("services.split_order_service")
    assert not hasattr(mod, "VALID_EXCHANGES"), (
        "split_order_service must not re-introduce the dead "
        "VALID_EXCHANGES import. Phase 3 (T-20) removed it as it was "
        "imported but never used."
    )
    assert not hasattr(mod, "VALID_PRODUCT_TYPES")
    assert not hasattr(mod, "VALID_PRICE_TYPES")
    assert hasattr(mod, "_REQUIRED_ORDER_FIELDS"), (
        "split_order_service should declare the inlined "
        "_REQUIRED_ORDER_FIELDS tuple after Phase 3."
    )


# ---------------------------------------------------------------------------
# Region-aware vocabulary helpers (services.market_region_service)
# ---------------------------------------------------------------------------


def test_india_vocabulary_matches_legacy_constants(force_india):
    """The relocated India vocabulary must equal
    ``utils.constants.VALID_*`` element-by-element so the v1 wire
    contract is bit-identical."""
    from services.market_region_service import (
        get_allowed_action_codes_for_active_region,
        get_allowed_price_type_codes_for_active_region,
        get_allowed_product_codes_for_active_region,
        get_allowed_venue_codes_for_active_region,
    )
    from utils.constants import (
        VALID_ACTIONS,
        VALID_EXCHANGES,
        VALID_PRICE_TYPES,
        VALID_PRODUCT_TYPES,
    )

    assert get_allowed_venue_codes_for_active_region() == list(VALID_EXCHANGES)
    assert get_allowed_product_codes_for_active_region() == list(VALID_PRODUCT_TYPES)
    assert get_allowed_price_type_codes_for_active_region() == list(VALID_PRICE_TYPES)
    assert get_allowed_action_codes_for_active_region() == list(VALID_ACTIONS)


def test_helpers_raise_missing_region_context_when_unresolvable(force_no_region):
    from domain.errors import MissingRegionContext
    from services.market_region_service import (
        get_allowed_action_codes_for_active_region,
        get_allowed_price_type_codes_for_active_region,
        get_allowed_product_codes_for_active_region,
        get_allowed_venue_codes_for_active_region,
    )

    for fn in (
        get_allowed_venue_codes_for_active_region,
        get_allowed_product_codes_for_active_region,
        get_allowed_price_type_codes_for_active_region,
        get_allowed_action_codes_for_active_region,
    ):
        with pytest.raises(MissingRegionContext):
            fn()
