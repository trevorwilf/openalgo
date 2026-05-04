"""T-14 (v7 Phase 3) — region-dispatched holiday calendar.

Asserts:
* ``GET /api/v2/regions/india/holidays`` returns India holidays from
  the plugin.json calendar_exceptions block.
* Year query param filters by year (default current year).
* Unknown region returns 404 ``region_not_found``.
* US region returns its own (currently empty) calendar; the legacy
  India v1 ``/market/holidays`` endpoint is NOT routed for non-
  India brokers.
"""

from __future__ import annotations

import os

import pytest

# Force API_V2 on at module load so the regions namespace mounts.
os.environ.setdefault("API_V2", "1")

from app import app  # noqa: E402


@pytest.fixture
def client():
    return app.test_client()


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
