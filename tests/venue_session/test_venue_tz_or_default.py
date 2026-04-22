"""`venue_tz_or_default` — the post-Phase-9 migration seam used by
iv_chart / straddle_chart / historify_scheduler consumers to switch
from hardcoded "Asia/Kolkata" to a venue-driven timezone behind the
``VENUE_SESSION_V2`` flag.

Byte-identical for Indian venues whether the flag is on or off. Only
non-Indian venues see a different tz when the flag is on.
"""

from __future__ import annotations

import pytest

from services.venue_session_service import venue_tz_or_default


def test_flag_off_returns_default(seeded_db, monkeypatch) -> None:
    monkeypatch.delenv("VENUE_SESSION_V2", raising=False)
    assert venue_tz_or_default("XNYS") == "Asia/Kolkata"
    assert venue_tz_or_default("NSE") == "Asia/Kolkata"
    assert venue_tz_or_default(None) == "Asia/Kolkata"


def test_flag_on_returns_venue_tz(seeded_db, monkeypatch) -> None:
    monkeypatch.setenv("VENUE_SESSION_V2", "1")
    assert venue_tz_or_default("NSE") == "Asia/Kolkata"
    assert venue_tz_or_default("XNYS") == "America/New_York"
    assert venue_tz_or_default("XLON") == "Europe/London"
    assert venue_tz_or_default("CRYPTO") == "UTC"


def test_flag_on_unknown_venue_falls_back(seeded_db, monkeypatch) -> None:
    monkeypatch.setenv("VENUE_SESSION_V2", "1")
    assert venue_tz_or_default("NOT_A_VENUE") == "Asia/Kolkata"


def test_flag_on_none_venue_falls_back(seeded_db, monkeypatch) -> None:
    monkeypatch.setenv("VENUE_SESSION_V2", "1")
    assert venue_tz_or_default(None) == "Asia/Kolkata"


def test_flag_on_custom_default(seeded_db, monkeypatch) -> None:
    monkeypatch.setenv("VENUE_SESSION_V2", "1")
    assert venue_tz_or_default(None, default="UTC") == "UTC"
    # But when venue resolves, the default is overridden.
    assert venue_tz_or_default("XNYS", default="UTC") == "America/New_York"


def test_returns_string_not_zoneinfo(seeded_db, monkeypatch) -> None:
    """Legacy callers wrap the result in pytz.timezone(...) — the
    helper must return a plain string."""
    monkeypatch.setenv("VENUE_SESSION_V2", "1")
    result = venue_tz_or_default("NSE")
    assert isinstance(result, str)


def test_no_raise_on_repo_error(seeded_db, monkeypatch) -> None:
    """If the venues table is unreachable, fall back cleanly."""
    monkeypatch.setenv("VENUE_SESSION_V2", "1")
    from services import venue_session_service

    def boom(*args, **kwargs):
        raise RuntimeError("db gone")

    monkeypatch.setattr(venue_session_service, "venues_get", boom)
    assert venue_tz_or_default("NSE") == "Asia/Kolkata"
