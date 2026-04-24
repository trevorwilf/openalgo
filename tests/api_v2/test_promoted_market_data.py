"""Phase 4 — promoted-lane /api/v2/quotes and /api/v2/bars dispatch.

Asserts:

- with the flag on and a registered adapter, the legacy
  quotes_service / history_service / get_token / VALID_EXCHANGES are
  never touched;
- with the flag off, the legacy path still runs.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from database.instruments_repo import (
    BrokerMapRow,
    broker_map_upsert_many,
    instruments_create,
    venues_upsert,
)
from services.broker_market_data_registry import (
    clear_market_data_registries_for_tests,
)


@pytest.fixture(autouse=True)
def _clean():
    clear_market_data_registries_for_tests()
    yield
    clear_market_data_registries_for_tests()


def _install_fake_auth_resolver(monkeypatch, broker_code: str):
    def fake_resolve_auth():
        return "fake-token", broker_code, None

    monkeypatch.setattr("restx_api.v2.quotes.resolve_auth", fake_resolve_auth)
    monkeypatch.setattr("restx_api.v2.bars.resolve_auth", fake_resolve_auth)


def _seed_aapl(broker_code: str = "fake_us"):
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
        broker_code=broker_code,
        venue_code="XNAS",
        sync_version=1,
        rows=[
            BrokerMapRow(
                external_symbol="AAPL",
                external_token="FAKE-AAPL-TOKEN",
                instrument_id=aapl.instrument_id,
            )
        ],
    )
    return aapl.instrument_id


def _forbid_legacy_quotes_and_get_token(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*a, **kw):
        raise AssertionError("legacy symbol touched on promoted path")

    monkeypatch.setattr(
        "services.quotes_service.get_quotes_with_auth", _raise
    )
    monkeypatch.setattr(
        "services.history_service.get_history_with_auth", _raise
    )
    monkeypatch.setattr("database.token_db.get_token", _raise)


def test_promoted_quote_path_returns_fake_data(
    flask_app, monkeypatch
):
    from tests.fakes.fake_us_market_data import install_fake_us_market_data

    install_fake_us_market_data()
    monkeypatch.setenv("API_V2_FAKE_US", "1")
    _install_fake_auth_resolver(monkeypatch, broker_code="fake_us")
    _forbid_legacy_quotes_and_get_token(monkeypatch)
    _seed_aapl()

    client = flask_app.test_client()
    resp = client.post(
        "/api/v2/quotes",
        json={
            "apikey": "x",
            "instruments": [
                {"venue_code": "XNAS", "canonical_symbol": "AAPL"}
            ],
        },
    )
    assert resp.status_code == 200, resp.get_json()
    j = resp.get_json()
    assert len(j["data"]) == 1
    assert j["data"][0]["quote"]["bid"] == "100.01"
    assert j["data"][0]["quote"]["last"] == "100.02"


def test_promoted_bars_path_returns_fake_data(
    flask_app, monkeypatch
):
    from tests.fakes.fake_us_market_data import install_fake_us_market_data

    install_fake_us_market_data()
    monkeypatch.setenv("API_V2_FAKE_US", "1")
    _install_fake_auth_resolver(monkeypatch, broker_code="fake_us")
    _forbid_legacy_quotes_and_get_token(monkeypatch)
    _seed_aapl()

    client = flask_app.test_client()
    resp = client.post(
        "/api/v2/bars",
        json={
            "apikey": "x",
            "instrument": {"venue_code": "XNAS", "canonical_symbol": "AAPL"},
            "interval": "1m",
            "start": "2026-04-23T14:30:00+00:00",
            "end": "2026-04-23T15:00:00+00:00",
        },
    )
    assert resp.status_code == 200, resp.get_json()
    j = resp.get_json()
    assert j["data"]["interval"] == "1m"
    assert len(j["data"]["bars"]) == 3
    assert j["data"]["bars"][0]["open"] == "100.00"


def test_promoted_quote_path_missing_instrument_404_shape(
    flask_app, monkeypatch
):
    from tests.fakes.fake_us_market_data import install_fake_us_market_data

    install_fake_us_market_data()
    monkeypatch.setenv("API_V2_FAKE_US", "1")
    _install_fake_auth_resolver(monkeypatch, broker_code="fake_us")
    _forbid_legacy_quotes_and_get_token(monkeypatch)
    # NOTE: do not seed — the instrument universe is empty.

    client = flask_app.test_client()
    resp = client.post(
        "/api/v2/quotes",
        json={
            "apikey": "x",
            "instruments": [
                {"venue_code": "XNAS", "canonical_symbol": "AAPL"}
            ],
        },
    )
    # Quotes returns 200 with per-ref errors even when none resolved.
    assert resp.status_code == 200
    j = resp.get_json()
    assert j["data"][0]["error"]["code"] == "instrument_not_resolvable"


def test_flag_off_does_not_use_promoted_path(flask_app, monkeypatch):
    """With the flag off, the fake adapter is NOT called — legacy runs."""
    from tests.fakes.fake_us_market_data import install_fake_us_market_data

    install_fake_us_market_data()
    monkeypatch.delenv("API_V2_FAKE_US", raising=False)
    _install_fake_auth_resolver(monkeypatch, broker_code="fake_us")
    _seed_aapl()

    called = {"legacy": False}

    def _fake_quotes(**kwargs):
        called["legacy"] = True
        return True, {"data": {"ltp": 123.45}}, 200

    monkeypatch.setattr(
        "services.quotes_service.get_quotes_with_auth", _fake_quotes
    )

    client = flask_app.test_client()
    resp = client.post(
        "/api/v2/quotes",
        json={
            "apikey": "x",
            "instruments": [
                {"venue_code": "XNAS", "canonical_symbol": "AAPL"}
            ],
        },
    )
    assert resp.status_code == 200
    assert called["legacy"] is True
