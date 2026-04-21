"""LSE (Europe/London) — opening auction 07:50–08:00, regular 08:00–16:30,
closing auction 16:30–16:35."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def _london(y: int, m: int, d: int, h: int, minute: int) -> datetime:
    return datetime(y, m, d, h, minute, tzinfo=ZoneInfo("Europe/London")).astimezone(timezone.utc)


def test_lse_opening_auction(service) -> None:
    # 07:55 London on a Tuesday
    at = _london(2026, 4, 21, 7, 55)
    assert service.is_open("XLON", at) is True
    assert any(
        s.session_type == "OPENING_AUCTION"
        for s in service.current_sessions("XLON", at)
    )


def test_lse_regular(service) -> None:
    at = _london(2026, 4, 21, 9, 0)
    assert service.is_open("XLON", at) is True
    assert any(
        s.session_type == "REGULAR"
        for s in service.current_sessions("XLON", at)
    )


def test_lse_closing_auction(service) -> None:
    at = _london(2026, 4, 21, 16, 31)
    assert service.is_open("XLON", at) is True
    assert any(
        s.session_type == "CLOSING_AUCTION"
        for s in service.current_sessions("XLON", at)
    )


def test_lse_closed_weekend(service) -> None:
    # Saturday
    at = _london(2026, 4, 18, 10, 0)
    assert service.is_open("XLON", at) is False


def test_lse_session_boundaries_for_tuesday(service) -> None:
    from datetime import date

    windows = service.session_boundaries_for_date("XLON", date(2026, 4, 21))
    types = [w.session_type for w in windows]
    assert types == ["OPENING_AUCTION", "REGULAR", "CLOSING_AUCTION"]
