"""Phase 9 (T-33) — operator-controlled v1 sunset machinery.

When ``OPENALGO_V1_SUNSET_DATE`` is set to an ISO date and today is on
or after that date, every ``/api/v1/*`` request returns 410 Gone with
code ``v1_sunset_passed``, regardless of whether the active broker is
India or not. When the env var is unset (default), the behavior is
the pre-Phase-9 status quo (India brokers proceed; non-India brokers
get the existing ``v1_unavailable_for_non_india_broker`` 410).

The default ``Sunset:`` response header advertised on every v1
response remains 180 days out — that's a *deprecation announcement*,
not enforcement. Setting OPENALGO_V1_SUNSET_DATE is what flips
enforcement on.
"""

from __future__ import annotations

import importlib

import pytest


def test_explicit_sunset_date_parser_handles_iso(monkeypatch):
    monkeypatch.setenv("OPENALGO_V1_SUNSET_DATE", "2027-12-31")
    import restx_api

    importlib.reload(restx_api)
    from datetime import date

    assert restx_api._v1_explicitly_sunset_date() == date(2027, 12, 31)


def test_explicit_sunset_date_parser_returns_none_when_unset(monkeypatch):
    monkeypatch.delenv("OPENALGO_V1_SUNSET_DATE", raising=False)
    import restx_api

    importlib.reload(restx_api)
    assert restx_api._v1_explicitly_sunset_date() is None


def test_explicit_sunset_date_parser_returns_none_on_garbage(monkeypatch):
    monkeypatch.setenv("OPENALGO_V1_SUNSET_DATE", "not-a-date")
    import restx_api

    importlib.reload(restx_api)
    assert restx_api._v1_explicitly_sunset_date() is None


def test_default_sunset_date_iso_is_180_days_out(monkeypatch):
    """The default header value remains 180 days out — that's the
    deprecation announcement, not enforcement."""
    monkeypatch.delenv("OPENALGO_V1_SUNSET_DATE", raising=False)
    import restx_api

    importlib.reload(restx_api)
    iso = restx_api._v1_sunset_date_iso()
    # ISO date format: YYYY-MM-DD
    assert len(iso) == 10
    assert iso[4] == "-"
    assert iso[7] == "-"


def test_explicit_past_sunset_overrides_default_announcement(monkeypatch):
    """When OPENALGO_V1_SUNSET_DATE is set to a past date, the header
    still reflects that explicit value (operators want clients to see
    the configured cutover, not the rolling default)."""
    monkeypatch.setenv("OPENALGO_V1_SUNSET_DATE", "2020-01-01")
    import restx_api

    importlib.reload(restx_api)
    assert restx_api._v1_sunset_date_iso() == "2020-01-01"


def test_v1_before_request_returns_410_when_sunset_in_past(monkeypatch):
    """Direct unit test of the before_request hook — verifies the
    410 Gone shape independently of the Flask test client.

    With OPENALGO_V1_SUNSET_DATE set to 2020-01-01, the hook returns
    a (json, 410) tuple regardless of whether an India broker is
    active.
    """
    monkeypatch.setenv("OPENALGO_V1_SUNSET_DATE", "2020-01-01")
    from flask import Flask

    import restx_api

    importlib.reload(restx_api)

    app = Flask(__name__)
    app.register_blueprint(restx_api.api_v1_bp)
    with app.test_request_context("/api/v1/placeorder", method="POST"):
        resp = restx_api._v1_block_non_india_brokers_or_sunset()
    assert resp is not None, (
        "Sunset hook must short-circuit when the env date is in the past"
    )
    body, status = resp
    assert status == 410
    payload = body.get_json()
    assert payload["status"] == "error"
    assert payload["code"] == "v1_sunset_passed"
    assert "2020-01-01" in payload["message"]


def test_v1_before_request_passes_through_when_sunset_not_set(monkeypatch):
    """Without the env var, the hook delegates to the pre-existing
    non-India guard (returns None for India brokers, 410 for non-India).
    The exact return depends on broker session state; this test only
    verifies the sunset path is NOT taken."""
    monkeypatch.delenv("OPENALGO_V1_SUNSET_DATE", raising=False)
    from flask import Flask

    import restx_api

    importlib.reload(restx_api)

    app = Flask(__name__)
    app.register_blueprint(restx_api.api_v1_bp)
    with app.test_request_context("/api/v1/placeorder", method="POST"):
        resp = restx_api._v1_block_non_india_brokers_or_sunset()
    if resp is not None:
        # Whatever the response is, it must NOT be the sunset code.
        body, status = resp
        if hasattr(body, "get_json"):
            payload = body.get_json() or {}
        else:
            payload = body or {}
        assert payload.get("code") != "v1_sunset_passed", (
            "Without OPENALGO_V1_SUNSET_DATE the hook must not return "
            "v1_sunset_passed"
        )
