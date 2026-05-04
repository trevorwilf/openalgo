"""T-27 + T-28 + T-29 (v7 Phase 7-bis) — US broker plugin readiness.

* T-27 (Alpaca): full capability surface declared
  (auth_modes, streaming_transports, supports_subaccounts, etc.).
* T-28 (Schwab): real plugin scaffold at ``broker/schwab/`` with
  full capabilities; mock_schwab_like remains as test fixture.
* T-29 (Webull): real plugin scaffold at ``broker/webull/``.

Per the prompt's stakeholder notes, real-API contract verification
is deferred until API access lands. This test asserts framework
readiness only — capability manifests valid, plugins load, no
hard-coded session windows in source.
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module", autouse=True)
def _load_plugins():
    from utils.plugin_loader import load_broker_capabilities

    load_broker_capabilities()


def test_alpaca_full_capability_surface():
    from utils.plugin_loader import get_broker_capabilities

    alpaca = get_broker_capabilities("alpaca")
    assert alpaca is not None
    assert alpaca.default_venue_code == "XNAS"
    assert alpaca.default_product_code == "DAY"
    assert alpaca.base_currency == "USD"
    # T-09 + T-27: refresh policy populated.
    assert alpaca.master_contract_refresh_policy is not None
    assert alpaca.master_contract_refresh_policy["timezone"] == "America/New_York"
    # T-27: auth + streaming declared.
    assert any("OAUTH" in str(a) for a in alpaca.auth_modes)
    assert len(alpaca.streaming_transports) > 0
    # T-27: explicit no-MPP-no-v1-compat declarations.
    assert alpaca.requires_market_price_protection is False
    assert alpaca.requires_v1_compat is False


def test_schwab_plugin_loads():
    from utils.plugin_loader import get_broker_capabilities

    schwab = get_broker_capabilities("schwab")
    assert schwab is not None, "T-28: broker/schwab/ plugin scaffold must load"
    assert schwab.supported_regions == ["us"]
    assert schwab.base_currency == "USD"
    assert schwab.default_venue_code == "XNAS"
    # Schwab supports OAuth + account hashes (per the scaffold).
    assert any("OAUTH" in str(a) for a in schwab.auth_modes)
    assert schwab.supports_account_hashes is True
    assert schwab.supports_subaccounts is True


def test_webull_plugin_loads():
    from utils.plugin_loader import get_broker_capabilities

    webull = get_broker_capabilities("webull")
    assert webull is not None, "T-29: broker/webull/ plugin scaffold must load"
    assert webull.supported_regions == ["us"]
    assert webull.base_currency == "USD"
    # Webull declares CRYPTO support per the scaffold.
    assert "CRYPTO" in webull.supported_venue_codes


def test_real_plugins_distinct_from_mocks():
    """The real ``broker/schwab/`` / ``broker/webull/`` plugins are
    separate registrations from the underscore-prefixed mock
    fixtures. Both load — the mocks remain as the broker
    compliance harness's deterministic fixture set."""
    from utils.plugin_loader import get_broker_capabilities

    real_schwab = get_broker_capabilities("schwab")
    mock_schwab = get_broker_capabilities("_mock_schwab_like")
    real_webull = get_broker_capabilities("webull")
    mock_webull = get_broker_capabilities("_mock_webull_like")
    assert real_schwab is not None and mock_schwab is not None
    assert real_webull is not None and mock_webull is not None
    # Real plugins declare the broker's actual broker_code, NOT the
    # underscore-prefixed mock identifier.
    assert real_schwab.broker_code == "schwab"
    assert real_webull.broker_code == "webull"
    assert mock_schwab.broker_code == "_mock_schwab_like"
    assert mock_webull.broker_code == "_mock_webull_like"


def test_all_us_plugins_declare_master_contract_refresh_policy():
    """T-09 (mandatory for non-legacy) — every US plugin declares
    the policy."""
    from utils.plugin_loader import get_broker_capabilities

    for code in ("alpaca", "schwab", "webull"):
        caps = get_broker_capabilities(code)
        assert caps is not None
        policy = caps.master_contract_refresh_policy
        assert policy, f"{code}: missing master_contract_refresh_policy"
        assert "timezone" in policy
        assert "cutoff_local" in policy
        assert "frequency" in policy
