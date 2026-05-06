"""Phase 2a instrument universe — ORM models + repository layer.

This module is the single source of truth for the *new* normalized
instrument tables: `venues`, `instruments`, `instrument_identifiers`,
`broker_instrument_map`, `instrument_sync_runs`.

Important invariants (see `docs/adr/0001-track-a-scope.md` and
`docs/refactor/inventory/02-symtoken-usage.md`):

* `symtoken` is NOT touched by this module. These tables coexist with
  the legacy one; no FK, no join, no schema change to `database/symbol.py`.
* All schema changes are additive. This module never drops columns or
  tables.
* Nothing under `services/`, `blueprints/`, or `broker/` may import from
  here yet — Phase 2a is schema-only. Phase 2b onwards wires consumers
  behind feature flags.

The models use SQLAlchemy 2.0 typed ``Mapped`` declarations so the
repository methods get static type-checking for free. The repository
layer never holds a global session; a module-level ``sessionmaker`` is
used as a factory, and every method either opens a short-lived session
or composes with a session the caller passes via the ``session`` kwarg.
"""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from datetime import datetime
from enum import Enum
from decimal import Decimal
from typing import Any, Iterator, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    and_,
    create_engine,
    func,
    select,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)
from sqlalchemy.pool import NullPool

from utils.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Engine & session plumbing
# ---------------------------------------------------------------------------

_engine = None
_Sessionmaker: Optional[sessionmaker[Session]] = None


def _build_engine():
    """Build the engine lazily from DATABASE_URL.

    SQLite uses NullPool per the project-wide convention (see CLAUDE.md —
    "SQLite Connection Pooling"). Other backends use the standard pool.
    """
    url = os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db")
    if "sqlite" in url:
        return create_engine(
            url, poolclass=NullPool, connect_args={"check_same_thread": False}
        )
    return create_engine(url, pool_size=50, max_overflow=100, pool_timeout=10)


def get_engine():
    """Return the shared engine, building it on first use."""
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def _get_sessionmaker() -> sessionmaker[Session]:
    global _Sessionmaker
    if _Sessionmaker is None:
        _Sessionmaker = sessionmaker(
            bind=get_engine(), autocommit=False, autoflush=False, expire_on_commit=False
        )
    return _Sessionmaker


@contextmanager
def session_scope(session: Session | None = None) -> Iterator[Session]:
    """Yield a Session.

    If `session` is not None, yield it as-is and do not commit or close —
    the caller owns the transaction.

    Otherwise open a fresh session, commit on clean exit, roll back on
    exception, and close at the end.
    """
    if session is not None:
        yield session
        return
    s = _get_sessionmaker()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """Dedicated Base for instrument-universe tables.

    Kept separate from `database.symbol.Base` so `Base.metadata.create_all`
    creates only the Phase 2a tables. `symtoken` is never in this metadata.
    """


class Venue(Base):
    """An execution venue — NSE, BSE, XNAS, XLON, BINANCE, DELTA_EXCHANGE, ..."""

    __tablename__ = "venues"

    venue_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    market_family: Mapped[str] = mapped_column(String(32), nullable=False)
    country_code: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    timezone_name: Mapped[str] = mapped_column(String(64), nullable=False)
    base_currency: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    settlement_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    session_model: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        "metadata", JSON, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Instrument(Base):
    """Canonical instrument row keyed by its internal UUID.

    The `(venue_code, canonical_symbol, expiration_at, option_right, strike)`
    unique constraint is declarative, but SQLite treats NULLs as distinct.
    Repository methods apply an additional in-code dedupe check before
    inserting derivative rows.
    """

    __tablename__ = "instruments"

    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    venue_code: Mapped[str] = mapped_column(
        String(32), ForeignKey("venues.venue_code"), nullable=False
    )
    canonical_symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_class: Mapped[str] = mapped_column(String(32), nullable=False)
    instrument_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    tick_size: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    lot_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    quantity_precision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    min_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    underlying_instrument_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("instruments.instrument_id"), nullable=True
    )
    expiration_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    option_right: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    strike: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        "metadata", JSON, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "venue_code",
            "canonical_symbol",
            "expiration_at",
            "option_right",
            "strike",
            name="uq_instrument_derivative_tuple",
        ),
        Index("idx_instr_venue_symbol", "venue_code", "canonical_symbol"),
        Index(
            "idx_instr_underlying_expiry",
            "underlying_instrument_id",
            "expiration_at",
            "option_right",
            "strike",
        ),
        Index("idx_instr_venue_active", "venue_code", "is_active"),
    )


