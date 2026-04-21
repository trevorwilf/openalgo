"""Resolver miss semantics in the WebSocket path.

If the instruments table is empty for the ref and the legacy token
lookup can still answer, Phase 3a's resolver returns a legacy-fallback
ResolvedInstrument with a synthetic uuid5. The subscription proceeds,
legacy `subscribe` is called, and outbound payloads get the synthetic
ID (consistent with Phase 3a's published behavior).

If neither path can resolve, the resolver raises `ResolverMiss`; the
base adapter surfaces that to the caller (unlike
quotes/history_service which explicitly swallow, the ws path bubbles
because there's nothing else for subscribe_by_instrument_ref to fall
back to — the caller can always invoke the legacy subscribe directly).
"""

from __future__ import annotations

import pytest

from domain.instrument_ref import InstrumentRef
from services.instrument_resolver import ResolverMiss


def test_legacy_fallback_still_subscribes(
    adapter, instruments_db, reset_default_resolver
):
    """instruments table is empty for SBIN. A mocked legacy token lookup
    answers. subscribe_by_instrument_ref delegates to subscribe anyway."""
    from services import instrument_resolver

    # Construct a resolver with a stub legacy lookup instead of using the
    # module default.
    resolver = instrument_resolver.InstrumentResolver(
        legacy_token_lookup=lambda sym, ex: "LEGACY-TOKEN-42"
        if sym == "SBIN" and ex == "NSE"
        else None
    )
    import websocket_proxy.broker_factory as bf
    from unittest import mock

    with mock.patch.object(bf, "get_instrument_resolver", return_value=resolver):
        adapter.subscribe_by_instrument_ref(
            InstrumentRef(venue_code="NSE", canonical_symbol="SBIN")
        )

    assert adapter.subscribe_calls == [("SBIN", "NSE", 2, 5)]
    # Synthetic UUID tracked in state.
    iid = adapter._subscribed_instrument_ids[("NSE", "SBIN")]
    import uuid as _u
    assert iid == _u.uuid5(_u.NAMESPACE_URL, "legacy:zerodha:NSE:SBIN")


def test_full_miss_raises(adapter, instruments_db, reset_default_resolver):
    """No instrument and no legacy fallback possible. ResolverMiss
    propagates to the caller."""
    from services import instrument_resolver

    resolver = instrument_resolver.InstrumentResolver(
        legacy_token_lookup=lambda s, e: None
    )
    import websocket_proxy.broker_factory as bf
    from unittest import mock

    with mock.patch.object(bf, "get_instrument_resolver", return_value=resolver):
        with pytest.raises(ResolverMiss):
            adapter.subscribe_by_instrument_ref(
                InstrumentRef(venue_code="NSE", canonical_symbol="GHOST")
            )

    # Nothing was subscribed and no state map entry was added.
    assert adapter.subscribe_calls == []
    assert ("NSE", "GHOST") not in adapter._subscribed_instrument_ids
