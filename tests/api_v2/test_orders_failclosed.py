"""Phase 3 — promoted-lane fail-closed dispatch (ADR 0008).

Verifies that the v2 orders dispatcher:

* returns 503 ``translator_not_registered`` when the promoted flag is
  set but no translator is registered (never silently falls back to
  legacy);
* returns 422 ``unsupported_capability`` when the broker capabilities
  table excludes a requested order primitive;
* returns 422 ``rule_violation`` when ``check_order`` rejects;
* returns 503 ``promoted_lane_required_for_non_india_broker`` when the
  flag is *off* but the broker plugin's supported_regions excludes
  india AND broker_type isn't crypto;
* still serves the legacy lane bit-identically for India brokers
  with the flag off.
"""

from __future__ import annotations

import pytest

from database import broker_rules_repo
from services.broker_translator_registry import clear_registry_for_tests


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry_for_tests()
    yield
    clear_registry_for_tests()


def _install_fake_auth_resolver(monkeypatch, broker_code: str):
    def _fake():
        return "fake-token", broker_code, None

    monkeypatch.setattr("restx_api.v2.orders.resolve_auth", _fake)


def _valid_body(apikey: str = "k") -> dict:
    return {
        "apikey": apikey,
        "instrument": {"venue_code": "XNAS", "canonical_symbol": "AAPL"},
        "side": "BUY",
        "order_type": "MARKET",
        "quantity": "1",
        "quantity_unit": "WHOLE",
        "time_in_force": "DAY",
    }


def _seed_permissive_rule(broker: str, types=("MARKET", "LIMIT")):
    broker_rules_repo.rules_upsert(
        broker_code=broker,
        venue_code=None,
        asset_class=None,
        session_name=None,
        allowed_order_types=list(types),
        allowed_time_in_force=["DAY", "GTC"],
        allows_fractional=True,
        allows_notional=True,
        allows_short=True,
    )


def _stub_caps(monkeypatch, *, broker_code: str, supported_regions, broker_type,
               supported_order_types=("MARKET", "LIMIT"),
               supported_time_in_force=("DAY", "GTC"),
               supported_sessions=("REGULAR",),
               supported_quantity_units=("WHOLE",)):
    """Stub utils.plugin_loader.get_broker_capabilities for the lane check.

    Builds a small object that quacks like the BrokerCapabilities
    fields the dispatcher reads. Used so tests do not need to land a
    real broker plugin on disk.
    """
    from types import SimpleNamespace
    from domain.enums import OrderType, TimeInForce, Session, QuantityUnit

    caps = SimpleNamespace(
        broker_code=broker_code,
        supported_regions=list(supported_regions),
        broker_type=broker_type,
        supported_order_types=[OrderType(v) for v in supported_order_types],
        supported_time_in_force=[TimeInForce(v) for v in supported_time_in_force],
        supported_sessions=[Session(v) for v in supported_sessions],
        supported_quantity_units=[QuantityUnit(v) for v in supported_quantity_units],
        base_currency=None,
    )

    def _fake(name):
        return caps if name == broker_code else None

    monkeypatch.setattr("utils.plugin_loader.get_broker_capabilities", _fake)


# --- Tests ---------------------------------------------------------------


def test_promoted_flag_on_but_translator_missing_returns_503(
    flask_app, monkeypatch
):
    monkeypatch.setenv("API_V2_FAKE_US", "1")
    _install_fake_auth_resolver(monkeypatch, broker_code="fake_us")

    def _forbidden(*a, **kw):  # pragma: no cover
        raise AssertionError("legacy must not run on promoted-flag-on path")

    monkeypatch.setattr(
        "domain.translators.normalized_order_to_legacy_fields", _forbidden
    )

    resp = flask_app.test_client().post("/api/v2/orders", json=_valid_body())
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["error"]["code"] == "translator_not_registered"


def test_promoted_capability_missing_returns_422_unsupported(
    flask_app, monkeypatch
):
    """A registered translator + capabilities that do NOT include the
    requested order_type → 422 unsupported_capability."""
    from tests.fakes.fake_us_translator import install_fake_us_translator

    _seed_permissive_rule("fake_us")
    install_fake_us_translator()
    monkeypatch.setenv("API_V2_FAKE_US", "1")
    _install_fake_auth_resolver(monkeypatch, broker_code="fake_us")
    _stub_caps(
        monkeypatch,
        broker_code="fake_us",
        supported_regions=["us"],
        broker_type="US_stock",
        supported_order_types=("LIMIT",),  # no MARKET
    )

    body = _valid_body()  # MARKET — not supported per stub
    resp = flask_app.test_client().post("/api/v2/orders", json=body)
    assert resp.status_code == 422, resp.get_json()
    j = resp.get_json()
    assert j["error"]["code"] == "unsupported_capability"
    assert j["error"]["details"]["capability_name"] == "order_type"


