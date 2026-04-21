"""The resolver consults a legacy `token_lookup` callable when the
instruments table lacks the (venue, symbol) row. Returned
`ResolvedInstrument.legacy_fallback` is True and the `instrument_id`
is a stable uuid5-derived synthetic.
"""

from __future__ import annotations

import uuid

import pytest

from domain.instrument_ref import InstrumentRef
from services.instrument_resolver import InstrumentResolver, ResolverMiss


def test_legacy_fallback_returns_synthetic_id(fresh_db) -> None:
    # instruments table is empty (no upsert called). Legacy lookup has it.
    def legacy_get_token(symbol: str, exchange: str):
        return "LEGACY-TOKEN-42" if symbol == "SBIN" and exchange == "NSE" else None

    resolver = InstrumentResolver(legacy_token_lookup=legacy_get_token)
    result = resolver.resolve(
        InstrumentRef(venue_code="NSE", canonical_symbol="SBIN"),
        broker_code="zerodha",
    )
    assert result.legacy_fallback is True
    assert result.external_token == "LEGACY-TOKEN-42"
    assert result.external_symbol == "SBIN"
    assert result.venue_code == "NSE"
    assert result.canonical_symbol == "SBIN"
    # Synthetic UUID is deterministic — must match the spec-defined seed.
    expected = uuid.uuid5(uuid.NAMESPACE_URL, "legacy:zerodha:NSE:SBIN")
    assert result.instrument_id == expected


def test_legacy_fallback_stable_across_calls(fresh_db) -> None:
    calls: list[tuple[str, str]] = []

    def legacy_get_token(symbol: str, exchange: str):
        calls.append((symbol, exchange))
        return "LEGACY-777"

    resolver = InstrumentResolver(legacy_token_lookup=legacy_get_token)
    ref = InstrumentRef(venue_code="NSE", canonical_symbol="TCS")
    r1 = resolver.resolve(ref, broker_code="zerodha")
    r2 = resolver.resolve(ref, broker_code="zerodha")
    assert r1.instrument_id == r2.instrument_id
    # Cache: second call served from cache, legacy lookup called exactly once.
    assert len(calls) == 1


def test_legacy_fallback_requires_broker_code(fresh_db) -> None:
    """Without broker_code, the resolver has no way to construct a
    stable synthetic id OR to attribute the token, so it misses."""
    resolver = InstrumentResolver(legacy_token_lookup=lambda s, e: "x")
    with pytest.raises(ResolverMiss):
        resolver.resolve(InstrumentRef(venue_code="NSE", canonical_symbol="TCS"))


def test_legacy_fallback_returns_none_still_misses(fresh_db) -> None:
    resolver = InstrumentResolver(legacy_token_lookup=lambda s, e: None)
    with pytest.raises(ResolverMiss):
        resolver.resolve(
            InstrumentRef(venue_code="NSE", canonical_symbol="GHOST"),
            broker_code="zerodha",
        )


def test_legacy_fallback_lookup_exception_is_swallowed(fresh_db) -> None:
    """If the legacy lookup itself raises, we log and miss — do not
    leak the underlying exception to the caller."""

    def boom(symbol, exchange):
        raise RuntimeError("db connection lost")

    resolver = InstrumentResolver(legacy_token_lookup=boom)
    with pytest.raises(ResolverMiss):
        resolver.resolve(
            InstrumentRef(venue_code="NSE", canonical_symbol="BREAK"),
            broker_code="zerodha",
        )
