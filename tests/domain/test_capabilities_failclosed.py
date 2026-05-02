"""Phase 1 fail-closed capability inference (ADR 0006).

Verifies:
* Legacy India broker plugins (no ``supported_regions``) keep IN_stock
  inference exactly as before.
* Crypto plugins with no ``supported_regions`` keep crypto inference
  unchanged.
* Plugins whose ``supported_regions`` excludes "india" must declare
  the four explicit fields or raise ``BrokerCapabilityError``.
* Setting ``STRICT_CAPABILITY_INFERENCE=0`` downgrades the failure to
  a warning (the rollback escape hatch).
"""

from __future__ import annotations

import pytest

from domain.capabilities import infer_capabilities_from_legacy
from domain.errors import BrokerCapabilityError


# --- legacy India parity -------------------------------------------------


def test_legacy_indian_plugin_with_explicit_supported_regions_inferred() -> None:
    """Zerodha-shaped plugin: gets IN_stock + INR defaults.

    Phase 1 T-03: legacy India plugins are required to declare
    ``supported_regions=["india"]`` explicitly (the migration commit
    in this branch added the field to all 32 shipped plugins). The
    earlier "no supported_regions = legacy India" auto-inference is
    retired.
    """
    plugin = {
        "Plugin Name": "zerodha",
        "supported_regions": ["india"],  # Phase 1 T-03: now required
        "supported_exchanges": ["NSE", "BSE", "NFO", "BFO"],
        "broker_type": "IN_stock",
        "leverage_config": False,
    }
    caps = infer_capabilities_from_legacy(plugin, "zerodha")
    assert caps["base_currency"].value == "INR"
    assert caps["supports_analyzer"] is True
    assert caps["supported_venue_codes"] == ["NSE", "BSE", "NFO", "BFO"]


def test_legacy_indian_plugin_with_supported_regions_india_inferred() -> None:
    """Explicit single-region india still falls into the legacy path."""
    plugin = {
        "supported_exchanges": ["NSE"],
        "broker_type": "IN_stock",
        "supported_regions": ["india"],
    }
    caps = infer_capabilities_from_legacy(plugin, "demo_in")
    assert caps["base_currency"].value == "INR"


def test_legacy_crypto_plugin_with_explicit_supported_regions_inferred() -> None:
    """Crypto broker plugin: gets crypto + USDT defaults.

    Phase 1 T-03: must declare supported_regions explicitly. Delta
    Exchange is India-served (SEBI static IP), so the migration
    commit declared ``supported_regions=["india"]`` on its
    plugin.json. The crypto inference still runs because the
    inference picks the branch on ``broker_type``, not region.
    """
    plugin = {
        "Plugin Name": "deltaexchange",
        "supported_regions": ["india"],  # Phase 1 T-03: now required
        "supported_exchanges": ["CRYPTO"],
        "broker_type": "crypto",
    }
    caps = infer_capabilities_from_legacy(plugin, "deltaexchange")
    assert caps["base_currency"].value == "USDT"


# --- non-India fail-closed ---------------------------------------------


def test_promoted_us_plugin_missing_broker_type_raises(monkeypatch) -> None:
    monkeypatch.delenv("STRICT_CAPABILITY_INFERENCE", raising=False)
    plugin = {
        "Plugin Name": "fakeus",
        "supported_regions": ["us"],
        # missing: broker_type, market_families, default_currency, base_currency
    }
    with pytest.raises(BrokerCapabilityError) as exc:
        infer_capabilities_from_legacy(plugin, "fakeus")
    assert "broker_type" in exc.value.missing_fields
    assert "default_currency" in exc.value.missing_fields
    assert exc.value.broker_code == "fakeus"


def test_promoted_us_plugin_with_explicit_fields_passes(monkeypatch) -> None:
    monkeypatch.delenv("STRICT_CAPABILITY_INFERENCE", raising=False)
    plugin = {
        "Plugin Name": "fakeus",
        "broker_type": "US_stock",
        "supported_regions": ["us"],
        "market_families": ["US_STOCK"],
        "default_currency": "USD",
        "base_currency": "USD",
        "supported_exchanges": ["XNAS", "XNYS"],
    }
    caps = infer_capabilities_from_legacy(plugin, "fakeus")
    # No silent IN_stock leak.
    assert caps["base_currency"] == "USD"
    assert caps["market_families"] == ["US_STOCK"]


def test_alpaca_plugin_passes_failclosed_check(monkeypatch) -> None:
    """The shipped Alpaca plugin already declares all required fields."""
    monkeypatch.delenv("STRICT_CAPABILITY_INFERENCE", raising=False)
    import json
    from pathlib import Path

    plugin_path = (
        Path(__file__).resolve().parents[2] / "broker" / "alpaca" / "plugin.json"
    )
    plugin_data = json.loads(plugin_path.read_text(encoding="utf-8"))
    caps = infer_capabilities_from_legacy(plugin_data, "alpaca")
    assert caps["base_currency"] == "USD"


def test_strict_off_warns_and_continues(monkeypatch, caplog) -> None:
    """Operator-side rollback: STRICT_CAPABILITY_INFERENCE=0 turns the
    raise into a warning so existing deployments are not blocked."""
    monkeypatch.setenv("STRICT_CAPABILITY_INFERENCE", "0")
    plugin = {
        "Plugin Name": "fakeus",
        "supported_regions": ["us"],
    }
    with caplog.at_level("WARNING", logger="domain.capabilities"):
        caps = infer_capabilities_from_legacy(plugin, "fakeus")
    # Inference still produced *something* — we don't assert on shape;
    # the contract is "do not crash boot".
    assert caps["broker_code"] == "fakeus"
    assert any(
        "STRICT_CAPABILITY_INFERENCE disabled" in rec.message
        for rec in caplog.records
    )