def test_promoted_rule_violation_returns_422(flask_app, monkeypatch):
    """No matching rule → check_order raises → 422 rule_violation."""
    from tests.fakes.fake_us_translator import install_fake_us_translator

    install_fake_us_translator()  # registered, but no rule seeded
    monkeypatch.setenv("API_V2_FAKE_US", "1")
    _install_fake_auth_resolver(monkeypatch, broker_code="fake_us")
    _stub_caps(
        monkeypatch,
        broker_code="fake_us",
        supported_regions=["us"],
        broker_type="US_stock",
    )

    resp = flask_app.test_client().post("/api/v2/orders", json=_valid_body())
    assert resp.status_code == 422, resp.get_json()
    j = resp.get_json()
    assert j["error"]["code"] == "rule_violation"


def test_flag_off_non_india_non_crypto_broker_returns_503(
    flask_app, monkeypatch
):
    """A non-India broker may not silently use the legacy lane."""
    _install_fake_auth_resolver(monkeypatch, broker_code="fake_us")
    monkeypatch.delenv("API_V2_FAKE_US", raising=False)
    _stub_caps(
        monkeypatch,
        broker_code="fake_us",
        supported_regions=["us"],
        broker_type="US_stock",
    )

    def _forbidden(*a, **kw):  # pragma: no cover
        raise AssertionError("legacy must not run for non-India broker")

    monkeypatch.setattr(
        "domain.translators.normalized_order_to_legacy_fields", _forbidden
    )

    resp = flask_app.test_client().post("/api/v2/orders", json=_valid_body())
    assert resp.status_code == 503, resp.get_json()
    j = resp.get_json()
    assert j["error"]["code"] == "promoted_lane_required_for_non_india_broker"
    assert j["error"]["details"]["supported_regions"] == ["us"]


def test_flag_off_india_broker_uses_legacy(flask_app, monkeypatch):
    """India broker with flag off — legacy path runs as before."""
    _install_fake_auth_resolver(monkeypatch, broker_code="zerodha_test")
    monkeypatch.delenv("API_V2_ZERODHA_TEST", raising=False)
    _stub_caps(
        monkeypatch,
        broker_code="zerodha_test",
        supported_regions=[],  # legacy India plugin shape
        broker_type="IN_stock",
    )

    called = {"legacy": False}

    def _legacy(normalized):
        called["legacy"] = True
        return {"side": "BUY", "pricetype": "MARKET", "product": "MIS"}

    monkeypatch.setattr(
        "domain.translators.normalized_order_to_legacy_fields", _legacy
    )

    def _fake_place(auth_token, broker, order_data):
        return True, {"orderid": "leg-1", "order_status": "submitted"}, 200

    monkeypatch.setattr(
        "services.place_order_service.place_order_with_auth", _fake_place
    )

    resp = flask_app.test_client().post("/api/v2/orders", json=_valid_body())
    assert resp.status_code == 200
    assert called["legacy"] is True


def test_flag_off_crypto_broker_uses_legacy(flask_app, monkeypatch):
    """Crypto broker (broker_type=crypto) is allowed to legacy-fallback
    even when supported_regions excludes india."""
    _install_fake_auth_resolver(monkeypatch, broker_code="deltax_test")
    monkeypatch.delenv("API_V2_DELTAX_TEST", raising=False)
    _stub_caps(
        monkeypatch,
        broker_code="deltax_test",
        supported_regions=["crypto"],
        broker_type="crypto",
    )

    def _legacy(normalized):
        return {"side": "BUY", "pricetype": "MARKET", "product": "MIS"}

    monkeypatch.setattr(
        "domain.translators.normalized_order_to_legacy_fields", _legacy
    )

    def _fake_place(auth_token, broker, order_data):
        return True, {"orderid": "crypto-1", "order_status": "submitted"}, 200

    monkeypatch.setattr(
        "services.place_order_service.place_order_with_auth", _fake_place
    )

    resp = flask_app.test_client().post("/api/v2/orders", json=_valid_body())
    assert resp.status_code == 200
