"""Regression: market-calendar special-session / holiday-window
lookups must not write ``None`` into the 1-hour ``_timings_cache``.

Pre-fix: a ``None`` lookup result poisoned ``_timings_cache`` for the
full 3600 s TTL. Adding an emergency special-session row to the DB
during an active trading day was invisible to API consumers for up
to an hour.

Fix: route ``None`` outcomes to a separate ``_timings_negative_cache``
with a 300 s TTL. Positive lookups still get the full 1-hour TTL.
"""

from __future__ import annotations

from datetime import date

import pytest

# Import via the canonical alias module so this test mirrors how the
# rest of the codebase reaches the legacy India calendar.
from database import market_calendar_db as cal


class _FakeHoliday:
    def __init__(self, *, holiday_id: int = 1, description: str = "Muhurat") -> None:
        self.id = holiday_id
        self.description = description


class _FakeExchangeRow:
    def __init__(self, *, start_ms: int, end_ms: int) -> None:
        self.start_time = start_ms
        self.end_time = end_ms


class _Filter:
    """Minimal SQLAlchemy-query stand-in: ignore filter args, return whatever was configured."""

    def __init__(self, value: object) -> None:
        self._value = value

    def filter(self, *_: object, **__: object) -> "_Filter":
        return self

    def first(self) -> object:
        return self._value


def _patch_queries(monkeypatch, *, holiday: object, ex_row: object) -> None:
    monkeypatch.setattr(cal.Holiday, "query", _Filter(holiday))
    monkeypatch.setattr(cal.HolidayExchange, "query", _Filter(ex_row))
    cal._timings_cache.clear()
    cal._timings_negative_cache.clear()


def test_special_session_miss_does_not_poison_long_lived_cache(monkeypatch):
    _patch_queries(monkeypatch, holiday=None, ex_row=None)

    result = cal.get_special_session(date(2026, 5, 5), "NSE")

    assert result is None
    # The long-lived cache MUST stay empty. Only the short-TTL
    # negative cache may carry the negative entry.
    assert len(cal._timings_cache) == 0
    assert len(cal._timings_negative_cache) == 1


def test_holiday_window_miss_does_not_poison_long_lived_cache(monkeypatch):
    _patch_queries(monkeypatch, holiday=None, ex_row=None)

    result = cal.get_holiday_exchange_window(date(2026, 5, 5), "MCX")

    assert result is None
    assert len(cal._timings_cache) == 0
    assert len(cal._timings_negative_cache) == 1


def test_recovery_after_negative_cache_clears(monkeypatch):
    """A miss caches the negative result. When the short-TTL window
    elapses (simulated here by clearing the negative cache), a freshly
    added DB row is visible — pre-fix it was blocked for an hour.
    """
    # First call: no row, gets the "no special session" miss.
    _patch_queries(monkeypatch, holiday=None, ex_row=None)
    assert cal.get_special_session(date(2026, 5, 5), "NSE") is None

    # Operator inserts the special session row mid-day. Simulate the
    # 5-minute negative-cache TTL elapsing by clearing it without
    # touching the long-lived cache.
    cal._timings_negative_cache.clear()
    monkeypatch.setattr(cal.Holiday, "query", _Filter(_FakeHoliday()))
    monkeypatch.setattr(
        cal.HolidayExchange,
        "query",
        _Filter(_FakeExchangeRow(start_ms=12_900_000, end_ms=15_000_000)),
    )

    result = cal.get_special_session(date(2026, 5, 5), "NSE")

    # Pre-fix this returned None because _timings_cache had been
    # poisoned with a None entry for an hour.
    assert result is not None
    assert result["start_ms"] == 12_900_000
    assert result["end_ms"] == 15_000_000
    assert result["description"] == "Muhurat"


def test_positive_result_still_cached_in_long_lived_cache(monkeypatch):
    """Don't regress the happy path: a positive lookup must populate
    the 1-hour cache, not the 5-minute negative cache.
    """
    _patch_queries(
        monkeypatch,
        holiday=_FakeHoliday(),
        ex_row=_FakeExchangeRow(start_ms=12_900_000, end_ms=15_000_000),
    )

    cal.get_special_session(date(2026, 5, 5), "NSE")

    assert len(cal._timings_cache) == 1
    assert len(cal._timings_negative_cache) == 0
