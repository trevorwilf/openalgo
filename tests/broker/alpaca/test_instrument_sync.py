"""Alpaca instrument sync — idempotency, mapping, audit trail."""

from __future__ import annotations

from pathlib import Path

import pytest

from broker.alpaca.sync.instrument_sync import BROKER_CODE, latest_run, sync_instruments
from database import instruments_repo
from database.instruments_repo import (
    broker_map_lookup_by_symbol,
    instruments_get_by_venue_symbol,
)


ASSET_SET_A = [
    {
        "id": "alpaca-aapl-id",
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "exchange": "NASDAQ",
        "class": "us_equity",
        "status": "active",
        "tradable": True,
        "shortable": True,
        "easy_to_borrow": True,
        "fractionable": True,
    },
    {
        "id": "alpaca-msft-id",
        "symbol": "MSFT",
        "name": "Microsoft Corporation",
        "exchange": "NASDAQ",
        "class": "us_equity",
        "status": "active",
        "tradable": True,
        "shortable": True,
        "easy_to_borrow": True,
        "fractionable": True,
    },
    {
        "id": "alpaca-jpm-id",
        "symbol": "JPM",
        "name": "JPMorgan Chase & Co.",
        "exchange": "NYSE",
        "class": "us_equity",
        "status": "active",
        "tradable": True,
        "shortable": True,
        "easy_to_borrow": True,
        "fractionable": False,
    },
]


ASSET_SET_A_MINUS_MSFT = [r for r in ASSET_SET_A if r["symbol"] != "MSFT"]


@pytest.fixture
def fresh_instrument_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_file = tmp_path / "alpaca_sync.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    instruments_repo._reset_engine_for_tests()
    instruments_repo.init_instrument_tables()
    yield db_file
    instruments_repo._reset_engine_for_tests()


def test_first_run_populates_instruments_and_map(fresh_instrument_db):
    summary = sync_instruments(assets=ASSET_SET_A)
    assert summary.fetched_count == 3
    assert summary.new_instruments == 3
    assert summary.map_rows_written == 3

    aapl = instruments_get_by_venue_symbol("XNAS", "AAPL")
    assert aapl is not None
    assert aapl.currency == "USD"

    jpm = instruments_get_by_venue_symbol("XNYS", "JPM")
    assert jpm is not None

    mapped = broker_map_lookup_by_symbol(
        broker_code=BROKER_CODE, venue_code="XNAS", external_symbol="AAPL"
    )
    assert mapped is not None
    assert mapped.external_token == "alpaca-aapl-id"


def test_second_run_same_fixture_is_idempotent(fresh_instrument_db):
    s1 = sync_instruments(assets=ASSET_SET_A)
    s2 = sync_instruments(assets=ASSET_SET_A)

    # New instruments = 0 on second run.
    assert s1.new_instruments == 3
    assert s2.new_instruments == 0
    # Map rows are still upserted (count matches input length).
    assert s2.map_rows_written == 3


def test_second_run_missing_asset_does_not_delete(fresh_instrument_db):
    sync_instruments(assets=ASSET_SET_A)
    s2 = sync_instruments(assets=ASSET_SET_A_MINUS_MSFT)

    # The disappeared row is NOT removed from instruments.
    msft = instruments_get_by_venue_symbol("XNAS", "MSFT")
    assert msft is not None

    # The second run reports 2 fetched; the audit row should reflect this.
    assert s2.fetched_count == 2


def test_sync_run_recorded_in_audit_table(fresh_instrument_db):
    sync_instruments(assets=ASSET_SET_A)
    run = latest_run()
    assert run is not None
    assert run.broker_code == BROKER_CODE
    assert run.status == "ok"
    assert run.instrument_count == 3
    assert run.metadata_json["new_instruments"] == 3


# ---------------------------------------------------------------------------
# Crypto canonical-symbol form — OpenAlgo uses dash (BTC-USD), Alpaca
# uses slash (BTC/USD). The sync MUST store the dash form as
# ``canonical_symbol`` so v2 callers can resolve by canonical, while
# the broker_map row keeps the slash form as ``external_symbol``.
# ---------------------------------------------------------------------------


CRYPTO_ASSETS = [
    {
        "id": "alpaca-btcusd-id",
        "symbol": "BTC/USD",
        "name": "Bitcoin",
        "exchange": "CRYPTO",
        "class": "crypto",
        "status": "active",
        "tradable": True,
        "fractionable": True,
        "min_order_size": "0.000000001",
        "min_trade_increment": "0.000000001",
        "price_increment": "1",
    },
    {
        "id": "alpaca-ethusd-id",
        "symbol": "ETH/USD",
        "name": "Ethereum",
        "exchange": "CRYPTO",
        "class": "crypto",
        "status": "active",
        "tradable": True,
        "fractionable": True,
    },
]


def test_crypto_canonical_symbol_uses_dash(fresh_instrument_db):
    """Crypto canonical_symbol = OpenAlgo form (BTC-USD), not Alpaca form."""
    sync_instruments(assets=CRYPTO_ASSETS)

    btc_canonical = instruments_get_by_venue_symbol("ALPACA_CRYPTO", "BTC-USD")
    assert btc_canonical is not None, (
        "canonical lookup by 'BTC-USD' must succeed — the sync should "
        "have stored the dash form so v2 callers resolve correctly"
    )

    # The slash form must NOT be the canonical key.
    btc_slash = instruments_get_by_venue_symbol("ALPACA_CRYPTO", "BTC/USD")
    assert btc_slash is None


def test_crypto_broker_map_keeps_slash_form(fresh_instrument_db):
    """``broker_map.external_symbol`` keeps Alpaca's slash form so the
    order layer's ``broker_native_symbol`` round-trips correctly to
    ``POST /v2/orders``.
    """
    sync_instruments(assets=CRYPTO_ASSETS)

    mapped = broker_map_lookup_by_symbol(
        broker_code=BROKER_CODE,
        venue_code="ALPACA_CRYPTO",
        external_symbol="BTC/USD",
    )
    assert mapped is not None
    assert mapped.external_token == "alpaca-btcusd-id"
