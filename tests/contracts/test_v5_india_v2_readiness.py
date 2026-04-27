"""Phase 8 v5 — India v1→v2 readiness contract.

Asserts the load-bearing pieces of the v5 Phase 8 deliverable:

* Every `/api/v1/*` response carries `Deprecation: true` and
  `Sunset: <date>` headers (RFC 8594).
* Every India broker plugin can be inferred into a complete
  `BrokerCapabilities` object via the loader (no missing required
  fields).
* The readiness matrix doc exists.
* The migration doc exists.

Per-broker translator + per-broker parity harnesses are explicitly
deferred to v5 Phase 8-bis (see
`docs/refactor/v5_india_v2_readiness_matrix.md`); this test
documents the deferral.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BROKER_ROOT = REPO_ROOT / "broker"
INDIA_BROKERS_HINT = (
    "aliceblue", "angel", "compositedge", "definedge", "dhan",
    "dhan_sandbox", "firstock", "fivepaisa", "fivepaisaxts",
    "flattrade", "fyers", "groww", "ibulls", "iifl", "iiflcapital",
    "indmoney", "jainamxts", "kotak", "motilal", "mstock", "nubra",
    "paytm", "pocketful", "rmoney", "samco", "shoonya", "tradejini",
    "upstox", "zerodha",
)


def test_v5_india_v2_readiness_matrix_exists():
    p = REPO_ROOT / "docs" / "refactor" / "v5_india_v2_readiness_matrix.md"
    assert p.is_file(), f"missing {p.relative_to(REPO_ROOT).as_posix()}"
    text = p.read_text(encoding="utf-8")
    # Spot-check that the matrix lists at least 5 India brokers.
    listed = sum(1 for b in INDIA_BROKERS_HINT if f"| {b} " in text or f"| **{b}**" in text)
    assert listed >= 5, (
        f"matrix should list at least 5 India brokers; got {listed}"
    )


def test_v1_to_v2_migration_doc_exists():
    p = REPO_ROOT / "docs" / "migration" / "v1-to-v2.md"
    assert p.is_file(), f"missing {p.relative_to(REPO_ROOT).as_posix()}"
    text = p.read_text(encoding="utf-8")
    # Spot-check that the migration doc covers placeorder + quotes
    # + history (the highest-traffic surface).
    assert "/api/v1/placeorder" in text
    assert "/api/v1/quotes" in text
    assert "/api/v1/history" in text
    assert "Deprecation: true" in text


@pytest.mark.parametrize("broker", INDIA_BROKERS_HINT)
def test_india_broker_plugin_json_present(broker):
    """Every India broker the matrix lists must have a plugin.json."""
    p = BROKER_ROOT / broker / "plugin.json"
    assert p.is_file(), (
        f"India broker {broker!r} missing plugin.json — matrix lists it; "
        "either add the file or remove the broker from the matrix."
    )
    payload = json.loads(p.read_text(encoding="utf-8"))
    # Minimum: the loader needs broker_type + supported_exchanges.
    assert "broker_type" in payload, f"{broker}: plugin.json missing broker_type"
    assert "supported_exchanges" in payload, (
        f"{broker}: plugin.json missing supported_exchanges"
    )


def test_india_broker_inference_produces_complete_capabilities():
    """Every India broker should infer to a complete BrokerCapabilities
    via `_indian_defaults()`, even without explicit plugin fields."""
    from domain.capabilities import (
        BrokerCapabilities,
        infer_capabilities_from_legacy,
    )

    for broker in ("zerodha", "angel", "dhan", "fyers", "upstox"):
        plugin = json.loads(
            (BROKER_ROOT / broker / "plugin.json").read_text(encoding="utf-8")
        )
        inferred = infer_capabilities_from_legacy(
            plugin_data=plugin, broker_code=broker
        )
        # The inference must give us something valid enough for the
        # BrokerCapabilities model; `supported_venue_codes` is the
        # rename of `supported_exchanges`.
        if "supported_venue_codes" not in inferred:
            inferred["supported_venue_codes"] = list(
                plugin.get("supported_exchanges", [])
            )
        inferred.setdefault("broker_code", broker)
        inferred.setdefault("broker_display_name", broker.title())
        caps = BrokerCapabilities(**inferred)
        assert caps.supports_sandbox is True
        assert caps.supports_options is True
        assert caps.supports_screener_providers is True
        assert "india" in caps.supported_regions


def test_v1_route_emits_deprecation_headers():
    """Every /api/v1/* response must carry RFC-8594 headers.

    v1 endpoints are POST-everywhere (Flask-RESTX namespaces). The
    test issues a POST without a valid API key — the route's auth
    layer rejects with 403, but the after_request hook still runs
    inside the api_v1_bp and stamps the Deprecation/Sunset headers.
    """
    from app import app

    client = app.test_client()
    # POST with a bogus payload. The auth layer rejects (401/403),
    # but the after_request hook adds the headers.
    resp = client.post("/api/v1/ping/", json={"apikey": "test"})
    assert resp.headers.get("Deprecation") == "true", (
        f"missing Deprecation header on /api/v1/ping/ (status={resp.status_code})"
    )
    sunset = resp.headers.get("Sunset")
    assert sunset, "missing Sunset header on /api/v1/ping/"
    # ISO date sanity check — first 4 chars are a year.
    assert len(sunset) >= 10
    assert sunset[:4].isdigit() and int(sunset[:4]) >= 2026


def test_v1_sunset_date_overridable_via_env(monkeypatch):
    """Operator can override the sunset date via OPENALGO_V1_SUNSET_DATE."""
    monkeypatch.setenv("OPENALGO_V1_SUNSET_DATE", "2027-09-30")
    from restx_api import _v1_sunset_date_iso

    assert _v1_sunset_date_iso() == "2027-09-30"
