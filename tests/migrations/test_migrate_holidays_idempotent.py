"""Phase 4 — `upgrade/migrate_holidays_to_venue_calendar.py`.

Verifies the migration script:

* copies legacy `market_holidays` rows into
  `venue_calendar_exceptions`,
* skips legacy rows whose venue is not yet seeded in `venues`,
* is idempotent on rerun (counter for inserted_or_updated grows on a
  re-run only by the same number of rows; no duplicate exceptions
  are created).
"""

from __future__ import annotations

from datetime import date as date_type, time as dt_time
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "phase4.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    # Re-init both engines pointed at the temp DB.
    from database import instruments_repo, venue_schedule_repo, market_calendar_db

    instruments_repo._reset_engine_for_tests()
    instruments_repo.init_instrument_tables()
    venue_schedule_repo.init_venue_schedule_tables()

    # The legacy market_calendar_db module captured DATABASE_URL at
    # import time; rebuild its engine to point at our tmp DB.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import scoped_session, sessionmaker
    from sqlalchemy.pool import NullPool

    new_engine = create_engine(
        f"sqlite:///{db_path}",
        poolclass=NullPool,
        connect_args={"check_same_thread": False},
    )
    market_calendar_db.engine = new_engine
    market_calendar_db.db_session = scoped_session(
        sessionmaker(autocommit=False, autoflush=False, bind=new_engine)
    )
    market_calendar_db.Base.query = market_calendar_db.db_session.query_property()
    market_calendar_db.Base.metadata.create_all(new_engine)

    yield tmp_path

    instruments_repo._reset_engine_for_tests()


def _seed_venue(code: str, tz_name: str = "Asia/Kolkata") -> None:
    from database.instruments_repo import venues_upsert

    venues_upsert(
        venue_code=code,
        market_family="IN_STOCK",
        country_code="IN",
        timezone_name=tz_name,
        base_currency="INR",
        settlement_type="T+1",
        session_model="REGULAR_ONLY",
        display_name=code,
    )


def _seed_legacy_holiday(
    *, dt: date_type, exchange: str, description: str = "Test Holiday"
) -> None:
    from database.market_calendar_db import (
        Holiday,
        HolidayExchange,
        db_session,
    )

    h = Holiday(
        holiday_date=dt,
        description=description,
        holiday_type="TRADING_HOLIDAY",
        year=dt.year,
    )
    db_session.add(h)
    db_session.flush()

    db_session.add(
        HolidayExchange(
            holiday_id=h.id,
            exchange_code=exchange,
            is_open=False,
            start_time=None,
            end_time=None,
        )
    )
    db_session.commit()


def test_migration_copies_legacy_holiday(tmp_db) -> None:
    _seed_venue("NSE")
    _seed_legacy_holiday(dt=date_type(2026, 1, 26), exchange="NSE")

    from upgrade.migrate_holidays_to_venue_calendar import migrate

    counters = migrate()
    assert counters["inserted_or_updated"] == 1
    assert counters["skipped_unknown_venue"] == 0

    from database.venue_schedule_repo import exceptions_for_date

    rows = exceptions_for_date("NSE", date_type(2026, 1, 26))
    assert len(rows) == 1
    assert rows[0].exception_type == "CLOSED"
    assert rows[0].metadata_json["source"] == "legacy_market_holidays_migration"


def test_migration_skips_unseeded_venue(tmp_db, caplog) -> None:
    _seed_legacy_holiday(dt=date_type(2026, 1, 26), exchange="UNKNOWN_VENUE")

    from upgrade.migrate_holidays_to_venue_calendar import migrate

    with caplog.at_level("WARNING"):
        counters = migrate()
    assert counters["inserted_or_updated"] == 0
    assert counters["skipped_unknown_venue"] == 1
    assert any("UNKNOWN_VENUE" in rec.message for rec in caplog.records)


def test_migration_idempotent(tmp_db) -> None:
    _seed_venue("NSE")
    _seed_legacy_holiday(dt=date_type(2026, 1, 26), exchange="NSE")

    from upgrade.migrate_holidays_to_venue_calendar import migrate

    migrate()
    migrate()  # second run should not duplicate

    from database.venue_schedule_repo import exceptions_for_date

    rows = exceptions_for_date("NSE", date_type(2026, 1, 26))
    assert len(rows) == 1


def test_migration_special_session_uses_offsets(tmp_db) -> None:
    """A legacy SPECIAL_SESSION row with offsets becomes a
    SPECIAL_SESSION exception with HH:MM start/end times in venue tz."""
    _seed_venue("MCX")

    from database.market_calendar_db import (
        Holiday,
        HolidayExchange,
        db_session,
    )

    h = Holiday(
        holiday_date=date_type(2026, 11, 1),
        description="Muhurat Trading",
        holiday_type="SPECIAL_SESSION",
        year=2026,
    )
    db_session.add(h)
    db_session.flush()
    # 18:00 in offset-from-midnight ms = 18 * 3600 * 1000 = 64800000
    # 19:00 = 68400000
    db_session.add(
        HolidayExchange(
            holiday_id=h.id,
            exchange_code="MCX",
            is_open=True,
            start_time=64800000,
            end_time=68400000,
        )
    )
    db_session.commit()

    from upgrade.migrate_holidays_to_venue_calendar import migrate

    migrate()

    from database.venue_schedule_repo import exceptions_for_date

    rows = exceptions_for_date("MCX", date_type(2026, 11, 1))
    assert len(rows) == 1
    assert rows[0].exception_type == "SPECIAL_SESSION"
    assert rows[0].starts_at_local == dt_time(18, 0)
    assert rows[0].ends_at_local == dt_time(19, 0)
