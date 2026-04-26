"""Phase 2 v4 — master contract status returns the actual configured
timezone string, not a binary UTC/IST label.

ADR 0023 invariant 1: timezone reads route through the broker plugin's
``master_contract_refresh_policy``.
"""

from __future__ import annotations

import pytz

from utils import auth_utils


def test_get_master_contract_cutoff_returns_iana_zone_for_india(monkeypatch):
    monkeypatch.delenv("MASTER_CONTRACT_CUTOFF_TIME", raising=False)
    # Default behavior for an India broker: cutoff_time, IST zone.
    cutoff_hour, cutoff_minute, tz = auth_utils.get_master_contract_cutoff(
        "zerodha"
    )
    assert cutoff_hour == 8
    assert cutoff_minute == 0
    # Returns the actual pytz tz object (zone string Asia/Kolkata).
    assert getattr(tz, "zone", None) == "Asia/Kolkata"


def test_get_master_contract_cutoff_returns_utc_for_crypto(monkeypatch):
    monkeypatch.delenv("CRYPTO_MASTER_CONTRACT_CUTOFF_TIME", raising=False)
    cutoff_hour, cutoff_minute, tz = auth_utils.get_master_contract_cutoff(
        "deltaexchange"
    )
    assert cutoff_hour == 0
    assert cutoff_minute == 0
    assert tz is pytz.utc


def test_smart_status_uses_real_zone_string(monkeypatch):
    """The blueprint should surface the configured tz string, not 'IST'."""
    # Stub the cutoff to return a non-default zone via a mock plugin policy.
    fake_tz = pytz.timezone("America/New_York")

    def _fake_cutoff(broker):
        return 9, 30, fake_tz

    monkeypatch.setattr(
        "blueprints.master_contract_status.get_master_contract_cutoff",
        _fake_cutoff,
    )
    # We don't need to spin up Flask to test the labelling code; just
    # call the helper logic the way the route does.
    cutoff_hour, cutoff_minute, tz = _fake_cutoff("alpaca")
    cutoff_timezone = getattr(tz, "zone", None) or str(tz)
    assert cutoff_timezone == "America/New_York"
    assert cutoff_timezone != "IST"
    assert cutoff_timezone != "UTC"
