"""Promoted-request observability label helper (v5 Phase 1, ADR 0030).

A single canonical place to assemble the structured-log line that
describes every promoted (v2) request. Keeps the label set in one
place so that downstream metrics or log shippers can rely on a stable
schema.

This module deliberately does NOT introduce a metrics backend — it
emits a single structured-log line via the standard logger. v6 may
upgrade to OpenTelemetry / Prometheus; the call sites only need the
context dict, not the transport.

Required label set (per ``docs/observability/promoted_request_labels.md``):

* ``region_code``       — active region (e.g., "india", "us") or None
* ``broker_code``       — active broker plugin code or None
* ``venue_code``        — venue (e.g., "XNSE", "XNYS") or None
* ``instrument_id``     — canonical instrument identifier or None
* ``currency``          — ISO 4217 (e.g., "INR", "USD") or None
* ``provider_code``     — sandbox/options/screener provider id or None
* ``capability_source`` — one of "region", "broker", "account", "provider"
* ``legacy_lane``       — bool; True if request was served by the v1 path
* ``route``             — "v1" or "v2"
* ``request_id``        — opaque per-request id (whatever the framework set)

Legacy (v1) callers MUST NOT call this helper. The contract test at
``tests/contracts/test_v5_observability_labels_complete.py`` enforces
that legacy requests do not emit promoted-request log lines.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from utils.logging import get_logger

logger = get_logger(__name__)


CapabilitySource = Literal["region", "broker", "account", "provider"]
LaneRoute = Literal["v1", "v2"]

REQUIRED_LABELS: tuple[str, ...] = (
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
)


@dataclass(frozen=True)
class PromotedRequestContext:
    """Immutable label bundle for a single promoted request.

    All optional fields default to None; the structured logger emits
    them as ``null`` so that downstream parsers see a stable schema.
    The ``capability_source``, ``legacy_lane``, and ``route`` fields
    are required because they describe the dispatch decision and
    cannot be inferred at log time.
    """

    capability_source: CapabilitySource
    route: LaneRoute = "v2"
    legacy_lane: bool = False
    region_code: str | None = None
    broker_code: str | None = None
    venue_code: str | None = None
    instrument_id: str | None = None
    currency: str | None = None
    provider_code: str | None = None
    request_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def as_label_dict(self) -> dict[str, Any]:
        """Return the canonical label dict (REQUIRED_LABELS only)."""
        d = asdict(self)
        d.pop("extra", None)
        return d

    def assert_complete(self) -> None:
        """Raise if any required label key is missing.

        Defensive — catches construction bugs in tests; the dataclass
        already enforces presence at the type level. The check exists
        because new label keys may be appended over time and the
        dataclass cannot stop a downstream user from passing
        ``asdict()`` to a stale serializer.
        """
        d = self.as_label_dict()
        missing = [k for k in REQUIRED_LABELS if k not in d]
        if missing:
            raise ValueError(
                f"PromotedRequestContext missing required label keys: {missing}"
            )


def build_context(
    *,
    capability_source: CapabilitySource,
    route: LaneRoute = "v2",
    legacy_lane: bool = False,
    region_code: str | None = None,
    broker_code: str | None = None,
    venue_code: str | None = None,
    instrument_id: str | None = None,
    currency: str | None = None,
    provider_code: str | None = None,
    request_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> PromotedRequestContext:
    """Build a `PromotedRequestContext` with explicit kwargs only.

    Caller-side convenience that keeps every site honest about which
    label values it owns. No defaults sneak in.
    """
    return PromotedRequestContext(
        capability_source=capability_source,
        route=route,
        legacy_lane=legacy_lane,
        region_code=region_code,
        broker_code=broker_code,
        venue_code=venue_code,
        instrument_id=instrument_id,
        currency=currency,
        provider_code=provider_code,
        request_id=request_id,
        extra=dict(extra or {}),
    )


def log_promoted_request(
    ctx: PromotedRequestContext,
    *,
    event: str,
    message: str | None = None,
    level: int | None = None,
) -> dict[str, Any]:
    """Emit one structured log line for a promoted request.

    Returns the assembled label dict so call sites can attach it to
    additional sinks (audit DB, etc.) without recomputing it.
    """
    import logging as _logging

    ctx.assert_complete()
    if ctx.legacy_lane and ctx.route == "v2":
        # Defensive — flag dispatch bugs that would emit "legacy_lane=true"
        # under the v2 route, which would confuse downstream alerts.
        logger.warning(
            "promoted_request: legacy_lane=true with route=v2 (dispatch bug?) "
            "broker=%s region=%s",
            ctx.broker_code,
            ctx.region_code,
        )

    payload = {
        "event": event,
        **ctx.as_label_dict(),
    }
    if ctx.extra:
        payload["extra"] = dict(ctx.extra)

    if message is None:
        message = json.dumps(payload, default=str, sort_keys=True)
    eff_level = level if level is not None else _logging.INFO
    logger.log(eff_level, "%s", message)
    return payload


__all__ = [
    "CapabilitySource",
    "LaneRoute",
    "PromotedRequestContext",
    "REQUIRED_LABELS",
    "build_context",
    "log_promoted_request",
]
