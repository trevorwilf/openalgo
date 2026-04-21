"""NYSE (America/New_York) — pre 04:00–09:30, regular 09:30–16:00, post 16:00–20:00 ET."""

from __future__ import annotations

from datetime import datetime, timezone

from zoneinfo import ZoneInfo


def _et(y: int, m: int, d: int, h: int, minute: int) -> datetime:
    return datetime(y, m, d, h, minute, tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)


def test_nyse_pre_market(service) -> None:
    # 2026-04-21 (Tue) 04:30 ET
    assert service.is_open("XNYS", _et(2026, 4, 21, 4, 30)) is True
    types = [s.session_type for s in service.current_sessions("XNYS", _et(2026, 4, 21, 4, 30))]
    assert "PRE_MARKET" in types


def test_nyse_regular(service) -> None:
    assert service.is_open("XNYS", _et(2026, 4, 21, 10, 0)) is True
    types = [s.session_type for s in service.current_sessions("XNYS", _et(2026, 4, 21, 10, 0))]
    assert "REGULAR" in types


def test_nyse_post_market(service) -> None:
    assert service.is_open("XNYS", _et(2026, 4, 21, 17, 0)) is True
    types = [s.session_type for s in service.current_sessions("XNYS", _et(2026, 4, 21, 17, 0))]
    assert "POST_MARKET" in types


def test_nyse_closed_overnight(service) -> None:
    assert service.is_open("XNYS", _et(2026, 4, 21, 22, 0)) is False
    assert service.is_open("XNYS", _et(2026, 4, 21, 3, 30)) is False


def test_nyse_timezone(service) -> None:
    assert str(service.venue_timezone("XNYS")) == "America/New_York"
