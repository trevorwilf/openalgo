"""Integration — the promoted /api/v2/orders lane increments the
right metrics on rule rejections and legacy fallbacks.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from database import broker_rules_repo
from database.instruments_repo import (
    BrokerMapRow,
    broker_map_upsert_many,
    instruments_create,
    venues_upsert,
)
from services.broker_translator_registry import (
    clear_registry_for_tests,
    register_broker_translator,
)
from tests.fakes.fake_us_translator import FakeUSTranslator
from utils import metrics


@pytest.fixture(autouse=True)
def _reset():
    metrics.reset_for_tests()
    clear_registry_for_tests()
    yield
    metrics.reset_for_tests()
    clear_registry_for_tests()


def _install_fake_auth_resolver(monkeypatch, broker_code: str):
    def fake_resolve_auth():
        return "fake-token", broker_code, None

    monkeypatch.setattr("restx_api.v2.orders.resolve_auth", fake_resolve_auth)


def _seed_aapl():
    venues_upsert(
        "XNAS",
        market_family="US_STOCK",
        country_code="US",
        base_currency="USD",
        timezone_name="America/New_York",
    )
    aapl = instruments_create(
        venue_code="XNAS",
        canonical_symbol="AAPL",
        asset_class="EQUITY",
        instrument_kind="CASH",
        tick_size=Decimal("0.01"),
        quantity_precision=6,
        currency="USD",
    )
    broker_map_upsert_many(
        broker_code="fake_us",
        venue_code="XNAS",
        sync_version=1,
        rows=[
            BrokerMapRow(
                external_symbol="AAPL",
                external_token="tok",
                instrument_id=aapl.instrument_id,
            )
        ],
    )


def _valid_order_body() -> dict:
    return {
        "apikey": "x",
        "instrument": {
            "venue_code": "XNAS",
            "canonical_symbol": "AAPL",
        },
        "side": "BUY",
        "order_type": "MARKET",
        "quantity": "1",
        "quantity_unit": "WHOLE",
        "time_in_force": "DAY",
    }


def test_no_rule_seeded_bumps_rule_rejections_counter(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_FAKE_US", "1")
    _install_fake_auth_resolver(monkeypatch, "fake_us")
    register_broker_translator(FakeUSTranslator())
    _seed_aapl()
    # No broker_rules row for fake_us — check_order raises
    # no_rule_matches.
    resp = flask_app.test_client().post("/api/v2/orders", json=_valid_order_body())
    assert resp.status_code == 422
    assert metrics.get_counter_value(
        "rule_rejections_total",
        {"broker": "fake_us", "code": "no_rule_matches"},
    ) == 1.0


def test_disallowed_order_type_bumps_rule_rejections_counter(flask_app, monkeypatch):
    broker_rules_repo.rules_upsert(
        broker_code="fake_us",
        venue_code=None,
        asset_class=None,
        session_name=None,
        allowed_order_types=["LIMIT"],   # MARKET is NOT allowed
        allowed_time_in_force=["DAY", "GTC"],
        allows_fractional=True,
        allows_notional=True,
    )
    monkeypatch.setenv("API_V2_FAKE_US", "1")
    _install_fake_auth_resolver(monkeypatch, "fake_us")
    register_broker_translator(FakeUSTranslator())
    _seed_aapl()
    resp = flask_app.test_client().post("/api/v2/orders", json=_valid_order_body())
    assert resp.status_code == 422
    assert metrics.get_counter_value(
        "rule_rejections_total",
        {"broker": "fake_us", "code": "order_type_not_allowed"},
    ) == 1.0


def test_flag_on_but_no_translator_records_legacy_fallback(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_FAKE_US", "1")
    _install_fake_auth_resolver(monkeypatch, "fake_us")
    # Do NOT register a translator — the dispatcher must fall back
    # and the fallback counter must increment.
    # Legacy path will 500/422 because there's no real broker — we
    # only care about the counter.
    flask_app.test_client().post("/api/v2/orders", json=_valid_order_body())
    assert metrics.get_counter_value(
        "promoted_legacy_fallback_total", {"broker": "fake_us"}
    ) >= 1.0


def test_flag_off_does_not_bump_fallback_counter(flask_app, monkeypatch):
    monkeypatch.delenv("API_V2_FAKE_US", raising=False)
    _install_fake_auth_resolver(monkeypatch, "fake_us")
    flask_app.test_client().post("/api/v2/orders", json=_valid_order_body())
    assert metrics.get_counter_value(
        "promoted_legacy_fallback_total", {"broker": "fake_us"}
    ) == 0.0
