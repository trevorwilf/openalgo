"""NSE (Asia/Kolkata) — regular session Mon–Fri 09:15–15:30 IST."""

from __future__ import annotations

from datetime import datetime, timezone


def test_nse_open_during_session(service) -> None:
    # 2026-04-21 (Tue) 09:30 IST = 04:00 UTC
    at = datetime(2026, 4, 21, 4, 0, tzinfo=timezone.utc)
    assert service.is_open("NSE", at) is True


def test_nse_open_at_exact_start(service) -> None:
    # 09:15:00 IST = 03:45:00 UTC
    at = datetime(2026, 4, 21, 3, 45, tzinfo=timezone.utc)
    assert service.is_open("NSE", at) is True


def test_nse_closed_at_exact_end(service) -> None:
    # 15:30:00 IST = 10:00:00 UTC — end is exclusive.
    at = datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc)
    assert service.is_open("NSE", at) is False


def test_nse_closed_before_open(service) -> None:
    # 09:14 IST = 03:44 UTC
    at = datetime(2026, 4, 21, 3, 44, tzinfo=timezone.utc)
    assert service.is_open("NSE", at) is False


def test_nse_closed_on_saturday(service) -> None:
    # 2026-04-18 is a Saturday (no schedule).
    at = datetime(2026, 4, 18, 5, 0, tzinfo=timezone.utc)
    assert service.is_open("NSE", at) is False


def test_nse_next_session_returns_monday_when_called_on_saturday(service) -> None:
    at = datetime(2026, 4, 18, 5, 0, tzinfo=timezone.utc)  # Saturday
    window = service.next_session("NSE", at)
    assert window is not None
    assert window.venue_code == "NSE"
    assert window.session_type == "REGULAR"
    # Next session starts Monday 09:15 IST = 2026-04-20 03:45 UTC
    assert window.start_utc == datetime(2026, 4, 20, 3, 45, tzinfo=timezone.utc)


def test_nse_timezone_is_kolkata(service) -> None:
    assert str(service.venue_timezone("NSE")) == "Asia/Kolkata"
