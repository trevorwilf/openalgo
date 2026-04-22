"""Non-destructive instrument sync pipeline (Phase 2b).

Replaces the destructive pattern in each broker's
`master_contract_db.delete_symtoken_table()` + bulk insert. The legacy
path is NOT removed; this runner writes to the Phase 2a tables
(`venues`, `instruments`, `instrument_identifiers`,
`broker_instrument_map`, `instrument_sync_runs`) in parallel, behind
the ``INSTRUMENT_CORE_V2`` feature flag.

Critical invariants (enforced by Phase 2a's `test_no_destructive_writes`
and the repository layer):

* symtoken is never touched by anything in this module.
* Instrument rows are never deleted — `instruments_deactivate` is the
  only retirement path, and the sync runner does not call it.
* Broker-map rows are never deleted — `broker_map_prune_below_version`
  soft-retires by stamping `last_seen_at` to epoch zero.
* Two brokers syncing back-to-back must leave both their row sets
  visible (see `tests/instrument_sync/test_coexistence.py`).
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime
from typing import Any, Iterable, Optional, Protocol, runtime_checkable

from database import instruments_repo
from database.instruments_repo import (
    BrokerMapRow,
    Instrument,
    InstrumentSyncRun,
    broker_map_prune_below_version,
    broker_map_upsert_many,
    identifier_add,
    instruments_create,
    session_scope,
    sync_run_complete,
    sync_run_fail,
    sync_run_start,
    venues_upsert,
)
from sqlalchemy import select
from sqlalchemy.orm import Session
from utils.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

# `RawInstrumentRow` is an alias for "whatever the adapter reads" — most
# adapters will yield a dict but a `dataclass` or `pydantic` row is also
# fine. The Runner never introspects raw rows, only calls `normalize`.
RawInstrumentRow = dict[str, Any]


@dataclass(frozen=True)
class IdentifierRecord:
    """One alternative identifier (ISIN, FIGI, VENUE_SYMBOL, BROKER_TOKEN, ...)."""

    identifier_type: str
    identifier_value: str
    broker_code: Optional[str] = None
    venue_code: Optional[str] = None


@dataclass
class NormalizedInstrumentRow:
    """The output of `adapter.normalize()` — a fat struct carrying everything
    the runner needs to insert an instrument + its broker-map row +
    identifiers. Values map directly onto `instruments_repo.Instrument` fields.
    """

    venue_code: str
    market_family: str
    venue_timezone: str
    canonical_symbol: str
    asset_class: str
    instrument_kind: str
    # Broker-specific pieces
    external_symbol: str
    external_token: Optional[str] = None
    # Optional instrument fields
    tick_size: Optional[Decimal] = None
    lot_size: Optional[int] = None
    quantity_precision: int = 0
    min_quantity: Optional[Decimal] = None
    underlying_canonical_symbol: Optional[str] = None
    expiration_at: Optional[datetime] = None
    option_right: Optional[str] = None
    strike: Optional[Decimal] = None
    currency: Optional[str] = None
    display_name: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    # Identifiers the adapter wants persisted alongside the instrument.
    identifiers: list[IdentifierRecord] = field(default_factory=list)


@dataclass
class SyncRunResult:
    """Summary returned by `InstrumentSyncRunner.run`."""

    sync_id: uuid.UUID
    sync_version: int
    broker_code: str
    instrument_count: int
    new_count: int
    updated_count: int
    retired_count: int
    duration_ms: int
    status: str
    checksum: Optional[str] = None


@runtime_checkable
class InstrumentSyncAdapter(Protocol):
    """Adapter contract. Sync adapters live under
    ``services/instrument_sync_adapters/`` and are registered in the
    ``ADAPTERS`` dict there. Everything here is duck-typed; adapters
    may inherit from object.
    """

    broker_code: str

    def fetch_raw(self) -> Iterable[RawInstrumentRow]:
        """Yield raw broker-native rows. Must be restartable (called
        at most once per sync run)."""
        ...

    def normalize(self, raw: RawInstrumentRow) -> Optional[NormalizedInstrumentRow]:
        """Translate a raw row into the normalized shape. Return None to
        skip rows the adapter considers noise (expired contracts, etc.)."""
        ...

    def resolve_venue(self, normalized: NormalizedInstrumentRow) -> str:
        """Return the venue_code to use. Usually identity — but an adapter
        can defer computation here."""
        ...

    def resolve_identifiers(
        self, normalized: NormalizedInstrumentRow
    ) -> list[IdentifierRecord]:
        """Return the identifier records to persist. Usually identity on
        `normalized.identifiers`."""
        ...


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_CHUNK_SIZE = 500


class InstrumentSyncRunner:
    """Non-destructive sync runner. One instance per sync execution.

    Design notes:

    * Each chunk opens a single repo session via `session_scope` and
      uses it for every row in the chunk. This batches inserts into a
      single transaction, keeps FDs bounded under the SQLite NullPool
      convention (see CLAUDE.md), and lets the runner roll back a
      partial chunk on error without losing earlier chunks' progress.
    * An in-memory map ``(venue_code, canonical_symbol, expiration, right,
      strike) -> instrument_id`` is kept for the duration of a run so
      the runner can upsert identifiers and broker-map rows without a
      second query per row.
    * On exception, the sync_run is marked ``failed``, the exception is
      re-raised, and any broker-map rows inserted in completed chunks
      remain (they carry this run's sync_version and will be soft-pruned
      by the NEXT successful run).
    """

    def __init__(
        self,
        repo: Any = instruments_repo,
        clock: Any = time,
        logger_: Any = None,
    ) -> None:
        # `repo` and `clock` are injection points for tests that want to
        # assert specific sequences; in production both are the real
        # module and real ``time``.
        self._repo = repo
        self._clock = clock
        self._log = logger_ or logger

    def run(self, adapter: InstrumentSyncAdapter) -> SyncRunResult:
        start = self._clock.monotonic()
        sync_row: InstrumentSyncRun = sync_run_start(
            broker_code=adapter.broker_code,
            venue_code=None,  # a broker may span multiple venues
            source=type(adapter).__name__,
        )
        self._log.info(
            "instrument sync start broker=%s sync_id=%s sync_version=%d",
            adapter.broker_code,
            sync_row.sync_id,
            sync_row.sync_version,
        )

        instrument_count = 0
        new_count = 0
        updated_count = 0
        seen_venues: set[str] = set()
        seen_market_families: set[str] = set()
        external_symbols_seen: list[str] = []

        # Buffer broker-map rows per venue so we can upsert in chunks.
        buffered_by_venue: dict[str, list[BrokerMapRow]] = {}

        try:
            chunk: list[NormalizedInstrumentRow] = []
            for raw in adapter.fetch_raw():
                normalized = adapter.normalize(raw)
                if normalized is None:
                    continue
                chunk.append(normalized)
                if normalized.market_family:
                    seen_market_families.add(normalized.market_family)
                if len(chunk) >= _CHUNK_SIZE:
                    new, updated = self._process_chunk(
                        adapter, chunk, sync_row.sync_version,
                        seen_venues, buffered_by_venue, external_symbols_seen,
                    )
                    instrument_count += len(chunk)
                    new_count += new
                    updated_count += updated
                    chunk = []

            if chunk:
                new, updated = self._process_chunk(
                    adapter, chunk, sync_row.sync_version,
                    seen_venues, buffered_by_venue, external_symbols_seen,
                )
                instrument_count += len(chunk)
                new_count += new
                updated_count += updated

            # Flush any leftover broker-map rows per venue.
            for venue_code, rows in buffered_by_venue.items():
                broker_map_upsert_many(
                    adapter.broker_code, venue_code, rows, sync_row.sync_version
                )

            # Soft-retire any broker-map rows the previous sync had but
            # this sync did not re-see. Per-venue: only prune venues we
            # touched, so a broker with two venues getting a partial sync
            # does not collateral-damage the untouched venue.
            retired = 0
            for venue_code in seen_venues:
                retired += broker_map_prune_below_version(
                    adapter.broker_code, venue_code, sync_row.sync_version
                )

            # Deterministic checksum of the sorted external-symbol list.
            checksum = hashlib.md5(
                "|".join(sorted(external_symbols_seen)).encode("utf-8")
            ).hexdigest()

            sync_run_complete(sync_row.sync_id, instrument_count, checksum=checksum)
            duration_ms = int((self._clock.monotonic() - start) * 1000)

            self._log.info(
                "instrument sync success broker=%s market_family=%s "
                "sync_id=%s sync_version=%d instrument_count=%d new=%d "
                "updated=%d retired=%d duration_ms=%d status=success",
                adapter.broker_code,
                ",".join(sorted(seen_market_families)) or "unknown",
                sync_row.sync_id,
                sync_row.sync_version,
                instrument_count,
                new_count,
                updated_count,
                retired,
                duration_ms,
            )
            return SyncRunResult(
                sync_id=sync_row.sync_id,
                sync_version=sync_row.sync_version,
                broker_code=adapter.broker_code,
                instrument_count=instrument_count,
                new_count=new_count,
                updated_count=updated_count,
                retired_count=retired,
                duration_ms=duration_ms,
                status="success",
                checksum=checksum,
            )
        except Exception as exc:
            duration_ms = int((self._clock.monotonic() - start) * 1000)
            sync_run_fail(sync_row.sync_id, error=str(exc))
            self._log.exception(
                "instrument sync FAIL broker=%s market_family=%s "
                "sync_id=%s sync_version=%d duration_ms=%d status=failed",
                adapter.broker_code,
                ",".join(sorted(seen_market_families)) or "unknown",
                sync_row.sync_id,
                sync_row.sync_version,
                duration_ms,
            )
            raise

    # ---- chunk processing ------------------------------------------------

    def _process_chunk(
        self,
        adapter: InstrumentSyncAdapter,
        rows: list[NormalizedInstrumentRow],
        sync_version: int,
        seen_venues: set[str],
        buffered_by_venue: dict[str, list[BrokerMapRow]],
        external_symbols_seen: list[str],
    ) -> tuple[int, int]:
        """Process one chunk inside a single session. Returns (new, updated) counts."""
        new_count = 0
        updated_count = 0
        with session_scope() as s:
            for norm in rows:
                venue_code = adapter.resolve_venue(norm)
                seen_venues.add(venue_code)

                # Ensure venue upsert
                venues_upsert(
                    venue_code,
                    market_family=norm.market_family,
                    timezone_name=norm.venue_timezone,
                    base_currency=None,  # Phase 4 fills venue metadata
                    session=s,
                )

                instrument, was_new = self._upsert_instrument(s, norm, venue_code)
                if was_new:
                    new_count += 1
                else:
                    updated_count += 1

                # Identifiers — adapter may have prebuilt them; call the hook
                # so an adapter that splits the concern still works.
                idents = adapter.resolve_identifiers(norm)
                self._upsert_identifiers(s, instrument.instrument_id, idents)

                buffered_by_venue.setdefault(venue_code, []).append(
                    BrokerMapRow(
                        external_symbol=norm.external_symbol,
                        external_token=norm.external_token,
                        instrument_id=instrument.instrument_id,
                    )
                )
                external_symbols_seen.append(norm.external_symbol)
        return new_count, updated_count

    def _upsert_instrument(
        self, s: Session, norm: NormalizedInstrumentRow, venue_code: str
    ) -> tuple[Instrument, bool]:
        """Return (Instrument, was_new). Inserts when absent, updates fields
        in place when present."""
        stmt = select(Instrument).where(
            Instrument.venue_code == venue_code,
            Instrument.canonical_symbol == norm.canonical_symbol,
            _eq(Instrument.expiration_at, norm.expiration_at),
            _eq(Instrument.option_right, norm.option_right),
            _eq(Instrument.strike, norm.strike),
        )
        existing = s.scalar(stmt)
        if existing is not None:
            # Light-touch update. Don't clobber created_at.
            existing.asset_class = norm.asset_class
            existing.instrument_kind = norm.instrument_kind
            existing.tick_size = norm.tick_size
            existing.lot_size = norm.lot_size
            existing.quantity_precision = norm.quantity_precision
            existing.min_quantity = norm.min_quantity
            existing.currency = norm.currency
            existing.display_name = norm.display_name
            existing.is_active = True
            if norm.metadata is not None:
                existing.metadata_json = norm.metadata
            s.flush()
            return existing, False
        row = instruments_create(
            venue_code=venue_code,
            canonical_symbol=norm.canonical_symbol,
            asset_class=norm.asset_class,
            instrument_kind=norm.instrument_kind,
            tick_size=norm.tick_size,
            lot_size=norm.lot_size,
            quantity_precision=norm.quantity_precision,
            min_quantity=norm.min_quantity,
            expiration_at=norm.expiration_at,
            option_right=norm.option_right,
            strike=norm.strike,
            currency=norm.currency,
            display_name=norm.display_name,
            metadata=norm.metadata,
            session=s,
        )
        return row, True

    def _upsert_identifiers(
        self,
        s: Session,
        instrument_id: uuid.UUID,
        identifiers: list[IdentifierRecord],
    ) -> None:
        """Insert identifier rows that do not already exist.

        We don't want to reinsert (instrument_id, identifier_type,
        identifier_value, broker_code, venue_code) tuples on every
        sync, so filter first.
        """
        from database.instruments_repo import InstrumentIdentifier

        if not identifiers:
            return
        existing_rows = s.scalars(
            select(InstrumentIdentifier).where(
                InstrumentIdentifier.instrument_id == instrument_id
            )
        ).all()
        existing_keys = {
            (r.identifier_type, r.identifier_value, r.broker_code, r.venue_code)
            for r in existing_rows
        }
        for ident in identifiers:
            key = (
                ident.identifier_type,
                ident.identifier_value,
                ident.broker_code,
                ident.venue_code,
            )
            if key in existing_keys:
                continue
            identifier_add(
                instrument_id,
                ident.identifier_type,
                ident.identifier_value,
                broker_code=ident.broker_code,
                venue_code=ident.venue_code,
                session=s,
            )


def _eq(column: Any, value: Any) -> Any:
    """Null-aware equality predicate."""
    if value is None:
        return column.is_(None)
    return column == value


__all__ = [
    "IdentifierRecord",
    "InstrumentSyncAdapter",
    "InstrumentSyncRunner",
    "NormalizedInstrumentRow",
    "RawInstrumentRow",
    "SyncRunResult",
]