class InstrumentIdentifier(Base):
    """Many-to-one alternative identifier for an instrument (ISIN, FIGI, ...).

    Uniqueness is NOT enforced globally: VENUE_SYMBOL repeats across
    venues legitimately. The caller decides composite uniqueness.
    """

    __tablename__ = "instrument_identifiers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("instruments.instrument_id"), nullable=False, index=True
    )
    identifier_type: Mapped[str] = mapped_column(String(32), nullable=False)
    identifier_value: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    broker_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    venue_code: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("venues.venue_code"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "idx_ident_resolver",
            "identifier_type",
            "identifier_value",
            "broker_code",
            "venue_code",
        ),
        Index("idx_ident_instrument", "instrument_id", "identifier_type"),
    )


class BrokerInstrumentMap(Base):
    """Fast path from a broker's (venue_code, external_symbol|external_token)
    to our canonical `instrument_id`. Populated by the Phase 2b sync runner.

    Soft-removal semantics: `broker_map_prune_below_version` does NOT
    delete — it updates `last_seen_at` only. Rows below the cutoff can
    be cleaned up by a later operations task after a retention window.
    """

    __tablename__ = "broker_instrument_map"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    broker_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    venue_code: Mapped[str] = mapped_column(
        String(32), ForeignKey("venues.venue_code"), nullable=False, index=True
    )
    external_symbol: Mapped[str] = mapped_column(String(128), nullable=False)
    external_token: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("instruments.instrument_id"), nullable=False, index=True
    )
    sync_version: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "idx_brokermap_symbol", "broker_code", "venue_code", "external_symbol"
        ),
        Index(
            "idx_brokermap_token", "broker_code", "venue_code", "external_token"
        ),
        Index(
            "idx_brokermap_version", "broker_code", "venue_code", "sync_version"
        ),
    )


class InstrumentSyncRun(Base):
    """One row per sync attempt — provenance for the broker map."""

    __tablename__ = "instrument_sync_runs"

    sync_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    broker_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    venue_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    sync_version: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    instrument_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    checksum: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        "metadata", JSON, nullable=True
    )

    __table_args__ = (
        Index(
            "idx_syncrun_version", "broker_code", "venue_code", "sync_version"
        ),
        Index(
            "idx_syncrun_started_desc", "broker_code", "started_at"
        ),
    )


# ---------------------------------------------------------------------------
# Simple data containers
# ---------------------------------------------------------------------------


class BrokerMapRow:
    """Lightweight DTO for bulk broker-map upserts.

    Hand-rolled (not a pydantic model) so callers can pass plain tuples
    without a domain import. The Phase 2b sync runner materializes these.
    """

    __slots__ = ("external_symbol", "external_token", "instrument_id")

    def __init__(
        self,
        external_symbol: str,
        external_token: Optional[str],
        instrument_id: uuid.UUID,
    ) -> None:
        self.external_symbol = external_symbol
        self.external_token = external_token
        self.instrument_id = instrument_id


# ---------------------------------------------------------------------------
# Schema initialization
# ---------------------------------------------------------------------------


def init_instrument_tables(engine=None) -> None:
    """Idempotently create the Phase 2a tables.

    `engine` defaults to the module's shared engine. Callers that want
    to run the migration against an in-memory SQLite pass their own.
    """
    Base.metadata.create_all(engine or get_engine())


# ---------------------------------------------------------------------------
# Repository — venues
# ---------------------------------------------------------------------------


def venues_upsert(
    venue_code: str,
    *,
    market_family: str,
    timezone_name: str,
    country_code: Optional[str] = None,
    base_currency: Optional[str] = None,
    settlement_type: Optional[str] = None,
    session_model: Optional[str] = None,
    display_name: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    session: Session | None = None,
) -> Venue:
    """Insert a venue or update its mutable fields in place."""
    with session_scope(session) as s:
        row = s.get(Venue, venue_code)
        if row is None:
            row = Venue(
                venue_code=venue_code,
                market_family=market_family,
                timezone_name=timezone_name,
                country_code=country_code,
                base_currency=base_currency,
                settlement_type=settlement_type,
                session_model=session_model,
                display_name=display_name,
                metadata_json=metadata,
            )
            s.add(row)
        else:
            row.market_family = market_family
            row.timezone_name = timezone_name
            row.country_code = country_code
            row.base_currency = base_currency
            row.settlement_type = settlement_type
            row.session_model = session_model
            row.display_name = display_name
            row.metadata_json = metadata
        s.flush()
        return row


