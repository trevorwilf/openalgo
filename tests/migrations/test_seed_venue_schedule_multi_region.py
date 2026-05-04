"""T-18 (v7 Phase 3-ter) — multi-region seeder dispatch.

Asserts the seeder reads venue declarations from each loaded
region plugin in addition to the static ``VENUE_SEEDS`` list.
India install: bit-identical seed (static covers it). US/EU/UK
installs gain region-plugin-declared venues.
"""

from __future__ import annotations


def test_seeder_reads_region_plugin_venues():
    from upgrade.seed_venue_schedule_defaults import _venues_from_region_plugins

    extras = _venues_from_region_plugins()
    # The US region plugin declares ARCX/BATS/IEXG (in addition to
    # XNYS/XNAS which are already in the static seed).
    codes = {v["venue_code"] for v in extras}
    assert "ARCX" in codes
    assert "BATS" in codes


def test_seeder_static_list_still_present():
    """The historical static seeds (NSE/BSE/etc.) remain — region
    plugins augment, they don't replace."""
    from upgrade.seed_venue_schedule_defaults import VENUE_SEEDS

    static_codes = {v["venue_code"] for v in VENUE_SEEDS}
    # India venues still in static.
    assert {"NSE", "BSE", "NFO", "BFO", "MCX"}.issubset(static_codes)
    # Crypto venues still in static.
    assert "CRYPTO" in static_codes
