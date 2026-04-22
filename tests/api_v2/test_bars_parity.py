"""/api/v2/bars — wraps v1 history service, adds instrument envelope."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pandas as pd

HIST_ROWS = [
    {"timestamp": 1700000000, "open": 100, "high": 105, "low": 99, "close": 104, "volume": 500},
    {"timestamp": 1700000060, "open": 104, "high": 106, "low": 103, "close": 105, "volume": 700},
]


class _FakeBrokerData:
    calls: list[tuple] = []

    def __init__(self, auth_token, feed_token=None):
        pass

    def get_history(self, symbol, exchange, interval, start, end):
        _FakeBrokerData.calls.append((symbol, exchange, interval, start, end))
        return pd.DataFrame(HIST_ROWS)


def test_bars_parity_with_v1(client) -> None:
    _FakeBrokerData.calls = []
    with (
        mock.patch(
            "restx_api.v2._auth.get_auth_token_broker",
            return_value=("fake-auth", None, "zerodha"),
        ),
        mock.patch(
            "services.history_service.validate_symbol_exchange",
            return_value=(True, None),
        ),
        mock.patch(
            "services.history_service.import_broker_module",
            return_value=SimpleNamespace(BrokerData=_FakeBrokerData),
        ),
    ):
        resp = client.post(
            "/api/v2/bars",
            json={
                "apikey": "fake",
                "instrument": {"venue_code": "NSE", "canonical_symbol": "RELIANCE"},
                "interval": "1m",
                "start": "2026-04-18",
                "end": "2026-04-21",
            },
        )
    assert resp.status_code == 200
    body = resp.get_json()["data"]
    assert body["instrument"]["canonical_symbol"] == "RELIANCE"
    assert body["interval"] == "1m"
    assert len(body["bars"]) == 2
    # Broker call exact match.
    assert _FakeBrokerData.calls == [
        ("RELIANCE", "NSE", "1m", "2026-04-18", "2026-04-21")
    ]


def test_bars_missing_fields_400(client) -> None:
    with mock.patch(
        "restx_api.v2._auth.get_auth_token_broker",
        return_value=("fake-auth", None, "zerodha"),
    ):
        resp = client.post("/api/v2/bars", json={"apikey": "fake"})
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "bad_request"