def venues_get(venue_code: str, *, session: Session | None = None) -> Optional[Venue]:
    with session_scope(session) as s:
        return s.get(Venue, venue_code)


def venues_list(
    market_family: Optional[str] = None, *, session: Session | None = None
) -> list[Venue]:
    with session_scope(session) as s:
        stmt = select(Venue)
        if market_family is not None:
            stmt = stmt.where(Venue.market_family == market_family)
        return list(s.scalars(stmt.order_by(Venue.venue_code)))


# ---------------------------------------------------------------------------
# Repository — instruments
# ---------------------------------------------------------------------------


def instruments_create(
    *,
    venue_code: str,
    canonical_symbol: str,
    asset_class: str,
    instrument_kind: str,
    tick_size: Optional[Decimal] = None,
    lot_size: Optional[int] = None,
    quantity_precision: int = 0,
    min_quantity: Optional[Decimal] = None,
    underlying_instrument_id: Optional[uuid.UUID] = None,
    expiration_at: Optional[datetime] = None,
    option_right: Optional[str] = None,
    strike: Optional[Decimal] = None,
    currency: Optional[str] = None,
    display_name: Optional[str] = None,
    is_active: bool = True,
    metadata: Optional[dict[str, Any]] = None,
    session: Session | None = None,
) -> Instrument:
    """Insert a new instrument, generating a UUID if absent.

    Enforces the derivative-tuple uniqueness in Python because SQLite's
    UniqueConstraint treats NULLs as distinct — meaning two
    `(NSE, RELIANCE, NULL, NULL, NULL)` rows can otherwise coexist.
    """
    with session_scope(session) as s:
        existing = s.scalar(
            select(Instrument).where(
                and_(
                    Instrument.venue_code == venue_code,
                    Instrument.canonical_symbol == canonical_symbol,
                    _nullable_eq(Instrument.expiration_at, expiration_at),
                    _nullable_eq(Instrument.option_right, option_right),
                    _nullable_eq(Instrument.strike, strike),
                )
            )
        )
        if existing is not None:
            raise ValueError(
                f"instrument already exists for "
                f"({venue_code}, {canonical_symbol}, {expiration_at}, "
                f"{option_right}, {strike}) — instrument_id={existing.instrument_id}"
            )
        row = Instrument(
            instrument_id=uuid.uuid4(),
            venue_code=venue_code,
            canonical_symbol=canonical_symbol,
            asset_class=asset_class,
            instrument_kind=instrument_kind,
            tick_size=tick_size,
            lot_size=lot_size,
            quantity_precision=quantity_precision,
            min_quantity=min_quantity,
            underlying_instrument_id=underlying_instrument_id,
            expiration_at=expiration_at,
            option_right=option_right,
            strike=strike,
            currency=currency,
            display_name=display_name,
            is_active=is_active,
            metadata_json=metadata,
        )
        s.add(row)
        s.flush()
        return row


def _nullable_eq(column, value):
    """Build an `IS NULL` or `=` predicate depending on value."""
    if value is None:
        return column.is_(None)
    return column == value


def instruments_get_by_id(
    instrument_id: uuid.UUID, *, session: Session | None = None
) -> Optional[Instrument]:
    with session_scope(session) as s:
        return s.get(Instrument, instrument_id)


def instruments_get_by_venue_symbol(
    venue_code: str, canonical_symbol: str, *, session: Session | None = None
) -> Optional[Instrument]:
    """Return the *cash* instrument for (venue, symbol) — nulls on the
    derivative tuple fields. Derivatives must be looked up via a more
    specific query or `instruments_search`.
    """
    with session_scope(session) as s:
        return s.scalar(
            select(Instrument).where(
                and_(
                    Instrument.venue_code == venue_code,
                    Instrument.canonical_symbol == canonical_symbol,
                    Instrument.expiration_at.is_(None),
                    Instrument.option_right.is_(None),
                    Instrument.strike.is_(None),
                )
            )
        )


