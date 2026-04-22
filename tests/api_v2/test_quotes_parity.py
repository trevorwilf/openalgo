"""/api/v2/quotes parity with /api/v1 broker dispatch.

The test injects a mocked broker module. The v2 endpoint MUST invoke
the broker's `get_quotes(symbol, exchange)` with exactly the same
arguments the v1 service would pass. v2's response is a superset of
v1's — it wraps the v1 broker payload under `quote` and adds an
`instrument` envelope.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock


BROKER_QUOTE = {"ltp": 2900.5, "volume": 1234, "bid": 2900.0, "ask": 2900.5}


class _FakeBrokerData:
    calls: list[tuple[str, str]] = []

    def __init__(self, auth_token, feed_token=None):
        pass

    def get_quotes(self, symbol, exchange):
        _FakeBrokerData.calls.append((symbol, exchange))
        return dict(BROKER_QUOTE)


def _reset_calls():
    _FakeBrokerData.calls = []


def _mock_auth():
    return mock.patch(
        "restx_api.v2._auth.get_auth_token_broker",
        return_value=("fake-auth", None, "zerodha"),
    )


def _mock_quotes_service():
    return mock.patch(
        "services.quotes_service.import_broker_module",
        return_value=SimpleNamespace(BrokerData=_FakeBrokerData),
    )


def _mock_validate():
    return mock.patch(
        "services.quotes_service.validate_symbol_exchange", return_value=(True, None)
    )


def test_v2_quotes_calls_broker_with_same_args_as_v1(client) -> None:
    _reset_calls()
    with _mock_auth(), _mock_quotes_service(), _mock_validate():
        resp = client.post(
            "/api/v2/quotes",
            json={
                "apikey": "fake",
                "instruments": [
                    {"venue_code": "NSE", "canonical_symbol": "RELIANCE"}
                ],
            },
        )

    assert resp.status_code == 200
    # The broker module received the exact same (symbol, exchange) pair
    # that v1's broker module would receive.
    assert _FakeBrokerData.calls == [("RELIANCE", "NSE")]

    body = resp.get_json()["data"]
    assert len(body) == 1
    assert body[0]["instrument"]["venue_code"] == "NSE"
    assert body[0]["instrument"]["canonical_symbol"] == "RELIANCE"
    # v2 envelope wraps the v1 broker payload under `quote`.
    assert body[0]["quote"] == BROKER_QUOTE


def test_v2_quotes_accepts_legacy_symbol_exchange_shape(client) -> None:
    _reset_calls()
    with _mock_auth(), _mock_quotes_service(), _mock_validate():
        resp = client.post(
            "/api/v2/quotes",
            json={
                "apikey": "fake",
                "instruments": [{"symbol": "INFY", "exchange": "NSE"}],
            },
        )
    assert resp.status_code == 200
    assert _FakeBrokerData.calls == [("INFY", "NSE")]


def test_v2_quotes_unresolvable_ref_included_with_error(client) -> None:
    _reset_calls()
    with _mock_auth():
        resp = client.post(
            "/api/v2/quotes",
            json={
                "apikey": "fake",
                "instruments": [{"nonsense": "data"}],
            },
        )
    assert resp.status_code == 200
    body = resp.get_json()["data"]
    assert len(body) == 1
    assert body[0]["error"]["code"] == "instrument_not_resolvable"


def test_v2_quotes_missing_apikey_401(client) -> None:
    resp = client.post("/api/v2/quotes", json={"instruments": []})
    assert resp.status_code == 401
    assert resp.get_json()["error"]["code"] == "unauthorized"


def test_v2_quotes_empty_instruments_400(client) -> None:
    with _mock_auth():
        resp = client.post("/api/v2/quotes", json={"apikey": "fake", "instruments": []})
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "bad_request"
