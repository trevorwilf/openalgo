"""Phase 6 — option_symbol_service region gate."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch):
    monkeypatch.delenv("MARKET_REGION_FOR_TESTS", raising=False)


def test_us_region_returns_option_chain_disabled(monkeypatch) -> None:
    monkeypatch.setenv("MARKET_REGION_FOR_TESTS", "us")
    from services.option_symbol_service import get_option_symbol

    ok, payload, status = get_option_symbol(
        underlying="AAPL",
        exchange="XNAS",
        expiry_date=None,
        strike_int=None,
        offset="ATM",
        option_type="CALL",
        api_key="x",
    )
    assert ok is False
    assert status == 422
    assert payload["code"] == "option_chain_disabled"


def test_india_region_proceeds_past_gate(monkeypatch) -> None:
    """India region passes the gate; the call may still fail downstream
    (no DB / no API key) but it does NOT short-circuit at the gate."""
    monkeypatch.setenv("MARKET_REGION_FOR_TESTS", "india")
    from services.option_symbol_service import get_option_symbol

    ok, payload, status = get_option_symbol(
        underlying="NIFTY",
        exchange="NSE_INDEX",
        expiry_date=None,  # missing — error will come from the inner code
        strike_int=None,
        offset="ATM",
        option_type="CE",
        api_key="x",
    )
    # Either way, the gate did not return 422 option_chain_disabled.
    # India default behavior may return 400 expiry-date-required or 500;
    # both signal that the gate was passed.
    assert payload.get("code") != "option_chain_disabled"
