"""Broker rule matrix + session overrides — declarative per-broker
constraints for promoted-lane order validation.

Additive migration following the pattern in
:mod:`database.settings_db` (Phase 1 of this refactor): tables are
created only if absent, and this module is safe to re-run. The engine
and session factory follow the same pattern as
:mod:`database.instruments_repo` so the shared DATABASE_URL applies.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, time
from typing import Any, Iterator, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
    create_engine,
    func,
    inspect,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import NullPool

from utils.logging import get_logger

logger = get_logger(__name__)


class Base(DeclarativeBase):
    """Separate metadata so create_all only creates these tables."""


class BrokerOrderRulesRow(Base):
    """A single per-broker rule. Most-specific match wins.

    Specificity is ordered: a row where venue_code, asset_class,
    session, side and quantity_unit are all set is strictly more
    specific than a row where any of those are NULL (wildcard).
    """

    __tablename__ = "broker_order_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    broker_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    venue_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    asset_class: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    session: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    side: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    quantity_unit: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    allowed_order_types: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    allowed_time_in_force: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    requires_limit_price: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    allows_fractional: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    allows_notional: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    allows_short: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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
        Index("idx_rules_broker", "broker_code"),
        Index("idx_rules_broker_venue", "broker_code", "venue_code"),
    )


class BrokerVenueSessionOverrideRow(Base):
    """Per-broker override of a venue's session window.

    A row with ``is_enabled=False`` closes the session for this broker
    (e.g. broker-specific holiday that the canonical venue schedule
    doesn't reflect). A row with ``is_enabled=True`` and explicit
    ``open_time`` / ``close_time`` narrows the window.

    ``effective_date`` ``None`` means the override is always in effect
    (e.g. a broker that simply doesn't support a session at all).
    """

    __tablename__ = "broker_venue_session_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    broker_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    venue_code: Mapped[str] = mapped_column(String(32), nullable=False)
    session: Mapped[str] = mapped_column(String(32), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    open_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    close_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    effective_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        "metadata", JSON, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "idx_bvso_lookup",
            "broker_code",
            "venue_code",
            "session",
            "effective_date",
        ),
    )


# ---------------------------------------------------------------------------
# Engine / session factory
# ---------------------------------------------------------------------------


_engine = None
_Sessionmaker: sessionmaker | None = None


def _database_url() -> str:
    import os

    return os.environ.get("DATABASE_URL", "sqlite:///db/openalgo.db")


def _get_engine():
    global _engine
    if _engine is None:
        url = _database_url()
        kwargs: dict[str, Any] = {"future": True}
        if url.startswith("sqlite"):
            kwargs["poolclass"] = NullPool
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(url, **kwargs)
    return _engine


def _get_sessionmaker() -> sessionmaker:
    global _Sessionmaker
    if _Sessionmaker is None:
        _Sessionmaker = sessionmaker(
            bind=_get_engine(), expire_on_commit=False, future=True
        )
    return _Sessionmaker


def _reset_engine_for_tests() -> None:
    """Dispose the cached engine and reset the sessionmaker. Test-only."""
    global _engine, _Sessionmaker
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _Sessionmaker = None


@contextmanager
def session_scope(session: Session | None = None) -> Iterator[Session]:
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


def init_broker_rules_tables() -> None:
    """Create the tables if they don't exist — idempotent, additive."""
    engine = _get_engine()
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    if "broker_order_rules" in existing and "broker_venue_session_overrides" in existing:
        return
    Base.metadata.create_all(engine)


# ---------------------------------------------------------------------------
# Repository helpers
# ---------------------------------------------------------------------------


def rules_upsert(
    *,
    broker_code: str,
    allowed_order_types: list[str],
    allowed_time_in_force: list[str],
    venue_code: Optional[str] = None,
    asset_class: Optional[str] = None,
    session_name: Optional[str] = None,
    side: Optional[str] = None,
    quantity_unit: Optional[str] = None,
    requires_limit_price: bool = False,
    allows_fractional: bool = False,
    allows_notional: bool = False,
    allows_short: bool = False,
    metadata: Optional[dict[str, Any]] = None,
    session: Session | None = None,
) -> BrokerOrderRulesRow:
    """Insert or update a rule keyed by all the qualifier columns.

    Two rows are considered the *same* rule if every qualifier
    (broker_code, venue_code, asset_class, session, side,
    quantity_unit) matches exactly. This keeps seed scripts idempotent
    without adding a UNIQUE constraint that would need to handle NULLs
    across dialects.
    """
    with session_scope(session) as s:
        stmt = select(BrokerOrderRulesRow).where(
            BrokerOrderRulesRow.broker_code == broker_code,
            _nullable_eq(BrokerOrderRulesRow.venue_code, venue_code),
            _nullable_eq(BrokerOrderRulesRow.asset_class, asset_class),
            _nullable_eq(BrokerOrderRulesRow.session, session_name),
            _nullable_eq(BrokerOrderRulesRow.side, side),
            _nullable_eq(BrokerOrderRulesRow.quantity_unit, quantity_unit),
        )
        existing = s.scalar(stmt)
        if existing is None:
            existing = BrokerOrderRulesRow(
                broker_code=broker_code,
                venue_code=venue_code,
                asset_class=asset_class,
                session=session_name,
                side=side,
                quantity_unit=quantity_unit,
                allowed_order_types=list(allowed_order_types),
                allowed_time_in_force=list(allowed_time_in_force),
                requires_limit_price=requires_limit_price,
                allows_fractional=allows_fractional,
                allows_notional=allows_notional,
                allows_short=allows_short,
                metadata_json=metadata,
            )
            s.add(existing)
        else:
            existing.allowed_order_types = list(allowed_order_types)
            existing.allowed_time_in_force = list(allowed_time_in_force)
            existing.requires_limit_price = requires_limit_price
            existing.allows_fractional = allows_fractional
            existing.allows_notional = allows_notional
            existing.allows_short = allows_short
            existing.metadata_json = metadata
        s.flush()
        return existing


def rules_list_for(
    broker_code: str, session: Session | None = None
) -> list[BrokerOrderRulesRow]:
    with session_scope(session) as s:
        return list(
            s.scalars(
                select(BrokerOrderRulesRow).where(
                    BrokerOrderRulesRow.broker_code == broker_code
                )
            )
        )


def session_override_upsert(
    *,
    broker_code: str,
    venue_code: str,
    session_name: str,
    is_enabled: bool,
    open_time: Optional[time] = None,
    close_time: Optional[time] = None,
    effective_date: Optional[date] = None,
    reason: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    session: Session | None = None,
) -> BrokerVenueSessionOverrideRow:
    with session_scope(session) as s:
        stmt = select(BrokerVenueSessionOverrideRow).where(
            BrokerVenueSessionOverrideRow.broker_code == broker_code,
            BrokerVenueSessionOverrideRow.venue_code == venue_code,
            BrokerVenueSessionOverrideRow.session == session_name,
            _nullable_eq(
                BrokerVenueSessionOverrideRow.effective_date, effective_date
            ),
        )
        existing = s.scalar(stmt)
        if existing is None:
            existing = BrokerVenueSessionOverrideRow(
                broker_code=broker_code,
                venue_code=venue_code,
                session=session_name,
                is_enabled=is_enabled,
                open_time=open_time,
                close_time=close_time,
                effective_date=effective_date,
                reason=reason,
                metadata_json=metadata,
            )
            s.add(existing)
        else:
            existing.is_enabled = is_enabled
            existing.open_time = open_time
            existing.close_time = close_time
            existing.reason = reason
            existing.metadata_json = metadata
        s.flush()
        return existing


def session_overrides_for(
    broker_code: str,
    venue_code: str,
    session_name: str,
    *,
    on_date: Optional[date] = None,
    session: Session | None = None,
) -> list[BrokerVenueSessionOverrideRow]:
    """Return overrides applicable to ``(broker, venue, session)`` on
    ``on_date``.

    Includes rows whose ``effective_date`` is NULL (always) plus rows
    whose ``effective_date`` equals ``on_date`` when provided.
    """
    with session_scope(session) as s:
        stmt = select(BrokerVenueSessionOverrideRow).where(
            BrokerVenueSessionOverrideRow.broker_code == broker_code,
            BrokerVenueSessionOverrideRow.venue_code == venue_code,
            BrokerVenueSessionOverrideRow.session == session_name,
        )
        rows = list(s.scalars(stmt))
    if on_date is None:
        return [r for r in rows if r.effective_date is None]
    return [r for r in rows if r.effective_date is None or r.effective_date == on_date]


def _nullable_eq(column, value):
    """``column == value`` that also works when ``value`` is None.

    SQLAlchemy's ``==`` does not generate ``IS NULL`` for Python None —
    you get a literal ``= NULL`` which matches nothing. This helper
    picks the right operator.
    """
    if value is None:
        return column.is_(None)
    return column == value


__all__ = [
    "BrokerOrderRulesRow",
    "BrokerVenueSessionOverrideRow",
    "init_broker_rules_tables",
    "rules_list_for",
    "rules_upsert",
    "session_override_upsert",
    "session_overrides_for",
    "_reset_engine_for_tests",
    "session_scope",
]
