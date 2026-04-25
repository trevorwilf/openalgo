"""Phase 2 — MarketRegion v2 sub-models and convenience accessors."""

from __future__ import annotations

from datetime import date, time

import pytest

from domain.regions import (
    CalendarExceptionSeed,
    MarketRegion,
    SessionTemplateSeed,
    SymbolDisplay,
    VenueSeed,
)


def _make_region(**overrides) -> MarketRegion:
    payload = {
        "region_code": "demo",
        "display_name": "Demo",
        "timezone_name": "UTC",
        "market_families": ["OTHER"],
    }
    payload.update(overrides)
    return MarketRegion(**payload)


def test_v1_region_loads_with_empty_v2_fields() -> None:
    region = _make_region()
    assert region.venues == []
    assert region.session_templates == []
    assert region.calendar_exceptions == []
    assert region.symbol_display == SymbolDisplay()
    assert not region.is_feature_enabled("anything")


def test_get_venue_returns_match() -> None:
    region = _make_region(
        venues=[{"venue_code": "X1"}, {"venue_code": "X2"}],
    )
    assert region.get_venue("X1").venue_code == "X1"
    assert region.get_venue("X2").venue_code == "X2"
    assert region.get_venue("MISSING") is None


def test_session_template_accepts_venue_code_singular() -> None:
    """Loader convention: ``venue_code`` shortcut becomes a single-element
    ``venue_codes`` list."""
    tpl = SessionTemplateSeed(
        session_code="REGULAR",
        venue_code="NSE",
        local_start_time=time(9, 15),
        local_end_time=time(15, 30),
        days_of_week=[0, 1, 2, 3, 4],
    )
    assert tpl.venue_codes == ["NSE"]


def test_get_sessions_for_filters_by_date() -> None:
    region = _make_region(
        session_templates=[
            {
                "session_code": "REGULAR",
                "venue_codes": ["X1"],
                "local_start_time": "09:00",
                "local_end_time": "17:00",
                "days_of_week": [0, 1, 2, 3, 4],
                "effective_from": "2024-01-01",
                "effective_to": "2025-12-31",
            }
        ]
    )
    assert region.get_sessions_for("X1", on_date=date(2025, 6, 1))
    assert not region.get_sessions_for("X1", on_date=date(2026, 6, 1))
    assert not region.get_sessions_for("X1", on_date=date(2023, 1, 1))
    assert not region.get_sessions_for("X2", on_date=date(2025, 6, 1))


def test_calendar_exception_normalizes_type() -> None:
    exc = CalendarExceptionSeed(
        date=date(2026, 1, 1),
        venue_code="X",
        exception_type="closed",
    )
    assert exc.exception_type == "CLOSED"


def test_calendar_exception_rejects_unknown_type() -> None:
    with pytest.raises(Exception):
        CalendarExceptionSeed(
            date=date(2026, 1, 1),
            venue_code="X",
            exception_type="party",
        )


def test_get_calendar_exceptions_filters_by_date_range() -> None:
    region = _make_region(
        calendar_exceptions=[
            {"date": "2026-01-01", "venue_code": "X", "exception_type": "CLOSED"},
            {"date": "2026-06-15", "venue_code": "X", "exception_type": "CLOSED"},
            {"date": "2026-12-25", "venue_code": "X", "exception_type": "CLOSED"},
        ]
    )
    matches = region.get_calendar_exceptions_for(
        "X", from_date=date(2026, 6, 1), to_date=date(2026, 12, 31)
    )
    assert {e.date for e in matches} == {date(2026, 6, 15), date(2026, 12, 25)}


def test_feature_flags_default_false_then_explicit() -> None:
    region = _make_region(feature_flags={"option_chain_enabled": True})
    assert region.is_feature_enabled("option_chain_enabled") is True
    assert region.is_feature_enabled("not_set") is False
    assert region.is_feature_enabled("not_set", default=True) is True


def test_venue_seed_blank_code_rejected() -> None:
    with pytest.raises(Exception):
        VenueSeed(venue_code="")


def test_session_template_dow_validation() -> None:
    with pytest.raises(Exception):
        SessionTemplateSeed(
            session_code="REGULAR",
            venue_codes=["X"],
            local_start_time=time(9, 15),
            local_end_time=time(15, 30),
            days_of_week=[0, 7],  # 7 invalid
        )
