"""Phase 4 — utils.session reads SESSION_EXPIRY_TIMEZONE.

Default tz remains Asia/Kolkata for backward compatibility. Operators
on US/EU venues set SESSION_EXPIRY_TIMEZONE explicitly.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch):
    monkeypatch.delenv("SESSION_EXPIRY_TIMEZONE", raising=False)
    monkeypatch.delenv("SESSION_EXPIRY_TIME", raising=False)
    monkeypatch.delenv("DISABLE_SESSION_EXPIRY", raising=False)


def test_default_tz_is_asia_kolkata(monkeypatch) -> None:
    """No env var → tz = Asia/Kolkata (legacy default)."""
    from utils import session as utils_session

    tz = utils_session._session_tz()
    assert str(tz) == "Asia/Kolkata"


def test_explicit_us_tz(monkeypatch) -> None:
    monkeypatch.setenv("SESSION_EXPIRY_TIMEZONE", "America/New_York")
    from utils import session as utils_session

    tz = utils_session._session_tz()
    assert str(tz) == "America/New_York"


def test_unknown_tz_falls_back_to_kolkata(monkeypatch) -> None:
    monkeypatch.setenv("SESSION_EXPIRY_TIMEZONE", "Mars/Olympus")
    from utils import session as utils_session

    tz = utils_session._session_tz()
    assert str(tz) == "Asia/Kolkata"


def test_get_session_expiry_time_returns_timedelta(monkeypatch) -> None:
    monkeypatch.setenv("SESSION_EXPIRY_TIMEZONE", "UTC")
    monkeypatch.setenv("SESSION_EXPIRY_TIME", "03:00")
    from utils.session import get_session_expiry_time

    delta = get_session_expiry_time()
    assert isinstance(delta, timedelta)
    assert timedelta(seconds=0) < delta <= timedelta(days=1)


def test_get_session_expiry_time_disabled(monkeypatch) -> None:
    monkeypatch.setenv("DISABLE_SESSION_EXPIRY", "true")
    from utils.session import get_session_expiry_time

    delta = get_session_expiry_time()
    assert delta == timedelta(days=365)


def test_get_session_expiry_time_independent_of_container_tz(monkeypatch) -> None:
    """Same SESSION_EXPIRY_TIME with different SESSION_EXPIRY_TIMEZONE
    produce a different remaining-time delta — the calc anchors on the
    configured tz, not on the host clock's local tz."""
    monkeypatch.setenv("SESSION_EXPIRY_TIME", "03:00")

    monkeypatch.setenv("SESSION_EXPIRY_TIMEZONE", "America/New_York")
    from utils.session import get_session_expiry_time

    delta_ny = get_session_expiry_time()

    monkeypatch.setenv("SESSION_EXPIRY_TIMEZONE", "Asia/Kolkata")
    delta_kol = get_session_expiry_time()

    # India is UTC+5:30, NY is UTC-5/UTC-4. Their "next 03:00 local"
    # almost never lines up — at any given UTC instant the deltas
    # differ by enough that we can assert inequality. Allow 1 minute
    # tolerance to defend against a CI second-tick coincidence.
    assert abs((delta_ny - delta_kol).total_seconds()) > 60