def instruments_search(
    *,
    venue_code: Optional[str] = None,
    query: Optional[str] = None,
    asset_class: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    session: Session | None = None,
) -> list[Instrument]:
    """Lightweight search. Phase 3a resolver layer on top.

    When ``query`` is given, results are ranked:
        1. exact case-insensitive match on ``canonical_symbol``
        2. canonical_symbol starts with the query
        3. canonical_symbol contains the query (substring)
    Within each rank, results are alphabetical.

    Without ``query``, results are plain alphabetical.
    """
    from sqlalchemy import case as sa_case, func as sa_func

    with session_scope(session) as s:
        stmt = select(Instrument).where(Instrument.is_active.is_(True))
        if venue_code is not None:
            stmt = stmt.where(Instrument.venue_code == venue_code)
        if asset_class is not None:
            stmt = stmt.where(Instrument.asset_class == asset_class)
        if query:
            safe = query.replace("%", r"\%").replace("_", r"\_")
            q_lower = query.lower()
            stmt = stmt.where(
                Instrument.canonical_symbol.ilike(f"%{safe}%", escape="\\")
            )
            sym_lower = sa_func.lower(Instrument.canonical_symbol)
            rank = sa_case(
                (sym_lower == q_lower, 0),
                (sym_lower.like(f"{q_lower}%"), 1),
                else_=2,
            )
            stmt = stmt.order_by(rank, Instrument.canonical_symbol)
        else:
            stmt = stmt.order_by(Instrument.canonical_symbol)
        stmt = stmt.offset(offset).limit(limit)
        return list(s.scalars(stmt))


def instruments_deactivate(
    instrument_id: uuid.UUID, *, session: Session | None = None
) -> None:
    """Soft-retire an instrument by flipping `is_active`. Never deletes."""
    with session_scope(session) as s:
        row = s.get(Instrument, instrument_id)
        if row is None:
            return
        row.is_active = False


# ---------------------------------------------------------------------------
# Repository — identifiers
# ---------------------------------------------------------------------------


class IdentifierKind(str, Enum):
    """Canonical identifier-type vocabulary (Phase 3 v3 / ADR 0019).

    Helps callers avoid bare-string typos when adding or resolving
    `instrument_identifiers` rows. Strings are kept identical to the
    column values (str-Enum) so old `bytes`/string callers keep
    working.

    Scoping semantics:

    * Global (no broker, no venue): ``ISIN``, ``CUSIP``, ``SEDOL``,
      ``FIGI``, ``RIC``.
    * Venue-scoped: ``VENUE_SYMBOL``.
    * Broker-scoped: ``BROKER_SYMBOL``, ``BROKER_TOKEN``.
    * Cross-region: ``CANONICAL_SYMBOL`` (mirrors the canonical row
      symbol; mostly used by sync diff tooling).
    """

    ISIN = "ISIN"
    CUSIP = "CUSIP"
    SEDOL = "SEDOL"
    FIGI = "FIGI"
    RIC = "RIC"
    VENUE_SYMBOL = "VENUE_SYMBOL"
    BROKER_SYMBOL = "BROKER_SYMBOL"
    BROKER_TOKEN = "BROKER_TOKEN"
    CANONICAL_SYMBOL = "CANONICAL_SYMBOL"


def identifier_add(
    instrument_id: uuid.UUID,
    identifier_type: str,
    identifier_value: str,
    *,
    broker_code: Optional[str] = None,
    venue_code: Optional[str] = None,
    session: Session | None = None,
) -> InstrumentIdentifier:
    with session_scope(session) as s:
        row = InstrumentIdentifier(
            instrument_id=instrument_id,
            identifier_type=identifier_type,
            identifier_value=identifier_value,
            broker_code=broker_code,
            venue_code=venue_code,
        )
        s.add(row)
        s.flush()
        return row


def identifier_resolve(
    identifier_type: str,
    identifier_value: str,
    *,
    broker_code: Optional[str] = None,
    venue_code: Optional[str] = None,
    session: Session | None = None,
) -> list[InstrumentIdentifier]:
    """Return every identifier row matching the given key.

    `broker_code` and `venue_code` are narrowing filters; if a venue-
    agnostic identifier like ISIN was inserted with `venue_code=None`,
    it will match when the caller passes `venue_code=None`.
    """
    with session_scope(session) as s:
        stmt = select(InstrumentIdentifier).where(
            and_(
                InstrumentIdentifier.identifier_type == identifier_type,
                InstrumentIdentifier.identifier_value == identifier_value,
            )
        )
        stmt = stmt.where(_nullable_eq(InstrumentIdentifier.broker_code, broker_code))
        stmt = stmt.where(_nullable_eq(InstrumentIdentifier.venue_code, venue_code))
        return list(s.scalars(stmt))


