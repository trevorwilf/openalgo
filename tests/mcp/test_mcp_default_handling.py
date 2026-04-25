"""Phase 5 — mcp/mcpserver default substitution.

Loads ``mcp.mcpserver`` with stubbed sys.argv + a stubbed openalgo
client, then exercises ``_resolve_default`` and the converted
``place_order`` / ``get_quote`` tools to assert:

* India brokers: omitted exchange/product receive NSE/MIS substitutes.
* Non-India brokers: omitted exchange/product return a structured
  ``missing_required_field`` JSON error referencing
  ``/api/v2/capabilities/<broker>``.
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def mcp_module(monkeypatch, tmp_path):
    """Load the local `mcp/mcpserver.py` script (the installed `mcp`
    pip package shadows it as a top-level import, so we go through
    importlib.util to pick up the file directly).
    """
    monkeypatch.setattr(sys, "argv", ["mcp", "test-key", "http://localhost:5000"])

    # Stub the openalgo SDK so importing mcpserver does not actually
    # talk to a Flask app.
    fake_api = SimpleNamespace(
        placeorder=lambda **kwargs: {"orderid": "stub-1", **kwargs},
        placesmartorder=lambda **kwargs: {"orderid": "stub-2", **kwargs},
        quotes=lambda **kwargs: {"data": {"ltp": 1.0}, **kwargs},
        capabilities=lambda: None,
    )

    def _fake_api(api_key, host):
        return fake_api

    fake_openalgo = SimpleNamespace(api=_fake_api)
    monkeypatch.setitem(sys.modules, "openalgo", fake_openalgo)

    import importlib.util
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    src = repo_root / "mcp" / "mcpserver.py"
    spec = importlib.util.spec_from_file_location(
        "_mcp_mcpserver_under_test", src
    )
    assert spec is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)  # type: ignore[union-attr]

    m._connected_broker_caps.cache_clear()
    yield m
    m._connected_broker_caps.cache_clear()


def test_india_broker_substitutes_defaults(mcp_module, monkeypatch):
    monkeypatch.setenv("MCP_FORCE_REGION_FOR_TESTS", "india")
    mcp_module._connected_broker_caps.cache_clear()

    assert mcp_module._is_india_broker() is True
    assert mcp_module._resolve_default(None, "NSE", field_name="exchange") == "NSE"
    assert mcp_module._resolve_default(None, "MIS", field_name="product") == "MIS"


def test_non_india_broker_raises_when_field_missing(mcp_module, monkeypatch):
    monkeypatch.setenv("MCP_FORCE_REGION_FOR_TESTS", "us")
    mcp_module._connected_broker_caps.cache_clear()

    assert mcp_module._is_india_broker() is False
    with pytest.raises(ValueError) as exc:
        mcp_module._resolve_default(None, "NSE", field_name="exchange")
    assert "non-India" in str(exc.value)
    assert "/api/v2/capabilities/" in str(exc.value)


def test_non_india_broker_accepts_explicit_value(mcp_module, monkeypatch):
    monkeypatch.setenv("MCP_FORCE_REGION_FOR_TESTS", "us")
    mcp_module._connected_broker_caps.cache_clear()

    assert mcp_module._resolve_default("XNAS", "NSE", field_name="exchange") == "XNAS"


def test_unknown_broker_falls_back_to_legacy(mcp_module, monkeypatch):
    monkeypatch.delenv("MCP_FORCE_REGION_FOR_TESTS", raising=False)
    mcp_module._connected_broker_caps.cache_clear()
    # capabilities() returns None per the fixture stub → unknown.
    # _is_india_broker treats unknown as India for backward compat.
    assert mcp_module._is_india_broker() is True


def test_place_order_india_default_substituted(mcp_module, monkeypatch):
    monkeypatch.setenv("MCP_FORCE_REGION_FOR_TESTS", "india")
    mcp_module._connected_broker_caps.cache_clear()

    raw = mcp_module.place_order(
        symbol="reliance", quantity=1, action="BUY"
    )
    payload = json.loads(raw)
    assert payload["exchange"] == "NSE"
    assert payload["product"] == "MIS"


def test_place_order_non_india_no_exchange_returns_structured_error(
    mcp_module, monkeypatch
):
    monkeypatch.setenv("MCP_FORCE_REGION_FOR_TESTS", "us")
    mcp_module._connected_broker_caps.cache_clear()

    raw = mcp_module.place_order(symbol="AAPL", quantity=1, action="BUY")
    payload = json.loads(raw)
    assert payload["status"] == "error"
    assert payload["code"] == "missing_required_field"
    assert "non-India" in payload["message"]


def test_place_order_non_india_with_explicit_values(mcp_module, monkeypatch):
    monkeypatch.setenv("MCP_FORCE_REGION_FOR_TESTS", "us")
    mcp_module._connected_broker_caps.cache_clear()

    raw = mcp_module.place_order(
        symbol="AAPL",
        quantity=1,
        action="BUY",
        exchange="XNAS",
        product="DAY",
    )
    payload = json.loads(raw)
    assert payload["exchange"] == "XNAS"
    assert payload["product"] == "DAY"


def test_get_quote_india_default(mcp_module, monkeypatch):
    monkeypatch.setenv("MCP_FORCE_REGION_FOR_TESTS", "india")
    mcp_module._connected_broker_caps.cache_clear()
    raw = mcp_module.get_quote(symbol="reliance")
    payload = json.loads(raw)
    assert payload["exchange"] == "NSE"


def test_get_quote_non_india_no_exchange_returns_error(mcp_module, monkeypatch):
    monkeypatch.setenv("MCP_FORCE_REGION_FOR_TESTS", "us")
    mcp_module._connected_broker_caps.cache_clear()
    raw = mcp_module.get_quote(symbol="AAPL")
    payload = json.loads(raw)
    assert payload["status"] == "error"
    assert payload["code"] == "missing_required_field"
