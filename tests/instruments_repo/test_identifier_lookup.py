"""Phase 3 v3 / ADR 0019 — IdentifierKind enum + convenience helpers.

Covers each identifier kind end-to-end, with an emphasis on the
scoping semantics:

* Globally unique (ISIN/CUSIP/SEDOL/FIGI/RIC) — broker_code=None,
  venue_code=None.
* Venue-scoped (VENUE_SYMBOL) — venue_code matters, broker_code=None.
* Broker-scoped (BROKER_SYMBOL/BROKER_TOKEN) — broker_code matters,
  venue_code optional but recommended.
* Cross-region (CANONICAL_SYMBOL) — both None.

Also covers the ambiguity case: more-than-one match returns ``None``.
"""

from __future__ import annotations

import pytest

from database import instruments_repo
from database.instruments_repo import IdentifierKind


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase3_identifiers.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    instruments_repo._reset_engine_for_tests()
    instruments_repo.init_instrument_tables()
    yield db_file
    instruments_repo._reset_engine_for_tests()


def _aapl(fresh_db):
    instruments_repo.venues_upsert(
        venue_code="XNAS",
        market_family="US_STOCK",
        timezone_name="America/New_York",
        country_code="US",
        base_currency="USD",
    )
    return instruments_repo.instruments_create(
        venue_code="XNAS",
        canonical_symbol="AAPL",
        asset_class="EQUITY",
        instrument_kind="EQUITY",
        currency="USD",
    )


@pytest.mark.parametrize(
    "kind",
    [
        IdentifierKind.ISIN,
        IdentifierKind.CUSIP,
        IdentifierKind.SEDOL,
        IdentifierKind.FIGI,
        IdentifierKind.RIC,
        IdentifierKind.CANONICAL_SYMBOL,
    ],
)
def test_global_identifier_kinds_round_trip(fresh_db, kind):
    """Globally unique identifiers — broker_code/venue_code=None."""
    aapl = _aapl(fresh_db)
    instruments_repo.identifier_add(
        instrument_id=aapl.instrument_id,
        identifier_type=kind.value,
        identifier_value=f"FAKE-{kind.value}-1",
    )
    found = instruments_repo.identifier_resolve_one_instrument(
        kind, f"FAKE-{kind.value}-1"
    )
    assert found is not None
    assert found.instrument_id == aapl.instrument_id


def test_venue_scoped_identifier_kind(fresh_db):
    """VENUE_SYMBOL — same value can repeat across venues; the
    venue_code filter is required."""
    aapl = _aapl(fresh_db)
    instruments_repo.identifier_add(
        instrument_id=aapl.instrument_id,
        identifier_type=IdentifierKind.VENUE_SYMBOL.value,
        identifier_value="AAPL",
        venue_code="XNAS",
    )
    found = instruments_repo.identifier_resolve_one_instrument(
        IdentifierKind.VENUE_SYMBOL, "AAPL", venue_code="XNAS"
    )
    assert found is not None
    assert found.instrument_id == aapl.instrument_id

    # Without the venue filter the row is still found (only one such)
    found_unscoped = instruments_repo.identifier_resolve_one_instrument(
        IdentifierKind.VENUE_SYMBOL, "AAPL"
    )
    # With venue=None the helper passes broker_code=None, venue_code=None
    # which doesn't match the row that was inserted with venue_code="XNAS".
    # Confirm that scoping is honored.
    assert found_unscoped is None


def test_broker_scoped_identifier_kind_token(fresh_db):
    aapl = _aapl(fresh_db)
    instruments_repo.identifier_add(
        instrument_id=aapl.instrument_id,
        identifier_type=IdentifierKind.BROKER_TOKEN.value,
        identifier_value="ALPACA-AAPL-001",
        broker_code="alpaca",
        venue_code="XNAS",
    )
    found = instruments_repo.identifier_resolve_one_instrument(
        IdentifierKind.BROKER_TOKEN,
        "ALPACA-AAPL-001",
        broker_code="alpaca",
        venue_code="XNAS",
    )
    assert found is not None
    assert found.instrument_id == aapl.instrument_id


def test_ambiguous_match_returns_none(fresh_db):
    """When two instruments share the same identifier value, the
    helper returns None to force the caller to disambiguate."""
    aapl = _aapl(fresh_db)
    msft = instruments_repo.instruments_create(
        venue_code="XNAS",
        canonical_symbol="MSFT",
        asset_class="EQUITY",
        instrument_kind="EQUITY",
        currency="USD",
    )
    # Insert the same FIGI for both — pathological but sentinels the
    # helper's ambiguity guard.
    instruments_repo.identifier_add(
        instrument_id=aapl.instrument_id,
        identifier_type=IdentifierKind.FIGI.value,
        identifier_value="DUPE-FIGI",
    )
    instruments_repo.identifier_add(
        instrument_id=msft.instrument_id,
        identifier_type=IdentifierKind.FIGI.value,
        identifier_value="DUPE-FIGI",
    )
    found = instruments_repo.identifier_resolve_one_instrument(
        IdentifierKind.FIGI, "DUPE-FIGI"
    )
    assert found is None


def test_no_match_returns_none(fresh_db):
    _aapl(fresh_db)
    found = instruments_repo.identifier_resolve_one_instrument(
        IdentifierKind.ISIN, "MISSING-ISIN"
    )
    assert found is None


def test_string_identifier_type_accepted(fresh_db):
    """The helper accepts a bare string identifier_type for back-compat."""
    aapl = _aapl(fresh_db)
    instruments_repo.identifier_add(
        instrument_id=aapl.instrument_id,
        identifier_type="ISIN",
        identifier_value="US0378331005",
    )
    found = instruments_repo.identifier_resolve_one_instrument(
        "ISIN", "US0378331005"
    )
    assert found is not None
    assert found.instrument_id == aapl.instrument_id
