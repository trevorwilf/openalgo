"""Phase 2 v4 — utils.session fail-closed when SESSION_EXPIRY_TIMEZONE
is unset and the active broker is non-India.

ADR 0023 invariant 1: missing config in promoted code is a structured
error, not a silent India fallback. ``_session_tz`` only triggers the
fail-closed path when there is a confidently-resolved non-India broker
session; absence of a broker (bootstrap) defers to Asia/Kolkata so the
app can come up.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from domain.errors import ConfigurationError
from utils import session as session_module


def test_explicit_env_value_wins(monkeypatch):
    monkeypatch.setenv("SESSION_EXPIRY_TIMEZONE", "America/New_York")
    tz = session_module._session_tz()
    assert tz.zone == "America/New_York"


def test_unset_no_broker_session_returns_utc_in_bootstrap(monkeypatch):
    """Phase 1 T-08: bootstrap (no broker session, no env var) returns
    UTC instead of the prior implicit Asia/Kolkata default. India
    operators that need Kolkata in the bootstrap window must set
    SESSION_EXPIRY_TIMEZONE explicitly."""
    monkeypatch.delenv("SESSION_EXPIRY_TIMEZONE", raising=False)
    monkeypatch.setattr(session_module, "_resolve_active_broker_caps", lambda: None)
    # Reset the one-shot warning flag so this test always exercises the warning path.
    if hasattr(session_module._session_tz, "_bootstrap_warned"):
        delattr(session_module._session_tz, "_bootstrap_warned")
    tz = session_module._session_tz()
    assert tz.zone == "UTC"


def test_t07_venue_offset_none_raises(monkeypatch):
    """Phase 1 T-07: venue_local_offset_seconds(None) is now a
    structured VenueResolutionError instead of silent 19800."""
    from database.venue_offset import venue_local_offset_seconds
    from domain.errors import VenueResolutionError

    with pytest.raises(VenueResolutionError):
        venue_local_offset_seconds(None)


def test_unset_with_india_broker_returns_kolkata(monkeypatch):
    monkeypatch.delenv("SESSION_EXPIRY_TIMEZONE", raising=False)
    caps = SimpleNamespace(supported_regions=["india"])
    monkeypatch.setattr(session_module, "_resolve_active_broker_caps", lambda: caps)
    tz = session_module._session_tz()
    assert tz.zone == "Asia/Kolkata"


def test_unset_with_non_india_broker_raises(monkeypatch):
    monkeypatch.delenv("SESSION_EXPIRY_TIMEZONE", raising=False)
    caps = SimpleNamespace(supported_regions=["us"])
    monkeypatch.setattr(session_module, "_resolve_active_broker_caps", lambda: caps)
    with pytest.raises(ConfigurationError) as exc:
        session_module._session_tz()
    assert exc.value.missing_env == "SESSION_EXPIRY_TIMEZONE"
    msg = str(exc.value)
    assert "us" in msg.lower()
    assert "America/New_York" in msg or "non-India" in msg


def test_unset_with_legacy_india_plugin_no_regions_returns_kolkata(monkeypatch):
    """A legacy India broker plugin without explicit ``supported_regions``
    behaves as India (bit-identical preservation)."""
    monkeypatch.delenv("SESSION_EXPIRY_TIMEZONE", raising=False)
    caps = SimpleNamespace(supported_regions=None)
    monkeypatch.setattr(session_module, "_resolve_active_broker_caps", lambda: caps)
    tz = session_module._session_tz()
    assert tz.zone == "Asia/Kolkata"


def test_invalid_env_falls_back_to_kolkata_with_warning(monkeypatch):
    monkeypatch.setenv("SESSION_EXPIRY_TIMEZONE", "Mars/Olympus_Mons")
    tz = session_module._session_tz()
    assert tz.zone == "Asia/Kolkata"
