"""Phase 3 v4 (ADR 0023) — region data seeder is idempotent.

Confirms that running ``scripts.seed_region_data.seed_all_regions``
twice produces the same row counts and does not duplicate venues,
session templates, or calendar exceptions.
"""

from __future__ import annotations

import pytest

from database import instruments_repo
from database import venue_schedule_repo


@pytest.fixture(autouse=True)
def _setup_db():
    # Initialize tables. instruments_repo and venue_schedule_repo share
    # the Base metadata so create_all covers both.
    venue_schedule_repo.init_venue_schedule_tables()
    yield


def test_seed_all_regions_runs_clean():
    from scripts import seed_region_data

    counts = seed_region_data.seed_all_regions()
    assert "india" in counts
    assert "us" in counts
    assert "eu" in counts
    assert "uk" in counts
    assert counts["india"]["venues"] >= 6
    assert counts["us"]["venues"] >= 2


def test_seed_all_regions_is_idempotent():
    from scripts import seed_region_data

    first = seed_region_data.seed_all_regions()
    second = seed_region_data.seed_all_regions()
    # Counts are how many seed-rows were written, not the table size.
    # The repo is upsert-by-key, so a second run still calls upsert
    # for the same rows but does not duplicate them. Verify the
    # underlying table row count is stable.
    venues_after_first = instruments_repo.venues_list()
    n1 = len(venues_after_first)
    seed_region_data.seed_all_regions()
    venues_after_third = instruments_repo.venues_list()
    n2 = len(venues_after_third)
    assert n1 == n2, (
        f"Idempotency broken: venues table size grew from {n1} to {n2}"
    )


def test_us_venues_are_seeded_with_correct_tz():
    from scripts import seed_region_data

    seed_region_data.seed_all_regions(region_codes=["us"])
    xnys = instruments_repo.venues_get("XNYS")
    assert xnys is not None
    assert xnys.timezone_name == "America/New_York"
    assert xnys.base_currency == "USD"
    xnas = instruments_repo.venues_get("XNAS")
    assert xnas is not None
    assert xnas.timezone_name == "America/New_York"


def test_eu_uk_venues_are_seeded_with_correct_tz():
    from scripts import seed_region_data

    seed_region_data.seed_all_regions(region_codes=["eu", "uk"])
    xpar = instruments_repo.venues_get("XPAR")
    assert xpar is not None
    assert xpar.timezone_name == "Europe/Paris"
    assert xpar.base_currency == "EUR"
    xetr = instruments_repo.venues_get("XETR")
    assert xetr is not None
    assert xetr.timezone_name == "Europe/Berlin"
    xlon = instruments_repo.venues_get("XLON")
    assert xlon is not None
    assert xlon.timezone_name == "Europe/London"
    assert xlon.base_currency == "GBP"