def identifier_resolve_one_instrument(
    identifier_type: str | IdentifierKind,
    identifier_value: str,
    *,
    broker_code: Optional[str] = None,
    venue_code: Optional[str] = None,
    session: Session | None = None,
) -> Optional[Instrument]:
    """Return the single :class:`Instrument` matching ``identifier_value``,
    or ``None`` when zero or more-than-one rows are found.

    For globally-unique identifiers (``ISIN``, ``CUSIP``, ``SEDOL``,
    ``FIGI``, ``RIC``) callers should pass ``broker_code=None`` and
    ``venue_code=None``. For broker-scoped identifiers
    (``BROKER_TOKEN`` / ``BROKER_SYMBOL``) pass the broker_code.
    For venue-scoped identifiers (``VENUE_SYMBOL``) pass the
    venue_code.

    Phase 3 v3 / ADR 0019 — convenience helper that the v2 quote/bar
    dispatch path can call without hand-rolling a one-of-many check.
    """
    if isinstance(identifier_type, IdentifierKind):
        identifier_type = identifier_type.value
    rows = identifier_resolve(
        identifier_type,
        identifier_value,
        broker_code=broker_code,
        venue_code=venue_code,
        session=session,
    )
    if not rows or len(rows) > 1:
        return None
    return instruments_get_by_id(rows[0].instrument_id, session=session)


# ---------------------------------------------------------------------------
# Repository — broker map
# ---------------------------------------------------------------------------


def broker_map_upsert_many(
    broker_code: str,
    venue_code: str,
    rows: list[BrokerMapRow],
    sync_version: int,
    *,
    session: Session | None = None,
) -> int:
    """Bulk upsert. Matches existing rows on (broker_code, venue_code,
    external_symbol). Returns the number of rows written.
    """
    if not rows:
        return 0

    with session_scope(session) as s:
        existing_rows = s.scalars(
            select(BrokerInstrumentMap).where(
                and_(
                    BrokerInstrumentMap.broker_code == broker_code,
                    BrokerInstrumentMap.venue_code == venue_code,
                    BrokerInstrumentMap.external_symbol.in_(
                        [r.external_symbol for r in rows]
                    ),
                )
            )
        ).all()
        existing_by_symbol: dict[str, BrokerInstrumentMap] = {
            r.external_symbol: r for r in existing_rows
        }
        now = datetime.now()
        count = 0
        for row in rows:
            current = existing_by_symbol.get(row.external_symbol)
            if current is None:
                s.add(
                    BrokerInstrumentMap(
                        broker_code=broker_code,
                        venue_code=venue_code,
                        external_symbol=row.external_symbol,
                        external_token=row.external_token,
                        instrument_id=row.instrument_id,
                        sync_version=sync_version,
                        last_seen_at=now,
                    )
                )
            else:
                current.external_token = row.external_token
                current.instrument_id = row.instrument_id
                current.sync_version = sync_version
                current.last_seen_at = now
            count += 1
        s.flush()
        return count


def broker_map_lookup_by_symbol(
    broker_code: str,
    venue_code: str,
    external_symbol: str,
    *,
    session: Session | None = None,
) -> Optional[BrokerInstrumentMap]:
    with session_scope(session) as s:
        return s.scalar(
            select(BrokerInstrumentMap).where(
                and_(
                    BrokerInstrumentMap.broker_code == broker_code,
                    BrokerInstrumentMap.venue_code == venue_code,
                    BrokerInstrumentMap.external_symbol == external_symbol,
                )
            )
        )


def broker_map_lookup_by_token(
    broker_code: str,
    venue_code: str,
    external_token: str,
    *,
    session: Session | None = None,
) -> Optional[BrokerInstrumentMap]:
    with session_scope(session) as s:
        return s.scalar(
            select(BrokerInstrumentMap).where(
                and_(
                    BrokerInstrumentMap.broker_code == broker_code,
                    BrokerInstrumentMap.venue_code == venue_code,
                    BrokerInstrumentMap.external_token == external_token,
                )
            )
        )


