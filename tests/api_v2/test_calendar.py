"""GET /api/v2/calendar/holidays + /api/v2/calendar/timings."""
from __future__ import annotations


def test_holidays_xnas_2026(flask_app):
    resp = flask_app.test_client().get(
        "/api/v2/calendar/holidays",
        query_string={"venue_code": "XNAS", "year": "2026"},
    )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()["data"]
    assert body["venue_code"] == "XNAS"
    assert body["year"] == 2026
    assert body["timezone"] == "America/New_York"
    # NYSE / NASDAQ holidays in 2026 should include New Year's Day (Jan 1 = Thu)
    # and Christmas (Dec 25 = Fri) — both fall on weekdays in 2026.
    assert "2026-01-01" in body["holidays"]
    assert "2026-12-25" in body["holidays"]
    # ~10 federal market holidays per year for US equities.
    assert 8 <= len(body["holidays"]) <= 12


def test_holidays_unknown_venue_returns_404(flask_app):
    resp = flask_app.test_client().get(
        "/api/v2/calendar/holidays",
        query_string={"venue_code": "ZZZNOTREAL", "year": "2026"},
    )
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "venue_not_supported"


def test_holidays_missing_venue_returns_400(flask_app):
    resp = flask_app.test_client().get("/api/v2/calendar/holidays",
                                         query_string={"year": "2026"})
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "bad_request"


def test_holidays_year_out_of_range_returns_400(flask_app):
    resp = flask_app.test_client().get(
        "/api/v2/calendar/holidays",
        query_string={"venue_code": "XNAS", "year": "1999"},
    )
    assert resp.status_code == 400


def test_timings_xnas_open_day(flask_app):
    """May 6 2026 is a Wednesday — markets open."""
    resp = flask_app.test_client().get(
        "/api/v2/calendar/timings",
        query_string={"venue_code": "XNAS", "date": "2026-05-06"},
    )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()["data"]
    assert body["venue_code"] == "XNAS"
    assert body["is_open"] is True
    assert body["timezone"] == "America/New_York"
    assert "session_open" in body and "session_close" in body
    # NYSE/NASDAQ opens 09:30 ET → 13:30 UTC during DST (EDT is UTC-4).
    assert "13:30" in body["session_open"] or "14:30" in body["session_open"]


def test_timings_xnas_holiday(flask_app):
    """Jan 1 2026 — New Year's Day, market closed."""
    resp = flask_app.test_client().get(
        "/api/v2/calendar/timings",
        query_string={"venue_code": "XNAS", "date": "2026-01-01"},
    )
    assert resp.status_code == 200
    body = resp.get_json()["data"]
    assert body["is_open"] is False
    assert "session_open" not in body


def test_timings_xnas_weekend(flask_app):
    """May 9 2026 — Saturday."""
    resp = flask_app.test_client().get(
        "/api/v2/calendar/timings",
        query_string={"venue_code": "XNAS", "date": "2026-05-09"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["is_open"] is False


def test_timings_bad_date_returns_400(flask_app):
    resp = flask_app.test_client().get(
        "/api/v2/calendar/timings",
        query_string={"venue_code": "XNAS", "date": "not-a-date"},
    )
    assert resp.status_code == 400


def test_holidays_nse_2026(flask_app):
    """NSE supports NSE calendar in pandas_market_calendars."""
    resp = flask_app.test_client().get(
        "/api/v2/calendar/holidays",
        query_string={"venue_code": "NSE", "year": "2026"},
    )
    assert resp.status_code == 200
    body = resp.get_json()["data"]
    assert body["venue_code"] == "NSE"
    assert body["timezone"] == "Asia/Kolkata"
    assert isinstance(body["holidays"], list)
