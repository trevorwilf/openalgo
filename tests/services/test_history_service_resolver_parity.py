"""History service /api/v1 response byte-identical across three modes.

Mirrors test_quotes_service_resolver_parity.py for history's
`get_history_with_auth` entry point.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pandas as pd
import pytest

from database.instruments_repo import (
    BrokerMapRow,
    broker_map_upsert_many,
    instruments_create,
    sync_run_start,
    venues_upsert,
)


FAKE_HISTORY_ROWS = [
    {"timestamp": 1_776_993_900, "open": 100, "high": 105, "low": 99, "close": 104, "volume": 500},
    {"timestamp": 1_776_993_960, "open": 104, "high": 106, "low": 103, "close": 105, "volume": 700},
]


class _FakeBrokerData:
    calls: list[tuple[str, str, str, str, str]] = []

    def __init__(self, auth_token, feed_token=None):
        pass

    def get_history(self, symbol, exchange, interval, start, end):
        _FakeBrokerData.calls.append((symbol, exchange, interval, start, end))
        return pd.DataFrame(FAKE_HISTORY_ROWS)


@pytest.fixture(autouse=True)
def _reset_calls():
    _FakeBrokerData.calls = []
    yield


def _mocked_module():
    return SimpleNamespace(BrokerData=_FakeBrokerData)


def _call_service(monkeypatch):
    # Phase 3 (T-20) — history_service is PROMOTED_CORE; force India
    # so the region-aware validator accepts NSE.
    monkeypatch.setenv("MARKET_REGION_FOR_TESTS", "india")

    from services import history_service

    # Phase 3 (T-20): patch the source module — get_token is lazy.
    import database.token_db as _token_db

    monkeypatch.setattr(_token_db, "get_token", lambda s, e: "TOKEN-1")
    monkeypatch.setattr(
        history_service, "import_broker_module", lambda name: _mocked_module()
    )
    return history_service.get_history_with_auth(
        auth_token="fake-auth",
        feed_token=None,
        broker="zerodha",
        symbol="RELIANCE",
        exchange="NSE",
        interval="5m",
        start_date="2026-04-18",
        end_date="2026-04-21",
    )


def _expected_payload() -> dict:
    df = pd.DataFrame(FAKE_HISTORY_ROWS)
    df["oi"] = 0
    return {"status": "success", "data": df.to_dict(orient="records")}


def test_flag_off_baseline(fresh_db, monkeypatch, reset_default_resolver) -> None:
    monkeypatch.delenv("RESOLVER_V2", raising=False)
    ok, payload, status = _call_service(monkeypatch)
    assert ok is True
    assert status == 200
    assert payload == _expected_payload()


def test_flag_on_populated(fresh_db, monkeypatch, reset_default_resolver) -> None:
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    inst = instruments_create(
        venue_code="NSE",
        canonical_symbol="RELIANCE",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    r = sync_run_start("zerodha", "NSE")
    broker_map_upsert_many(
        "zerodha", "NSE",
        [BrokerMapRow("RELIANCE", "738561", inst.instrument_id)],
        sync_version=r.sync_version,
    )
    monkeypatch.setenv("RESOLVER_V2", "1")
    ok, payload, status = _call_service(monkeypatch)
    assert ok is True
    assert status == 200
    assert payload == _expected_payload()


def test_flag_on_empty_instruments(
    fresh_db, monkeypatch, reset_default_resolver
) -> None:
    monkeypatch.setenv("RESOLVER_V2", "1")
    ok, payload, status = _call_service(monkeypatch)
    assert ok is True
    assert status == 200
    assert payload == _expected_payload()


def test_flag_on_resolver_error_is_swallowed(
    fresh_db, monkeypatch, reset_default_resolver
) -> None:
    monkeypatch.setenv("RESOLVER_V2", "1")

    class _ExplodingResolver:
        def resolve_for_quote(self, **kwargs):
            raise RuntimeError("resolver boom")

    with mock.patch(
        "services.instrument_resolver.get_resolver",
        return_value=_ExplodingResolver(),
    ):
        ok, payload, status = _call_service(monkeypatch)
    assert ok is True
    assert status == 200
    assert payload == _expected_payload()
