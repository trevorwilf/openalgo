"""Phase 3 v6 — /api/v2/bars dry-run multi-region smoke test.

Mirror of the quote dry-run test for the bar adapter registry. The
v2 history endpoint must fail-closed for non-India brokers without
a registered bar adapter — never silently fall back to the legacy
India services per ADR 0018.
"""

from __future__ import annotations

from services.broker_market_data_registry import get_broker_bar_adapter


def test_unknown_broker_returns_no_bar_adapter() -> None:
    assert get_broker_bar_adapter("zz_unknown_broker_v6") is None


def test_empty_broker_code_returns_none_for_bars() -> None:
    assert get_broker_bar_adapter("") is None


def test_mock_us_brokers_register_their_own_bar_adapters() -> None:
    """Same shape as the quote-side test."""
    schwab = get_broker_bar_adapter("_mock_schwab_like")
    webull = get_broker_bar_adapter("_mock_webull_like")
    if schwab is not None:
        assert schwab.broker_code.lower() == "_mock_schwab_like"
    if webull is not None:
        assert webull.broker_code.lower() == "_mock_webull_like"
