"""Phase 4 — /api/v2/venues endpoints."""

from __future__ import annotations

from datetime import date as date_type, time as dt_time

import pytest


def _seed_venue(code: str, **overrides):
    from database.instruments_repo import venues_upsert

    payload = {
        "venue_code": code,
        "market_family": "IN_STOCK",
        "country_code": "IN",
        "timezone_name": "Asia/Kolkata",
        "base_currency": "INR",
        "settlement_type": "T+1",
        "session_model": "REGULAR_ONLY",
        "display_name": code,
    }
    payload.update(overrides)
    venues_upsert(**payload)


def test_venue_list_returns_seeded_venues(flask_app) -> None:
    _seed_venue("NSE")
    _seed_venue("XNYS",
                market_family="US_STOCK",
                country_code="US",
                timezone_name="America/New_York",
                base_currency="USD")
    resp = flask_app.test_client().get("/api/v2/venues")
    assert resp.status_code == 200
    body = resp.get_json()
    codes = {v["venue_code"] for v in body["data"]["venues"]}
    assert {"NSE", "XNYS"} <= codes


def test_venue_detail_round_trip(flask_app) -> None:
    _seed_venue("XLON",
                market_family="UK_STOCK",
                country_code="GB",
                timezone_name="Europe/London",
                base_currency="GBP",
                settlement_type="T+2",
                session_model="AUCTIONS_AND_REGULAR")
    resp = flask_app.test_client().get("/api/v2/venues/XLON")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"]["venue_code"] == "XLON"
    assert body["data"]["timezone_name"] == "Europe/London"
    assert body["data"]["base_currency"] == "GBP"
    assert body["data"]["settlement_template"] == "T+2"


def test_venue_detail_404_for_missing(flask_app) -> None:
    resp = flask_app.test_client().get("/api/v2/venues/NOPE")
    assert resp.status_code == 404
    body = resp.get_json()
    assert body["error"]["code"] == "venue_not_found"


def test_venue_sessions_returns_window(flask_app) -> None:
    _seed_venue("NSE")
    from database.venue_schedule_repo import upsert_schedule_template

    # NSE Mon-Fri 09:15-15:30
    for dow in range(5):
        upsert_schedule_template(
            venue_code="NSE",
            day_of_week=dow,
            session_type="REGULAR",
            starts_at_local=dt_time(9, 15),
            ends_at_local=dt_time(15, 30),
        )

    # 2026-04-27 is a Monday (dow=0)
    target = date_type(2026, 4, 27)
    resp = flask_app.test_client().get(
        f"/api/v2/venues/NSE/sessions?date={target.isoformat()}"
    )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    sessions = body["data"]["sessions"]
    assert len(sessions) >= 1
    assert sessions[0]["session_type"] == "REGULAR"
    assert "start_utc" in sessions[0] and "end_utc" in sessions[0]


def test_venue_sessions_404_for_missing_venue(flask_app) -> None:
    resp = flask_app.test_client().get("/api/v2/venues/NOPE/sessions")
    assert resp.status_code == 404


def test_venue_sessions_bad_date_returns_400(flask_app) -> None:
    _seed_venue("NSE")
    resp = flask_app.test_client().get("/api/v2/venues/NSE/sessions?date=27-04-2026")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"]["code"] == "bad_request"
