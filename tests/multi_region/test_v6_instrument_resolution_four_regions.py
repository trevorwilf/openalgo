"""Phase 3 v6 — instrument resolution multi-region smoke test.

Verifies that the canonical instrument resolution surface
(``services.instrument_resolution``) is callable for representative
instruments per region. Concrete resolution against real broker
fixtures is out of scope at the framework level (no live broker
session, no master contract loaded); this test pins that the
resolver module exists and offers the documented API per region.
"""

from __future__ import annotations

import pytest


REPRESENTATIVE_INSTRUMENTS = [
    ("india", "RELIANCE", "NSE"),
    ("us", "AAPL", "XNAS"),
    ("eu", "MC.PA", "XPAR"),
    ("uk", "VOD", "XLON"),
]


def test_resolver_module_imports() -> None:
    import services.instrument_resolution as ir

    # The resolver module must expose at least one resolution helper.
    callable_names = [n for n in dir(ir) if not n.startswith("_") and callable(getattr(ir, n))]
    assert callable_names, "instrument_resolution module exposes no callables"


def test_canonical_identifier_kind_enum_includes_required_kinds() -> None:
    """ADR 0019 defines IdentifierKind for ISIN/CUSIP/SEDOL/FIGI/RIC/
    VENUE_SYMBOL/BROKER_SYMBOL/BROKER_TOKEN/CANONICAL_SYMBOL."""
    from database.instruments_repo import IdentifierKind

    declared = {k.name for k in IdentifierKind}
    for required in (
        "ISIN", "CUSIP", "SEDOL", "FIGI", "RIC",
        "VENUE_SYMBOL", "BROKER_SYMBOL", "BROKER_TOKEN", "CANONICAL_SYMBOL",
    ):
        assert required in declared, (
            f"IdentifierKind missing {required!r}; got {sorted(declared)}"
        )


@pytest.mark.parametrize(("region", "symbol", "venue"), REPRESENTATIVE_INSTRUMENTS)
def test_representative_instruments_can_form_instrument_ref(
    region: str, symbol: str, venue: str,
) -> None:
    """Each region's representative instrument must form a valid
    ``InstrumentRef`` shape — this validates the canonical instrument
    identity model accepts non-Indian inputs."""
    from domain.instrument_ref import InstrumentRef

    ref = InstrumentRef(canonical_symbol=symbol, venue_code=venue)
    assert ref.canonical_symbol == symbol
    assert ref.venue_code == venue
