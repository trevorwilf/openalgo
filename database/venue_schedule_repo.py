"""Phase 4 venue schedule layer — ORM models + repository.

Two additive tables, both keyed on ``venues.venue_code`` (Phase 2a):

* ``venue_schedule_templates`` — one row per (venue, day_of_week,
  session_type). ``day_of_week`` uses ISO weekday numbering
  (0 = Monday … 6 = Sunday); -1 means "every day" (crypto).
* ``venue_calendar_exceptions`` — date-specific overrides: CLOSED,
  EARLY_CLOSE, LATE_OPEN, SPECIAL_SESSION.

Times are stored as local ``HH:MM:SS`` strings in the venue's
timezone (looked up on the ``venues`` row). The ``VenueSessionService``
combines these into tz-aware UTC windows.

The legacy `database/market_calendar_db.py` is **not touched**. It
remains the source of truth for the India-only legacy path; this
module is consumed only when ``VENUE_SESSION_V2`` is enabled.
"""

from __future__ import annotations

from datetime import date, time
from typing import Any, Iterable, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
    and_,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from database.instruments_repo import Base, session_scope
from utils.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------


class VenueScheduleTemplate(Base):
    __tablename__ = "venue_schedule_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    venue_code: Mapped[str] = mapped_column(
        String(32), ForeignKey("venues.venue_code"), nullable=False, index=True
    )
    # -1 = every day (crypto). 0..6 = Monday..Sunday.
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    # String value of the domain.Session enum (REGULAR / PRE_MARKET /
    # OPENING_AUCTION / CLOSING_AUCTION / POST_MARKET / ALL_DAY / etc.)
    session_type: Mapped[str] = mapped_column(String(32), nullable=False)
    starts_at_local: Mapped[time] = mapped_column(Time, nullable=False)
    ends_at_local: Mapped[time] = mapped_column(Time, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        "metadata", JSON, nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "venue_code", "day_of_week", "session_type",
            name="uq_venue_schedule_templates_day_session",
        ),
        Index("idx_venue_schedule_templates_day", "venue_code", "day_of_week"),
    )


class VenueCalendarException(Base):
    __tablename__ = "venue_calendar_exceptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    venue_code: Mapped[str] = mapped_column(
        String(32), ForeignKey("venues.venue_code"), nullable=False
    )
    session_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # CLOSED / EARLY_CLOSE / LATE_OPEN / SPECIAL_SESSION
    exception_type: Mapped[str] = mapped_column(String(32), nullable=False)
    starts_at_local: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    ends_at_local: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    session_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        "metadata", JSON, nullable=True
    )

    __table_args__ = (
        Index("idx_venue_calendar_exceptions_date", "venue_code", "session_date"),
    )


# ---------------------------------------------------------------------------
# Repository functions
# ---------------------------------------------------------------------------


def upsert_schedule_template(
    *,
    venue_code: str,
    day_of_week: int,
    session_type: str,
    starts_at_local: time,
    ends_at_local: time,
    is_active: bool = True,
    metadata: Optional[dict[str, Any]] = None,
    session: Session | None = None,
) -> VenueScheduleTemplate:
    """Insert or update a schedule row keyed on (venue, day, session_type)."""
    with session_scope(session) as s:
        existing = s.scalar(
            select(VenueScheduleTemplate).where(
                and_(
                    VenueScheduleTemplate.venue_code == venue_code,
                    VenueScheduleTemplate.day_of_week == day_of_week,
                    VenueScheduleTemplate.session_type == session_type,
                )
            )
        )
        if existing is not None:
            existing.starts_at_local = starts_at_local
            existing.ends_at_local = ends_at_local
            existing.is_active = is_active
            existing.metadata_json = metadata
            s.flush()
            return existing
        row = VenueScheduleTemplate(
            venue_code=venue_code,
            day_of_week=day_of_week,
            session_type=session_type,
            starts_at_local=starts_at_local,
            ends_at_local=ends_at_local,
            is_active=is_active,
            metadata_json=metadata,
        )
        s.add(row)
        s.flush()
        return row


def templates_for_venue(
    venue_code: str,
    *,
    day_of_week: Optional[int] = None,
    session: Session | None = None,
) -> list[VenueScheduleTemplate]:
    """Return active templates for a venue. Optionally narrow to a weekday.

    Rows with ``day_of_week == -1`` (crypto: "every day") always match.
    Ordered by session start time for predictable downstream iteration.
    """
    with session_scope(session) as s:
        stmt = select(VenueScheduleTemplate).where(
            and_(
                VenueScheduleTemplate.venue_code == venue_code,
                VenueScheduleTemplate.is_active.is_(True),
            )
        )
        if day_of_week is not None:
            stmt = stmt.where(
                VenueScheduleTemplate.day_of_week.in_([day_of_week, -1])
            )
        stmt = stmt.order_by(VenueScheduleTemplate.starts_at_local)
        return list(s.scalars(stmt))


def upsert_calendar_exception(
    *,
    venue_code: str,
    session_date: date,
    exception_type: str,
    starts_at_local: Optional[time] = None,
    ends_at_local: Optional[time] = None,
    session_type: Optional[str] = None,
    description: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    session: Session | None = None,
) -> VenueCalendarException:
    """Upsert a calendar exception row.

    Matching key is ``(venue_code, session_date, exception_type,
    session_type)`` — the same venue+date can have multiple exception
    rows when SPECIAL_SESSION adds a window alongside a CLOSED row for
    the primary session.
    """
    with session_scope(session) as s:
        existing = s.scalar(
            select(VenueCalendarException).where(
                and_(
                    VenueCalendarException.venue_code == venue_code,
                    VenueCalendarException.session_date == session_date,
                    VenueCalendarException.exception_type == exception_type,
                    VenueCalendarException.session_type.is_(session_type)
                    if session_type is None
                    else VenueCalendarException.session_type == session_type,
                )
            )
        )
        if existing is not None:
            existing.starts_at_local = starts_at_local
            existing.ends_at_local = ends_at_local
            existing.description = description
            existing.metadata_json = metadata
            s.flush()
            return existing
        row = VenueCalendarException(
            venue_code=venue_code,
            session_date=session_date,
            exception_type=exception_type,
            starts_at_local=starts_at_local,
            ends_at_local=ends_at_local,
            session_type=session_type,
            description=description,
            metadata_json=metadata,
        )
        s.add(row)
        s.flush()
        return row


def exceptions_for_date(
    venue_code: str, session_date: date, *, session: Session | None = None
) -> list[VenueCalendarException]:
    with session_scope(session) as s:
        stmt = select(VenueCalendarException).where(
            and_(
                VenueCalendarException.venue_code == venue_code,
                VenueCalendarException.session_date == session_date,
            )
        )
        return list(s.scalars(stmt))


def init_venue_schedule_tables(engine=None) -> None:
    """Idempotently create the Phase 4 tables. Shares the Base metadata
    with the Phase 2a instrument tables, so Base.metadata.create_all
    ensures every known table exists.
    """
    from database.instruments_repo import get_engine

    Base.metadata.create_all(engine or get_engine())


__all__ = [
    "VenueCalendarException",
    "VenueScheduleTemplate",
    "exceptions_for_date",
    "init_venue_schedule_tables",
    "templates_for_venue",
    "upsert_calendar_exception",
    "upsert_schedule_template",
]
