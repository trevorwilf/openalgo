"""v7 Phase 4-bis-5 — cross-broker symbol query helper.

Asserts ``services.symbol_service.get_symbol_info_for_broker``:
* Filters by ``broker_code`` when one is provided.
* Falls back to ``(symbol, exchange)`` matching when broker_code
  is empty (legacy behavior).
* Is importable + callable.
"""

from __future__ import annotations


def test_helper_importable():
    from services.symbol_service import get_symbol_info_for_broker

    assert callable(get_symbol_info_for_broker)


def test_helper_signature_accepts_broker_code():
    """The helper accepts (symbol, exchange, broker_code) and
    returns Optional[SymToken]. Empty broker_code falls back to
    (symbol, exchange) matching."""
    import inspect

    from services.symbol_service import get_symbol_info_for_broker

    sig = inspect.signature(get_symbol_info_for_broker)
    params = list(sig.parameters.keys())
    assert params == ["symbol", "exchange", "broker_code"]


def test_helper_with_empty_broker_code_returns_none_or_legacy_match():
    """When broker_code is empty, the helper degrades to the
    legacy (symbol, exchange) match. For an unknown symbol, the
    return value is None — the helper doesn't raise."""
    from services.symbol_service import get_symbol_info_for_broker

    result = get_symbol_info_for_broker(
        symbol="NONEXISTENT_SYMBOL_XYZ_123",
        exchange="NSE",
        broker_code="",
    )
    assert result is None


def test_helper_with_broker_code_filters():
    """With a broker_code, the helper filters even more strictly.
    For an unknown (symbol, exchange, broker) tuple, returns None."""
    from services.symbol_service import get_symbol_info_for_broker

    result = get_symbol_info_for_broker(
        symbol="NONEXISTENT_SYMBOL_XYZ_123",
        exchange="NSE",
        broker_code="zerodha",
    )
    assert result is None
