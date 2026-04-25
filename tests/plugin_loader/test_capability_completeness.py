"""Phase 3 — plugin_loader capability completeness gate (ADR 0008).

Non-India plugins must declare the full required-fields set or the
loader skips them. Legacy India plugins are unaffected.
"""

from __future__ import annotations

import pytest

from utils import plugin_loader


@pytest.fixture(autouse=True)
def _reset(reset_loader_state):
    yield


def _legacy_indian(extra: dict | None = None) -> dict:
    base = {
        "Plugin Name": "legacy_in",
        "broker_type": "IN_stock",
        "supported_exchanges": ["NSE"],
    }
    if extra:
        base.update(extra)
    return base


def _full_us(extra: dict | None = None) -> dict:
    base = {
        "Plugin Name": "fake_us",
        "broker_type": "US_stock",
        "supported_regions": ["us"],
        "market_families": ["US_STOCK"],
        "default_currency": "USD",
        "base_currency": "USD",
        "supported_venue_codes": ["XNAS"],
        "supported_asset_classes": ["EQUITY"],
        "supported_order_types": ["MARKET", "LIMIT"],
        "supported_time_in_force": ["DAY"],
        "supported_sessions": ["REGULAR"],
        "supported_quantity_units": ["WHOLE"],
        "trading_currencies": ["USD"],
    }
    if extra:
        base.update(extra)
    return base


def test_legacy_indian_plugin_loads_without_full_fields(
    make_broker_tree, chdir
) -> None:
    """No supported_regions → completeness gate doesn't fire."""
    make_broker_tree({"legacy_in": _legacy_indian()})
    caps = plugin_loader.load_broker_capabilities("broker")
    assert "legacy_in" in caps


def test_full_us_plugin_loads(make_broker_tree, chdir) -> None:
    make_broker_tree({"fake_us": _full_us()})
    caps = plugin_loader.load_broker_capabilities("broker")
    assert "fake_us" in caps
    assert caps["fake_us"].broker_code == "fake_us"


def test_us_plugin_missing_supported_order_types_skipped(
    make_broker_tree, chdir, caplog, monkeypatch
) -> None:
    monkeypatch.delenv("STRICT_CAPABILITY_INFERENCE", raising=False)
    p = _full_us()
    p.pop("supported_order_types")
    make_broker_tree({"fake_us": p})
    with caplog.at_level("ERROR"):
        caps = plugin_loader.load_broker_capabilities("broker")
    assert "fake_us" not in caps
    assert "fake_us" in plugin_loader._skipped_brokers_for_tests()
    assert any("supported_order_types" in rec.message for rec in caplog.records)


def test_us_plugin_missing_multiple_required_fields_lists_them(
    make_broker_tree, chdir, caplog, monkeypatch
) -> None:
    monkeypatch.delenv("STRICT_CAPABILITY_INFERENCE", raising=False)
    p = _full_us()
    for field in ("supported_order_types", "supported_quantity_units", "default_currency"):
        p.pop(field, None)
    make_broker_tree({"fake_us": p})
    with caplog.at_level("ERROR"):
        plugin_loader.load_broker_capabilities("broker")
    err_msgs = " ".join(rec.message for rec in caplog.records)
    for field in ("supported_order_types", "supported_quantity_units", "default_currency"):
        assert field in err_msgs


def test_strict_off_loads_incomplete_us_plugin(
    make_broker_tree, chdir, caplog, monkeypatch
) -> None:
    """STRICT_CAPABILITY_INFERENCE=0 downgrades skip to warning."""
    monkeypatch.setenv("STRICT_CAPABILITY_INFERENCE", "0")
    p = _full_us()
    p.pop("supported_quantity_units")
    make_broker_tree({"fake_us": p})
    with caplog.at_level("WARNING"):
        caps = plugin_loader.load_broker_capabilities("broker")
    # The completeness gate is skipped, but the underlying inference
    # may still raise via Phase 1's stricter check (4 currency/family
    # fields). Phase 1's check also honors STRICT_CAPABILITY_INFERENCE=0
    # and warns — so the plugin should load.
    assert "fake_us" in caps
    assert any(
        "STRICT_CAPABILITY_INFERENCE" in rec.message
        or "incomplete" in rec.message
        for rec in caplog.records
    )
