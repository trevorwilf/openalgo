"""Resolver in-process TTL cache."""

from __future__ import annotations

import pytest

from database.instruments_repo import instruments_create, venues_upsert
from domain.instrument_ref import InstrumentRef
from services.instrument_resolver import InstrumentResolver


def test_second_call_served_from_cache(fresh_db, monkeypatch) -> None:
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    inst = instruments_create(
        venue_code="NSE",
        canonical_symbol="RELIANCE",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    resolver = InstrumentResolver()

    # Count repo lookups
    from database import instruments_repo

    call_count = 0
    original = instruments_repo.instruments_get_by_venue_symbol

    def counting(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(
        instruments_repo, "instruments_get_by_venue_symbol", counting
    )
    # Also patch the attribute the resolver captured at construction time.
    monkeypatch.setattr(
        resolver._repo, "instruments_get_by_venue_symbol", counting
    )

    ref = InstrumentRef(venue_code="NSE", canonical_symbol="RELIANCE")
    r1 = resolver.resolve(ref)
    r2 = resolver.resolve(ref)
    assert r1.instrument_id == r2.instrument_id == inst.instrument_id
    # Cache hit: exactly one repo call for the two resolves.
    assert call_count == 1


def test_cache_invalidate_drops_all(fresh_db, monkeypatch) -> None:
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    instruments_create(
        venue_code="NSE",
        canonical_symbol="INFY",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    resolver = InstrumentResolver()
    ref = InstrumentRef(venue_code="NSE", canonical_symbol="INFY")
    resolver.resolve(ref)
    assert len(resolver._cache) == 1
    resolver.invalidate()
    assert resolver._cache == {}


def test_cache_ttl_expires(fresh_db, monkeypatch) -> None:
    """With a tiny TTL, the second call re-queries the repo."""
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    instruments_create(
        venue_code="NSE",
        canonical_symbol="TCS",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    resolver = InstrumentResolver(cache_ttl=0.0)  # effectively no cache

    from database import instruments_repo

    call_count = 0
    original = instruments_repo.instruments_get_by_venue_symbol

    def counting(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(
        resolver._repo, "instruments_get_by_venue_symbol", counting
    )
    ref = InstrumentRef(venue_code="NSE", canonical_symbol="TCS")
    resolver.resolve(ref)
    resolver.resolve(ref)
    # TTL=0 forces re-query every call
    assert call_count == 2


def test_cache_key_distinguishes_broker(fresh_db) -> None:
    """Same ref with different broker_code must cache separately."""
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    instruments_create(
        venue_code="NSE",
        canonical_symbol="HDFCBANK",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    resolver = InstrumentResolver()
    ref = InstrumentRef(venue_code="NSE", canonical_symbol="HDFCBANK")
    r1 = resolver.resolve(ref, broker_code="zerodha")
    r2 = resolver.resolve(ref, broker_code="dhan")
    assert len(resolver._cache) == 2  # two cache entries, one per broker
    assert r1.instrument_id == r2.instrument_id  # but same instrument
