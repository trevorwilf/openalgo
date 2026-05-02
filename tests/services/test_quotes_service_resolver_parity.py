"""Quote service /api/v1 response is byte-identical across three modes:

* flag OFF (default): pure legacy path
* flag ON + instruments table populated: resolver hits, logs, legacy broker call
* flag ON + instruments table empty: resolver falls through (miss or legacy
  fallback), logs, legacy broker call still succeeds

In all three cases, the mocked broker module is called with the same
(symbol, exchange) and the service returns the same dict.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest import mock

import pytest

from database.instruments_repo import (
    BrokerMapRow,
    broker_map_upsert_many,
    instruments_create,
    sync_run_start,
    venues_upsert,
)


FAKE_BROKER_QUOTE = {"ltp": 2900.5, "volume": 1234567, "bid": 2900.0, "ask": 2900.5}


class _FakeBrokerData:
    """Imitates the broker modules' `BrokerData` contract."""

    calls: list[tuple[str, str]] = []

    def __init__(self, auth_token, feed_token=None):
        _FakeBrokerData.calls.append(("init", auth_token))

    def get_quotes(self, symbol: str, exchange: str):
        _FakeBrokerData.calls.append((symbol, exchange))
        return dict(FAKE_BROKER_QUOTE)


@pytest.fixture(autouse=True)
def _reset_broker_calls():
    _FakeBrokerData.calls = []
    yield


def _mocked_broker_module():
    return SimpleNamespace(BrokerData=_FakeBrokerData)


def _call_service(monkeypatch) -> tuple[bool, dict, int]:
    """Run `get_quotes_with_auth` with every external dependency mocked."""
    import os

    # Phase 3 (T-20) — quotes_service is now PROMOTED_CORE and uses
    # the active region's vocabulary; force India for parity testing.
    monkeypatch.setenv("MARKET_REGION_FOR_TESTS", "india")

    from services import quotes_service

    # Phase 3 (T-20): patch the source module — `get_token` is now
    # imported lazily inside validate_symbol_exchange.
    import database.token_db as _token_db

    monkeypatch.setattr(_token_db, "get_token", lambda s, e: "TOKEN-1")
    monkeypatch.setattr(
        quotes_service, "import_broker_module",
        lambda name: _mocked_broker_module(),
    )
    return quotes_service.get_quotes_with_auth(
        auth_token="fake-auth",
        feed_token=None,
        broker="zerodha",
        symbol="RELIANCE",
        exchange="NSE",
    )


def test_flag_off_baseline(fresh_db, monkeypatch, reset_default_resolver) -> None:
    monkeypatch.delenv("RESOLVER_V2", raising=False)
    ok, payload, status = _call_service(monkeypatch)
    assert ok is True
    assert status == 200
    assert payload == {"status": "success", "data": FAKE_BROKER_QUOTE}


def test_flag_on_with_instruments_table_populated(
    fresh_db, monkeypatch, reset_default_resolver
) -> None:
    # Populate the new instrument universe so the resolver hits.
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

    # Byte-identical to flag-off mode
    assert ok is True
    assert status == 200
    assert payload == {"status": "success", "data": FAKE_BROKER_QUOTE}
    # Broker module invoked with the same (symbol, exchange)
    assert ("RELIANCE", "NSE") in _FakeBrokerData.calls


def test_flag_on_with_empty_instruments_table_still_byte_identical(
    fresh_db, monkeypatch, reset_default_resolver
) -> None:
    # Do NOT populate instruments. Resolver misses cleanly and logs —
    # legacy path still serves the quote.
    monkeypatch.setenv("RESOLVER_V2", "1")
    ok, payload, status = _call_service(monkeypatch)
    assert ok is True
    assert status == 200
    assert payload == {"status": "success", "data": FAKE_BROKER_QUOTE}


def test_flag_on_resolver_error_does_not_500(
    fresh_db, monkeypatch, reset_default_resolver
) -> None:
    """A bug inside the resolver MUST NOT break the quote path."""
    monkeypatch.setenv("RESOLVER_V2", "1")
    from services import quotes_service

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
    assert payload == {"status": "success", "data": FAKE_BROKER_QUOTE}
