"""Calendar exceptions: CLOSED / EARLY_CLOSE / LATE_OPEN / SPECIAL_SESSION."""

from __future__ import annotations

from datetime import date, datetime, time, timezone


def test_closed_exception_drops_all_sessions(service) -> None:
    from database.venue_schedule_repo import upsert_calendar_exception

    upsert_calendar_exception(
        venue_code="NSE",
        session_date=date(2026, 4, 21),
        exception_type="CLOSED",
    )
    at = datetime(2026, 4, 21, 4, 0, tzinfo=timezone.utc)  # 09:30 IST
    assert service.is_open("NSE", at) is False

    windows = service.session_boundaries_for_date("NSE", date(2026, 4, 21))
    assert windows == []


def test_early_close_truncates_session(service) -> None:
    from database.venue_schedule_repo import upsert_calendar_exception

    upsert_calendar_exception(
        venue_code="NSE",
        session_date=date(2026, 4, 21),
        exception_type="EARLY_CLOSE",
        session_type="REGULAR",
        ends_at_local=time(12, 0),  # close at 12:00 IST instead of 15:30
    )
    # 11:00 IST = 05:30 UTC → still open
    assert service.is_open("NSE", datetime(2026, 4, 21, 5, 30, tzinfo=timezone.utc)) is True
    # 12:30 IST = 07:00 UTC → closed now
    assert service.is_open("NSE", datetime(2026, 4, 21, 7, 0, tzinfo=timezone.utc)) is False


def test_late_open_delays_session(service) -> None:
    from database.venue_schedule_repo import upsert_calendar_exception

    upsert_calendar_exception(
        venue_code="NSE",
        session_date=date(2026, 4, 21),
        exception_type="LATE_OPEN",
        session_type="REGULAR",
        starts_at_local=time(11, 0),  # open at 11:00 IST instead of 09:15
    )
    # 10:00 IST = 04:30 UTC → closed
    assert service.is_open("NSE", datetime(2026, 4, 21, 4, 30, tzinfo=timezone.utc)) is False
    # 11:30 IST = 06:00 UTC → now open
    assert service.is_open("NSE", datetime(2026, 4, 21, 6, 0, tzinfo=timezone.utc)) is True


def test_special_session_adds_window(service) -> None:
    from database.venue_schedule_repo import upsert_calendar_exception

    # Muhurat Trading — Sunday evening special session.
    upsert_calendar_exception(
        venue_code="NSE",
        session_date=date(2026, 4, 19),  # Sunday
        exception_type="SPECIAL_SESSION",
        session_type="MUHURAT",
        starts_at_local=time(18, 0),
        ends_at_local=time(19, 15),
        description="Diwali Muhurat Trading",
    )
    # Normally closed Sunday — but during muhurat window it should open.
    # 18:30 IST = 13:00 UTC
    at = datetime(2026, 4, 19, 13, 0, tzinfo=timezone.utc)
    assert service.is_open("NSE", at) is True
    windows = service.session_boundaries_for_date("NSE", date(2026, 4, 19))
    assert len(windows) == 1
    assert windows[0].session_type == "MUHURAT"


def test_trading_days_excludes_closed(service) -> None:
    from database.venue_schedule_repo import upsert_calendar_exception

    # Close Tuesday 2026-04-21.
    upsert_calendar_exception(
        venue_code="NSE",
        session_date=date(2026, 4, 21),
        exception_type="CLOSED",
    )
    days = service.trading_days_in_range(
        "NSE", date(2026, 4, 20), date(2026, 4, 24)
    )
    # Mon 20, [Tue 21 closed], Wed 22, Thu 23, Fri 24 → 4 trading days.
    assert days == [
        date(2026, 4, 20),
        date(2026, 4, 22),
        date(2026, 4, 23),
        date(2026, 4, 24),
    ]


def test_previous_close(service) -> None:
    # Tuesday 11:00 IST = 05:30 UTC. Most recent close is Monday 15:30 IST = 10:00 UTC.
    before = datetime(2026, 4, 21, 5, 30, tzinfo=timezone.utc)
    got = service.previous_close("NSE", before)
    assert got == datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc)


def test_naive_datetime_rejected(service) -> None:
    import pytest

    with pytest.raises(ValueError, match="tz-aware"):
        service.is_open("NSE", datetime(2026, 4, 21, 4, 0))


def test_unknown_venue_raises(service) -> None:
    import pytest

    with pytest.raises(ValueError, match="no venue row"):
        service.venue_timezone("NOT_A_VENUE")
