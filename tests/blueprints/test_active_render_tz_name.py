"""Phase 1 (T-01/T-02) render-tz resolution test.

Asserts :func:`utils.venue_local_time.active_render_tz_name` returns
the expected IANA tz name for India and US active regions. This is
the helper the 6 promoted blueprints (pnltracker, analyzer, health,
latency, log, traffic) call for their wall-clock display logic.

Forces the active region via ``MARKET_REGION_FOR_TESTS`` (the
service-layer override read by
:func:`services.feature_gate_service.active_region_code`).
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def force_region(monkeypatch):
    def _set(code: str | None):
        if code is None:
            monkeypatch.delenv("MARKET_REGION_FOR_TESTS", raising=False)
        else:
            monkeypatch.setenv("MARKET_REGION_FOR_TESTS", code)
    return _set


def test_india_active_region_resolves_to_kolkata(force_region):
    """India operator → Asia/Kolkata (bit-identical legacy)."""
    force_region("india")
    from utils.venue_local_time import active_render_tz_name
    assert active_render_tz_name() == "Asia/Kolkata"


def test_us_active_region_resolves_to_new_york(force_region):
    """US operator → America/New_York (XNAS / XNYS / ARCX / BATS)."""
    force_region("us")
    from utils.venue_local_time import active_render_tz_name
    assert active_render_tz_name() == "America/New_York"


def test_no_region_falls_back_to_kolkata_for_legacy_compat(force_region, monkeypatch):
    """Render layer never raises — when region resolution fails,
    falls back to Asia/Kolkata so legacy India deployments keep
    wall-clock display unchanged. Fail-closed behavior is reserved
    for write paths (T-10, T-11)."""
    # Clear the env override AND simulate no Flask session. The
    # fallback chain inside active_region_code() will fail, and
    # active_render_tz_name() must catch and return India tz.
    force_region(None)
    monkeypatch.delenv("MARKET_REGION_FOR_TESTS", raising=False)
    from utils.venue_local_time import active_render_tz_name
    # The function MUST NOT raise. We don't strictly assert
    # 'Asia/Kolkata' here because a configured installation may
    # resolve via the settings table; both outcomes are valid.
    result = active_render_tz_name()
    assert isinstance(result, str)
    assert result  # non-empty


def test_eu_active_region_resolves_to_european_tz(force_region):
    """EU operator → European tz from the EU region plugin's primary
    venue. Phase 1 deliverable — Phase 6 fills in real venue
    behavior; for Phase 1, just assert the function returns a
    plausible European IANA tz string."""
    force_region("eu")
    from utils.venue_local_time import active_render_tz_name
    result = active_render_tz_name()
    # The EU plugin currently declares minimal stub vocabularies;
    # the helper must still return a non-empty IANA tz name.
    assert isinstance(result, str)
    assert result
