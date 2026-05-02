"""Phase 1 v5 (ADR 0030) — promoted-request observability label set.

Asserts:
* Every required label key is present in the canonical context.
* `legacy_lane=False` is the default for v2 contexts.
* The helper raises if an incomplete context is constructed via
  asdict-style mutation.
* The legacy-lane warning fires when `legacy_lane=True` + `route="v2"`.
"""

from __future__ import annotations

import logging

from utils.observability import (
    REQUIRED_LABELS,
    PromotedRequestContext,
    build_context,
    log_promoted_request,
)


REQUIRED_KEYS = set(REQUIRED_LABELS)


def test_required_labels_set_is_canonical():
    expected = {
        "region_code",
        "broker_code",
        "venue_code",
        "instrument_id",
        "currency",
        "provider_code",
        "capability_source",
        "legacy_lane",
        "route",
        "request_id",
    }
    assert REQUIRED_KEYS == expected


def test_build_context_emits_all_required_labels_with_defaults():
    ctx = build_context(capability_source="region")
    d = ctx.as_label_dict()
    assert REQUIRED_KEYS.issubset(d.keys())
    # nullable defaults
    assert d["region_code"] is None
    assert d["broker_code"] is None
    assert d["legacy_lane"] is False
    assert d["route"] == "v2"
    assert d["capability_source"] == "region"


def test_build_context_carries_explicit_values():
    ctx = build_context(
        capability_source="provider",
        region_code="india",
        broker_code="zerodha",
        venue_code="XNSE",
        instrument_id="instr-uuid-1",
        currency="INR",
        provider_code="india",
        request_id="req-1",
    )
    d = ctx.as_label_dict()
    assert d["region_code"] == "india"
    assert d["broker_code"] == "zerodha"
    assert d["venue_code"] == "XNSE"
    assert d["instrument_id"] == "instr-uuid-1"
    assert d["currency"] == "INR"
    assert d["provider_code"] == "india"
    assert d["capability_source"] == "provider"
    assert d["request_id"] == "req-1"


def test_assert_complete_raises_when_required_label_missing(monkeypatch):
    """If a downstream serializer drops a required key, assert_complete catches it."""
    ctx = build_context(capability_source="region")

    # Simulate a stale serializer that returned only a subset.
    def broken_dict(self):
        return {"region_code": None, "route": "v2"}

    monkeypatch.setattr(PromotedRequestContext, "as_label_dict", broken_dict)
    import pytest

    with pytest.raises(ValueError, match="missing required label keys"):
        ctx.assert_complete()


def test_log_promoted_request_emits_payload(caplog):
    ctx = build_context(
        capability_source="broker",
        region_code="india",
        broker_code="zerodha",
        route="v2",
        legacy_lane=False,
        request_id="req-42",
    )
    with caplog.at_level(logging.INFO, logger="utils.observability"):
        payload = log_promoted_request(ctx, event="order_admitted")
    assert payload["event"] == "order_admitted"
    assert payload["region_code"] == "india"
    assert payload["broker_code"] == "zerodha"
    assert payload["legacy_lane"] is False
    assert payload["route"] == "v2"
    assert payload["request_id"] == "req-42"
    assert REQUIRED_KEYS.issubset(payload.keys())


def test_log_promoted_request_warns_on_legacy_lane_under_v2(caplog):
    """legacy_lane=True under route="v2" is a dispatch bug; helper warns."""
    ctx = build_context(
        capability_source="region",
        route="v2",
        legacy_lane=True,
        broker_code="zerodha",
        region_code="india",
    )
    with caplog.at_level(logging.WARNING, logger="utils.observability"):
        log_promoted_request(ctx, event="order_admitted")
    assert any(
        "legacy_lane=true with route=v2" in record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING
    )


def test_v1_route_does_not_call_helper():
    """Document the contract: legacy v1 routes do NOT call the promoted helper.

    This is enforced by code review; the test grep-asserts that the
    v1 lane guard (and any v1 handler) does not import
    `utils.observability`.

    Phase 9-bis-physical (T-23 Group D) relocated the guard to
    market_regions/india/legacy_v1/restx_api/_v1_lane_guard.py.
    """
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    v1_guard = (
        repo_root
        / "market_regions"
        / "india"
        / "legacy_v1"
        / "restx_api"
        / "_v1_lane_guard.py"
    )
    assert v1_guard.is_file()
    text = v1_guard.read_text(encoding="utf-8")
    assert "utils.observability" not in text, (
        "v1 lane guard must not emit promoted-request labels (ADR 0030)."
    )
