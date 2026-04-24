"""Promoted-lane instrument resolution.

Resolves an :class:`InstrumentRef` (id | venue_symbol | external)
against the normalized instrument tables, enriches with the
broker-native mapping row when one exists, and returns a flat
:class:`ResolvedInstrument` the broker adapter can use directly.

**Promoted-lane contract.** This module MUST NOT call
``database.token_db.get_token`` or touch the legacy ``SymToken``
table. It is the only supported resolution path on the promoted
lane (Phase 4 onward).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from database.instruments_repo import (
    BrokerInstrumentMap,
    Instrument,
    broker_map_lookup_by_symbol,
    broker_map_lookup_by_token,
    instruments_get_by_id,
    instruments_get_by_venue_symbol,
)

if TYPE_CHECKING:  # pragma: no cover
    from domain.instrument_ref import InstrumentRef


@dataclass(frozen=True)
class ResolvedInstrument:
    """A fully-hydrated instrument for the promoted lane.

    Contains the canonical fields from :class:`Instrument` plus the
    broker-native symbol / token when a
    :class:`BrokerInstrumentMap` row is found for the active broker.
    """

    instrument_id: UUID
    venue_code: str
    canonical_symbol: str
    asset_class: str
    instrument_kind: str
    lot_size: Optional[int]
    tick_size: Optional[Decimal]
    quantity_precision: int
    currency: Optional[str]
    broker_native_symbol: Optional[str] = None
    broker_native_token: Optional[str] = None
    supports_fractional: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


def _from_row(
    row: Instrument,
    *,
    broker_map: BrokerInstrumentMap | None,
) -> ResolvedInstrument:
    supports_fractional = False
    if row.quantity_precision and row.quantity_precision > 0:
        supports_fractional = True

    return ResolvedInstrument(
        instrument_id=row.instrument_id,
        venue_code=row.venue_code,
        canonical_symbol=row.canonical_symbol,
        asset_class=row.asset_class,
        instrument_kind=row.instrument_kind,
        lot_size=row.lot_size,
        tick_size=row.tick_size,
        quantity_precision=row.quantity_precision,
        currency=row.currency,
        broker_native_symbol=(
            broker_map.external_symbol if broker_map is not None else None
        ),
        broker_native_token=(
            broker_map.external_token if broker_map is not None else None
        ),
        supports_fractional=supports_fractional,
        metadata=dict(row.metadata_json or {}),
    )


def _enrich_with_broker_map(
    row: Instrument, broker_code: str | None
) -> BrokerInstrumentMap | None:
    if not broker_code:
        return None
    return broker_map_lookup_by_symbol(
        broker_code=broker_code,
        venue_code=row.venue_code,
        external_symbol=row.canonical_symbol,
    )


def resolve_instrument(
    ref: "InstrumentRef", broker_code: str | None
) -> ResolvedInstrument | None:
    """Resolve ``ref`` against the canonical instrument universe.

    Order of precedence:

    1. ``ref.kind == "id"`` — direct lookup by internal UUID.
    2. ``ref.kind == "venue_symbol"`` — lookup the cash row for
       ``(venue_code, canonical_symbol)``.
    3. ``ref.kind == "external"`` — look up via
       :func:`broker_map_lookup_by_symbol` /
       :func:`broker_map_lookup_by_token`, then hydrate the
       canonical row.

    Returns ``None`` when no row is found. Never raises; callers map
    a ``None`` to a 404 themselves.

    Never calls ``database.token_db.get_token``.
    """
    if ref.kind == "id":
        row = instruments_get_by_id(ref.instrument_id)  # type: ignore[arg-type]
        if row is None:
            return None
        return _from_row(row, broker_map=_enrich_with_broker_map(row, broker_code))

    if ref.kind == "venue_symbol":
        row = instruments_get_by_venue_symbol(
            ref.venue_code, ref.canonical_symbol  # type: ignore[arg-type]
        )
        if row is None:
            return None
        return _from_row(row, broker_map=_enrich_with_broker_map(row, broker_code))

    if ref.kind == "external":
        code = ref.broker_code or broker_code
        if not code or not ref.venue_code:
            return None
        brow = broker_map_lookup_by_symbol(
            broker_code=code,
            venue_code=ref.venue_code,
            external_symbol=str(ref.identifier_value),
        )
        if brow is None:
            brow = broker_map_lookup_by_token(
                broker_code=code,
                venue_code=ref.venue_code,
                external_token=str(ref.identifier_value),
            )
        if brow is None:
            return None
        row = instruments_get_by_id(brow.instrument_id)
        if row is None:
            return None
        return _from_row(row, broker_map=brow)

    return None


__all__ = ["ResolvedInstrument", "resolve_instrument"]