def broker_map_prune_below_version(
    broker_code: str,
    venue_code: str,
    min_sync_version: int,
    *,
    session: Session | None = None,
) -> int:
    """Mark rows below `min_sync_version` as not-recently-seen.

    Soft-removal: updates `last_seen_at` to a very old timestamp (epoch
    zero). Does NOT delete. Consumers that want the freshest view filter
    on `sync_version >= current_run`.

    Returns the count of rows touched.
    """
    with session_scope(session) as s:
        stale_epoch = datetime.fromtimestamp(0)
        rows = s.scalars(
            select(BrokerInstrumentMap).where(
                and_(
                    BrokerInstrumentMap.broker_code == broker_code,
                    BrokerInstrumentMap.venue_code == venue_code,
                    BrokerInstrumentMap.sync_version < min_sync_version,
                )
            )
        ).all()
        for row in rows:
            row.last_seen_at = stale_epoch
        s.flush()
        return len(rows)


# ---------------------------------------------------------------------------
# Repository — sync runs
# ---------------------------------------------------------------------------


def sync_run_start(
    broker_code: str,
    venue_code: Optional[str],
    source: Optional[str] = None,
    *,
    session: Session | None = None,
) -> InstrumentSyncRun:
    """Start a new sync run. Assigns a `sync_version = max + 1` for the
    `(broker_code, venue_code)` pair. Status starts as 'running'.
    """
    with session_scope(session) as s:
        max_version = s.scalar(
            select(func.max(InstrumentSyncRun.sync_version)).where(
                and_(
                    InstrumentSyncRun.broker_code == broker_code,
                    _nullable_eq(InstrumentSyncRun.venue_code, venue_code),
                )
            )
        )
        next_version = (max_version or 0) + 1
        row = InstrumentSyncRun(
            sync_id=uuid.uuid4(),
            broker_code=broker_code,
            venue_code=venue_code,
            sync_version=next_version,
            status="running",
            source=source,
        )
        s.add(row)
        s.flush()
        return row


def sync_run_complete(
    sync_id: uuid.UUID,
    instrument_count: int,
    checksum: Optional[str] = None,
    *,
    session: Session | None = None,
) -> Optional[InstrumentSyncRun]:
    with session_scope(session) as s:
        row = s.get(InstrumentSyncRun, sync_id)
        if row is None:
            return None
        row.status = "success"
        row.completed_at = datetime.now()
        row.instrument_count = instrument_count
        row.checksum = checksum
        return row


def sync_run_fail(
    sync_id: uuid.UUID, error: str, *, session: Session | None = None
) -> Optional[InstrumentSyncRun]:
    with session_scope(session) as s:
        row = s.get(InstrumentSyncRun, sync_id)
        if row is None:
            return None
        row.status = "failed"
        row.completed_at = datetime.now()
        row.error = error
        return row


def sync_run_latest(
    broker_code: str,
    venue_code: Optional[str] = None,
    *,
    session: Session | None = None,
) -> Optional[InstrumentSyncRun]:
    with session_scope(session) as s:
        stmt = select(InstrumentSyncRun).where(
            InstrumentSyncRun.broker_code == broker_code
        )
        if venue_code is not None:
            stmt = stmt.where(InstrumentSyncRun.venue_code == venue_code)
        stmt = stmt.order_by(InstrumentSyncRun.sync_version.desc()).limit(1)
        return s.scalar(stmt)


# ---------------------------------------------------------------------------
# Test/migration helpers
# ---------------------------------------------------------------------------


def _reset_engine_for_tests() -> None:
    """Force the next call to `get_engine()` to rebuild from DATABASE_URL."""
    global _engine, _Sessionmaker
    _engine = None
    _Sessionmaker = None


__all__ = [
    "Base",
    "BrokerInstrumentMap",
    "BrokerMapRow",
    "Instrument",
    "InstrumentIdentifier",
    "InstrumentSyncRun",
    "Venue",
    "broker_map_lookup_by_symbol",
    "broker_map_lookup_by_token",
    "broker_map_prune_below_version",
    "broker_map_upsert_many",
    "get_engine",
    "identifier_add",
    "identifier_resolve",
    "init_instrument_tables",
    "instruments_create",
    "instruments_deactivate",
    "instruments_get_by_id",
    "instruments_get_by_venue_symbol",
    "instruments_search",
    "session_scope",
    "sync_run_complete",
    "sync_run_fail",
    "sync_run_latest",
    "sync_run_start",
    "venues_get",
    "venues_list",
    "venues_upsert",
]
