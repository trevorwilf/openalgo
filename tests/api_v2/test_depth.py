"""POST /api/v2/depth — capability boundary + dispatch."""
from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from broker.alpaca.api.auth_api import AlpacaAuth, DATA_BASE_URL, PAPER_BASE_URL
from broker.alpaca.api.order_api import AlpacaOrderTranslator
from broker.alpaca.sync.seed_rules import seed_alpaca_rules
from database.instruments_repo import (
    BrokerMapRow, broker_map_upsert_many, instruments_create, venues_upsert,
)
from services.broker_translator_registry import (
    clear_registry_for_tests, register_broker_translator,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry_for_tests()
    yield
    clear_registry_for_tests()


def _paper_auth():
    return AlpacaAuth(
        base_url=PAPER_BASE_URL,
        data_base_url=DATA_BASE_URL,
        headers={"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"},
    )


def _install_fake_auth(monkeypatch, broker="alpaca"):
    monkeypatch.setattr(
        "restx_api.v2.depth.resolve_auth",
        lambda: ("fake-token", broker, None),
    )


def _seed_aapl():
    venues_upsert("XNAS", market_family="US_STOCK", country_code="US",
                   base_currency="USD", timezone_name="America/New_York")
    aapl = instruments_create(
        venue_code="XNAS", canonical_symbol="AAPL",
        asset_class="EQUITY", instrument_kind="CASH",
        tick_size=Decimal("0.01"), quantity_precision=9, currency="USD",
    )
    broker_map_upsert_many(
        broker_code="alpaca", venue_code="XNAS", sync_version=1,
        rows=[BrokerMapRow(external_symbol="AAPL",
                           external_token="alpaca-aapl-id",
                           instrument_id=aapl.instrument_id)],
    )


def test_depth_alpaca_returns_501_unimplemented(flask_app, monkeypatch):
    """Alpaca's v2 stocks API doesn't expose L2 — translator
    intentionally lacks ``get_depth_via_token`` → 501 with a clear
    fallback hint pointing at /api/v2/quotes for top-of-book."""
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    _seed_aapl()
    seed_alpaca_rules()

    auth = _paper_auth()
    client = httpx.Client(base_url=auth.base_url, headers=dict(auth.headers),
                           transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    register_broker_translator(AlpacaOrderTranslator(auth=auth, client=client))

    resp = flask_app.test_client().post("/api/v2/depth", json={
        "apikey": "x",
        "instruments": [{"venue_code": "XNAS", "canonical_symbol": "AAPL"}],
    })
    client.close()
    assert resp.status_code == 501
    err = resp.get_json()["error"]
    assert err["code"] == "unimplemented"
    assert err["details"]["fallback_route"] == "/api/v2/quotes"


def test_depth_no_translator_returns_503(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    resp = flask_app.test_client().post("/api/v2/depth", json={
        "apikey": "x",
        "instruments": [{"venue_code": "XNAS", "canonical_symbol": "AAPL"}],
    })
    assert resp.status_code == 503
    assert resp.get_json()["error"]["code"] == "translator_not_registered"


def test_depth_flag_off_returns_503(flask_app, monkeypatch):
    monkeypatch.delenv("API_V2_ALPACA", raising=False)
    _install_fake_auth(monkeypatch)
    resp = flask_app.test_client().post("/api/v2/depth", json={
        "apikey": "x",
        "instruments": [{"venue_code": "XNAS", "canonical_symbol": "AAPL"}],
    })
    assert resp.status_code == 503
    assert resp.get_json()["error"]["code"] == "promoted_lane_required"


def test_depth_with_translator_returns_ladder(flask_app, monkeypatch):
    """If a (hypothetical) translator implements get_depth_via_token,
    the route returns the ladder. Pin the dispatch contract."""
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    _seed_aapl()
    seed_alpaca_rules()

    class _StubTranslator(AlpacaOrderTranslator):
        broker_code = "alpaca"
        def get_depth_via_token(self, auth_token, instrument):
            return {
                "bids": [{"price": "281.40", "qty": "100"},
                         {"price": "281.39", "qty": "200"}],
                "asks": [{"price": "281.42", "qty": "150"},
                         {"price": "281.43", "qty": "300"}],
                "ltp": "281.41",
            }

    auth = _paper_auth()
    client = httpx.Client(base_url=auth.base_url, headers=dict(auth.headers),
                           transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    register_broker_translator(_StubTranslator(auth=auth, client=client))

    resp = flask_app.test_client().post("/api/v2/depth", json={
        "apikey": "x",
        "instruments": [{"venue_code": "XNAS", "canonical_symbol": "AAPL"}],
    })
    client.close()
    assert resp.status_code == 200, resp.get_json()
    rows = resp.get_json()["data"]
    assert len(rows) == 1
    assert rows[0]["instrument"]["canonical_symbol"] == "AAPL"
    assert rows[0]["depth"]["bids"][0]["price"] == "281.40"
    assert rows[0]["depth"]["asks"][0]["price"] == "281.42"


def test_depth_unresolvable_instrument_per_row(flask_app, monkeypatch):
    """Per-row unresolvable: rest of batch still returns; the bad row
    carries an inline error."""
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    _seed_aapl()
    seed_alpaca_rules()

    class _StubTranslator(AlpacaOrderTranslator):
        def get_depth_via_token(self, auth_token, instrument):
            return {"bids": [], "asks": []}

    auth = _paper_auth()
    client = httpx.Client(base_url=auth.base_url, headers=dict(auth.headers),
                           transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    register_broker_translator(_StubTranslator(auth=auth, client=client))

    resp = flask_app.test_client().post("/api/v2/depth", json={
        "apikey": "x",
        "instruments": [
            {"venue_code": "XNAS", "canonical_symbol": "AAPL"},
            {"venue_code": "XNAS", "canonical_symbol": "ZZZNOTREAL"},
        ],
    })
    client.close()
    assert resp.status_code == 200
    rows = resp.get_json()["data"]
    assert len(rows) == 2
    assert "depth" in rows[0]
    assert "error" in rows[1]
    assert rows[1]["error"]["code"] == "instrument_not_resolvable"


def test_depth_empty_instruments_returns_400(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    _seed_aapl()
    seed_alpaca_rules()

    class _StubTranslator(AlpacaOrderTranslator):
        def get_depth_via_token(self, auth_token, instrument):
            return {}

    auth = _paper_auth()
    client = httpx.Client(base_url=auth.base_url, headers=dict(auth.headers),
                           transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    register_broker_translator(_StubTranslator(auth=auth, client=client))

    resp = flask_app.test_client().post("/api/v2/depth", json={
        "apikey": "x", "instruments": [],
    })
    client.close()
    assert resp.status_code == 400
