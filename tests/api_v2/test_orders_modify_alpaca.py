"""POST /api/v2/orders/<id>/modify dispatch — mocked Alpaca.

Pins the new v2 modify route's contract:
1. Route exists and dispatches to the broker translator's
   ``modify_order_via_token``.
2. Alpaca translator maps canonical fields onto Alpaca's PATCH body
   (qty / limit_price / stop_price / time_in_force / client_order_id).
3. Empty-body modify returns 422 ``validation_error``.
4. Alpaca's structured 4xx errors surface with the alpaca code.
"""
from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from broker.alpaca.api.auth_api import AlpacaAuth, DATA_BASE_URL, PAPER_BASE_URL
from broker.alpaca.api.order_api import AlpacaOrderTranslator
from broker.alpaca.sync.seed_rules import seed_alpaca_rules
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


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry_for_tests()
    yield
    clear_registry_for_tests()


def _paper_auth() -> AlpacaAuth:
    return AlpacaAuth(
        base_url=PAPER_BASE_URL,
        data_base_url=DATA_BASE_URL,
        headers={"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"},
    )


def _install_fake_auth_resolver(monkeypatch):
    def fake_resolve_auth():
        return "fake-token", "alpaca", None
    monkeypatch.setattr("restx_api.v2.orders.resolve_auth", fake_resolve_auth)


def _seed_aapl():
    venues_upsert(
        "XNAS", market_family="US_STOCK", country_code="US",
        base_currency="USD", timezone_name="America/New_York",
    )
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


def _modify_client(captured: dict, *, status: int = 200, body=None):
    """MockTransport that captures the PATCH body and returns ``body``."""
    body = body or {
        "id": "ord-1", "status": "new", "qty": "5",
        "limit_price": "2.50", "client_order_id": "coid-1",
    }

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "PATCH" and req.url.path.startswith("/v2/orders/"):
            captured["url"] = str(req.url)
            captured["body"] = req.read().decode()
            return httpx.Response(status, json=body)
        return httpx.Response(404, json={"message": "no route"})

    auth = _paper_auth()
    return httpx.Client(
        base_url=auth.base_url,
        headers=dict(auth.headers),
        transport=httpx.MockTransport(handler),
    )


def test_modify_dispatches_to_alpaca_translator(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth_resolver(monkeypatch)
    _seed_aapl()
    seed_alpaca_rules()

    captured = {}
    auth = _paper_auth()
    client = _modify_client(captured)
    register_broker_translator(AlpacaOrderTranslator(auth=auth, client=client))

    resp = flask_app.test_client().post(
        "/api/v2/orders/ord-1/modify",
        json={"apikey": "x", "quantity": "5", "price": "2.50"},
    )
    client.close()
    assert resp.status_code == 200, resp.get_json()
    j = resp.get_json()["data"]
    assert j["order_id"] == "ord-1"
    assert j["status"] == "modified"
    # Verify Alpaca-shaped fields landed in the PATCH body.
    import json as _json
    sent = _json.loads(captured["body"])
    assert sent["qty"] == "5"
    assert sent["limit_price"] == "2.50"
    # Non-supplied fields must NOT be in the body (else Alpaca rejects).
    assert "stop_price" not in sent
    assert "time_in_force" not in sent
    # Echoed Alpaca response is preserved under broker_response.
    assert j["broker_response"]["id"] == "ord-1"


def test_modify_translates_time_in_force(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth_resolver(monkeypatch)
    _seed_aapl()
    seed_alpaca_rules()

    captured = {}
    auth = _paper_auth()
    client = _modify_client(captured)
    register_broker_translator(AlpacaOrderTranslator(auth=auth, client=client))

    resp = flask_app.test_client().post(
        "/api/v2/orders/ord-1/modify",
        json={"apikey": "x", "time_in_force": "GTC"},
    )
    client.close()
    assert resp.status_code == 200, resp.get_json()
    import json as _json
    sent = _json.loads(captured["body"])
    assert sent["time_in_force"] == "gtc"  # canonical 'GTC' → alpaca 'gtc'


def test_modify_empty_body_returns_422(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth_resolver(monkeypatch)
    _seed_aapl()
    seed_alpaca_rules()

    auth = _paper_auth()
    captured = {}
    client = _modify_client(captured)
    register_broker_translator(AlpacaOrderTranslator(auth=auth, client=client))

    resp = flask_app.test_client().post(
        "/api/v2/orders/ord-1/modify",
        json={"apikey": "x"},
    )
    client.close()
    assert resp.status_code == 422
    assert resp.get_json()["error"]["code"] == "validation_error"
    # Translator must not have been called.
    assert "url" not in captured


def test_modify_alpaca_4xx_surfaces_alpaca_code(flask_app, monkeypatch):
    """Alpaca's structured 422 (e.g. 'cannot replace order in accepted
    status') must propagate with its alpaca code visible to the
    operator instead of httpx's generic message."""
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth_resolver(monkeypatch)
    _seed_aapl()
    seed_alpaca_rules()

    captured = {}
    auth = _paper_auth()
    client = _modify_client(
        captured,
        status=422,
        body={"code": 42210000, "message": "cannot replace order in accepted status"},
    )
    register_broker_translator(AlpacaOrderTranslator(auth=auth, client=client))

    resp = flask_app.test_client().post(
        "/api/v2/orders/ord-x/modify",
        json={"apikey": "x", "price": "2.50"},
    )
    client.close()
    assert resp.status_code == 502
    err_msg = resp.get_json()["error"]["message"]
    assert "alpaca" in err_msg.lower()
    assert "42210000" in err_msg
    assert "cannot replace" in err_msg


def test_modify_no_translator_returns_503(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth_resolver(monkeypatch)
    # No translator registered.
    resp = flask_app.test_client().post(
        "/api/v2/orders/ord-1/modify",
        json={"apikey": "x", "price": "2.50"},
    )
    assert resp.status_code == 503
    assert resp.get_json()["error"]["code"] == "translator_not_registered"
