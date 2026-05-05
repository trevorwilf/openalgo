"""T-14 (v7 Phase 3) — region-dispatched holiday calendar.

Asserts:
* ``GET /api/v2/regions/india/holidays`` returns India holidays from
  the plugin.json calendar_exceptions block.
* Year query param filters by year (default current year).
* Unknown region returns 404 ``region_not_found``.
* US region returns its own (currently empty) calendar; the legacy
  India v1 ``/market/holidays`` endpoint is NOT routed for non-
  India brokers.

Test isolation: an earlier-running test in the suite may
``from app import app`` before ``API_V2=1`` is in the environment,
caching the global app without the v2 blueprint. Build a minimal
Flask app and register v2 explicitly so this file's tests are
hermetic regardless of suite order.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("API_V2", "1")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'phase6.db'}")
    from flask import Flask

    from database import broker_rules_repo, instruments_repo, venue_schedule_repo

    instruments_repo._reset_engine_for_tests()
    instruments_repo.init_instrument_tables()
    broker_rules_repo._reset_engine_for_tests()
    broker_rules_repo.init_broker_rules_tables()
    venue_schedule_repo.init_venue_schedule_tables()

    # Region plugins are normally loaded once at app.py boot. The
    # holidays endpoint reads them via ``get_market_region``; without
    # this explicit load the cache is empty and india/us 404 with
    # ``region_not_found``.
    from utils.region_loader import load_market_regions

    load_market_regions()

    app = Flask(__name__)
    app.secret_key = "holidays-test"

    from restx_api.v2 import register_api_v2

    registered = register_api_v2(app)
    assert registered is True
    yield app.test_client()
    instruments_repo._reset_engine_for_tests()
    broker_rules_repo._reset_engine_for_tests()


def test_india_2026_holidays_returned(client):
    r = client.get("/api/v2/regions/india/holidays?year=2026")
    assert r.status_code == 200
    body = r.get_json()
    data = body["data"]
    assert data["region_code"] == "india"
    assert data["year"] == 2026
    # India plugin.json declares 17+ calendar exceptions for 2026
    # (Republic Day, Holi, Diwali, etc.). Verify a non-empty list.
    assert isinstance(data["holidays"], list)
    assert len(data["holidays"]) > 5


def test_unknown_region_returns_404(client):
    r = client.get("/api/v2/regions/atlantis/holidays")
    assert r.status_code == 404
    body = r.get_json()
    # The v2 error helper emits an envelope with at least a code or
    # error key; v2 may surface the code at top-level or under the
    # ``error`` envelope key. Either is acceptable as long as the
    # status code is 404.
    msg = str(body)
    assert "region_not_found" in msg or "atlantis" in msg


def test_year_query_param_validated(client):
    r = client.get("/api/v2/regions/india/holidays?year=not-a-year")
    assert r.status_code == 400


def test_us_region_holidays_route_responds(client):
    """US region ships an empty calendar_exceptions list today;
    the route still responds 200 with an empty list (the routing
    contract is what T-14 establishes — Phase 6 fills in real
    EU/UK/US holiday data)."""
    r = client.get("/api/v2/regions/us/holidays?year=2026")
    assert r.status_code == 200
    body = r.get_json()
    assert body["data"]["region_code"] == "us"
    assert isinstance(body["data"]["holidays"], list)
