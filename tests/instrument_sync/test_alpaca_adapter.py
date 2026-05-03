"""Alpaca instrument-sync adapter — fixture-driven normalization.

Drives :class:`AlpacaAdapter.fetch_raw` from a local JSON fixture and
asserts the :class:`NormalizedInstrumentRow` it yields.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from services.instrument_sync_adapters import ADAPTERS, AlpacaAdapter

FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "alpaca_assets_sample.json"
)


def test_alpaca_adapter_is_registered():
    assert ADAPTERS.get("alpaca") is AlpacaAdapter


def test_fetch_raw_yields_fixture_rows():
    adapter = AlpacaAdapter(json_path=FIXTURE)
    rows = list(adapter.fetch_raw())
    assert len(rows) == 7
    assert rows[0]["symbol"] == "AAPL"


def test_normalize_aapl_nasdaq():
    adapter = AlpacaAdapter(json_path=FIXTURE)
    rows = list(adapter.fetch_raw())
    norm = adapter.normalize(rows[0])
    assert norm is not None
    assert norm.canonical_symbol == "AAPL"
    assert norm.venue_code == "XNAS"
    assert norm.market_family == "US_STOCK"
    assert norm.venue_timezone == "America/New_York"
    assert norm.asset_class == "EQUITY"
    assert norm.instrument_kind == "CASH"
    assert norm.currency == "USD"
    assert norm.tick_size == Decimal("0.01")
    assert norm.quantity_precision == 9  # fractionable
    assert norm.external_symbol == "AAPL"
    assert norm.external_token == "b0b6dd9d-8b9b-48a9-ba46-b9d54906e415"
    assert norm.display_name == "Apple Inc. Common Stock"


def test_normalize_jpm_nyse():
    adapter = AlpacaAdapter(json_path=FIXTURE)
    norm = adapter.normalize(
        {
            "id": "x",
            "symbol": "JPM",
            "exchange": "NYSE",
            "class": "us_equity",
            "fractionable": True,
        }
    )
    assert norm is not None
    assert norm.venue_code == "XNYS"


def test_normalize_arca_routed_correctly():
    adapter = AlpacaAdapter(json_path=FIXTURE)
    norm = adapter.normalize(
        {"id": "x", "symbol": "SPY", "exchange": "ARCA", "class": "us_equity"}
    )
    assert norm is not None
    assert norm.venue_code == "ARCX"


def test_normalize_bats_routed_correctly():
    adapter = AlpacaAdapter(json_path=FIXTURE)
    norm = adapter.normalize(
        {"id": "x", "symbol": "VOO", "exchange": "BATS", "class": "us_equity"}
    )
    assert norm is not None
    assert norm.venue_code == "BATS"


def test_normalize_amex_folds_to_xnys():
    """AMEX is a NYSE subsidiary; canonical venue is XNYS."""
    adapter = AlpacaAdapter(json_path=FIXTURE)
    norm = adapter.normalize(
        {"id": "x", "symbol": "GLD", "exchange": "AMEX", "class": "us_equity"}
    )
    assert norm is not None
    assert norm.venue_code == "XNYS"


def test_normalize_otc_folds_to_xnas():
    adapter = AlpacaAdapter(json_path=FIXTURE)
    norm = adapter.normalize(
        {"id": "x", "symbol": "RDDT", "exchange": "OTC", "class": "us_equity"}
    )
    assert norm is not None
    assert norm.venue_code == "XNAS"


def test_normalize_unmapped_exchange_is_skipped():
    adapter = AlpacaAdapter(json_path=FIXTURE)
    norm = adapter.normalize(
        {"id": "x", "symbol": "BAYRY", "exchange": "PINK", "class": "us_equity"}
    )
    assert norm is None


def test_normalize_empty_symbol_is_skipped():
    adapter = AlpacaAdapter(json_path=FIXTURE)
    assert adapter.normalize({"exchange": "NASDAQ", "class": "us_equity"}) is None


def test_normalize_unsupported_asset_class_is_skipped():
    adapter = AlpacaAdapter(json_path=FIXTURE)
    norm = adapter.normalize(
        {
            "id": "x",
            "symbol": "ZZZZ",
            "exchange": "NASDAQ",
            "class": "options_contract",  # not implemented yet
        }
    )
    assert norm is None


def test_normalize_crypto_routed_to_spot():
    adapter = AlpacaAdapter(json_path=FIXTURE)
    norm = adapter.normalize(
        {
            "id": "x",
            "symbol": "BTC/USD",
            "exchange": "NASDAQ",  # Alpaca crypto uses class, not exchange
            "class": "crypto",
        }
    )
    assert norm is not None
    assert norm.asset_class == "SPOT"


def test_normalize_non_fractionable_uses_zero_quantity_precision():
    adapter = AlpacaAdapter(json_path=FIXTURE)
    norm = adapter.normalize(
        {
            "id": "x",
            "symbol": "VOO",
            "exchange": "BATS",
            "class": "us_equity",
            "fractionable": False,
        }
    )
    assert norm is not None
    assert norm.quantity_precision == 0


def test_normalize_propagates_metadata_flags():
    adapter = AlpacaAdapter(json_path=FIXTURE)
    rows = list(adapter.fetch_raw())
    norm = adapter.normalize(rows[0])  # AAPL
    assert norm is not None
    assert norm.metadata is not None
    assert norm.metadata["alpaca_class"] == "us_equity"
    assert norm.metadata["alpaca_exchange"] == "NASDAQ"
    assert norm.metadata["tradable"] is True
    assert norm.metadata["shortable"] is True
    assert norm.metadata["fractionable"] is True


def test_normalize_emits_broker_token_identifier():
    adapter = AlpacaAdapter(json_path=FIXTURE)
    rows = list(adapter.fetch_raw())
    norm = adapter.normalize(rows[0])
    assert norm is not None
    assert len(norm.identifiers) == 1
    ident = norm.identifiers[0]
    assert ident.identifier_type == "BROKER_TOKEN"
    assert ident.broker_code == "alpaca"
    assert ident.venue_code == "XNAS"
    assert ident.identifier_value == "b0b6dd9d-8b9b-48a9-ba46-b9d54906e415"
