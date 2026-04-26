"""Phase 4 v3 (ADR 0020) — region gate sanity tests for the
service-layer surfaces newly gated to India.

For each gated service, two assertions:

1. With ``MARKET_REGION_FOR_TESTS=us`` the entry point returns the
   structured ``*_disabled_in_region`` error and HTTP 422.
2. With ``MARKET_REGION_FOR_TESTS=india`` the gate is passed; the
   inner call may still fail (no DB / no API key in tests) but it
   does NOT short-circuit at the region gate.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch):
    monkeypatch.delenv("MARKET_REGION_FOR_TESTS", raising=False)


def test_expiry_service_us_region_returns_gate_error(monkeypatch):
    monkeypatch.setenv("MARKET_REGION_FOR_TESTS", "us")
    from services.expiry_service import get_expiry_dates

    ok, payload, status = get_expiry_dates(
        symbol="AAPL", exchange="XNAS", instrumenttype="options", api_key="x"
    )
    assert ok is False
    assert status == 422
    assert payload["code"] == "expiry_grammar_not_supported_in_region"


def test_expiry_service_india_region_passes_gate(monkeypatch):
    monkeypatch.setenv("MARKET_REGION_FOR_TESTS", "india")
    from services.expiry_service import get_expiry_dates

    _ok, payload, _status = get_expiry_dates(
        symbol="NIFTY", exchange="NFO", instrumenttype="options", api_key="x"
    )
    assert payload.get("code") != "expiry_grammar_not_supported_in_region"


def test_iv_chart_us_region_returns_gate_error(monkeypatch):
    monkeypatch.setenv("MARKET_REGION_FOR_TESTS", "us")
    from services.iv_chart_service import get_iv_chart_data

    ok, payload, status = get_iv_chart_data(
        underlying="AAPL", exchange="XNAS", expiry_date="06FEB26",
        interval="5m", api_key="x",
    )
    assert ok is False
    assert status == 422
    assert payload["code"] == "iv_chart_disabled_in_region"


def test_gex_us_region_returns_gate_error(monkeypatch):
    monkeypatch.setenv("MARKET_REGION_FOR_TESTS", "us")
    from services.gex_service import get_gex_data

    ok, payload, status = get_gex_data(
        underlying="AAPL", exchange="XNAS", expiry_date="06FEB26", api_key="x"
    )
    assert ok is False
    assert status == 422
    assert payload["code"] == "gex_disabled_in_region"


def test_option_greeks_us_region_returns_gate_error(monkeypatch):
    monkeypatch.setenv("MARKET_REGION_FOR_TESTS", "us")
    from services.option_greeks_service import get_option_greeks

    ok, payload, status = get_option_greeks(
        option_symbol="AAPL250118C00200000",
        exchange="OPRA",
        api_key="x",
    )
    assert ok is False
    assert status == 422
    assert payload["code"] == "option_greeks_disabled_in_region"


def test_options_multiorder_us_region_returns_gate_error(monkeypatch):
    monkeypatch.setenv("MARKET_REGION_FOR_TESTS", "us")
    # `services.options_multiorder_service` participates in a known
    # pre-existing circular import via `services.place_order_service`
    # → `restx_api/__init__.py` → `restx_api/options_multiorder.py`
    # → back to `services.options_multiorder_service`. We pre-import
    # restx_api so the cycle resolves through the already-loaded
    # package.
    import restx_api  # noqa: F401  pre-load to break the cycle
    import services.options_multiorder_service as svc

    ok, payload, status = svc.place_options_multiorder(
        multiorder_data={"underlying": "AAPL", "exchange": "OPRA", "legs": []},
        api_key="x",
    )
    assert ok is False
    assert status == 422
    assert payload["code"] == "multi_option_disabled_in_region"


def test_synthetic_future_us_region_returns_gate_error(monkeypatch):
    monkeypatch.setenv("MARKET_REGION_FOR_TESTS", "us")
    from services.synthetic_future_service import calculate_synthetic_future

    ok, payload, status = calculate_synthetic_future(
        underlying="AAPL", exchange="XNAS", expiry_date="06FEB26", api_key="x"
    )
    assert ok is False
    assert status == 422
    assert payload["code"] == "synthetic_future_disabled_in_region"


def test_straddle_chart_us_region_returns_gate_error(monkeypatch):
    monkeypatch.setenv("MARKET_REGION_FOR_TESTS", "us")
    from services.straddle_chart_service import get_straddle_chart_data

    ok, payload, status = get_straddle_chart_data(
        underlying="AAPL", exchange="XNAS", expiry_date="06FEB26",
        interval="1m", api_key="x",
    )
    assert ok is False
    assert status == 422
    assert payload["code"] == "straddle_chart_disabled_in_region"


def test_vol_surface_us_region_returns_gate_error(monkeypatch):
    monkeypatch.setenv("MARKET_REGION_FOR_TESTS", "us")
    from services.vol_surface_service import get_vol_surface_data

    ok, payload, status = get_vol_surface_data(
        underlying="AAPL", exchange="XNAS", expiry_dates=["06FEB26"],
        strike_count=10, api_key="x",
    )
    assert ok is False
    assert status == 422
    assert payload["code"] == "vol_surface_disabled_in_region"


def test_flow_executor_us_region_returns_gate_error(monkeypatch):
    monkeypatch.setenv("MARKET_REGION_FOR_TESTS", "us")
    from services.flow_executor_service import execute_workflow

    out = execute_workflow(workflow_id=1, api_key="x")
    assert out["status"] == "error"
    assert out["code"] == "flow_templates_disabled_in_region"


def test_require_region_feature_raises_for_disabled(monkeypatch):
    """Direct test of the new helper in feature_gate_service."""
    monkeypatch.setenv("MARKET_REGION_FOR_TESTS", "us")
    from domain.errors import FeatureNotAvailableInRegion
    from services.feature_gate_service import require_region_feature

    with pytest.raises(FeatureNotAvailableInRegion) as excinfo:
        require_region_feature(
            "iv_chart_enabled", "iv_chart_disabled_in_region"
        )
    assert excinfo.value.code == "iv_chart_disabled_in_region"
    assert excinfo.value.active_region == "us"


def test_require_region_feature_passes_when_enabled(monkeypatch):
    """When the flag is enabled the helper returns silently. Loads the
    market region plugin cache directly since we don't have a Flask
    app context in this test."""
    monkeypatch.setenv("MARKET_REGION_FOR_TESTS", "india")
    from services.feature_gate_service import require_region_feature
    from utils import region_loader

    # Force-load the bundled region plugins so the cache has 'india'
    # regardless of whether Flask app context is available.
    repo_root = __import__("pathlib").Path(__file__).resolve().parents[2]
    region_dir = str(repo_root / "market_regions")
    region_loader._reset_cache_for_tests()
    region_loader.load_market_regions(region_dir)
    try:
        require_region_feature(
            "option_chain_enabled", "option_chain_disabled_in_region"
        )
    finally:
        region_loader._reset_cache_for_tests()
