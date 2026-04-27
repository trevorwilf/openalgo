"""Domain-level exception hierarchy.

Keep these narrow — the point is to let callers distinguish "this
broker cannot do that" (UnsupportedCapability) from "the instrument
does not exist" (InstrumentNotResolvable) from "the request is
malformed" (ValidationError, re-exported from pydantic).
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError  # re-exported


class DomainError(Exception):
    """Base for all intentional domain-layer errors."""


class InstrumentNotResolvable(DomainError):
    """The requested instrument cannot be resolved in the current universe.

    Carries the attempted `InstrumentRef` for logging. Stored as
    `attempted_ref` attribute since importing the type here would
    create a circular import.
    """

    def __init__(self, message: str, attempted_ref: Any | None = None) -> None:
        super().__init__(message)
        self.attempted_ref = attempted_ref


class UnsupportedCapability(DomainError):
    """The active broker does not expose the capability this operation needs.

    Example: a crypto-only broker being asked for an Indian-style MIS
    product. `broker_code`, `capability_name`, and `details` are for
    structured logging.

    v5 Phase 1: optional `dimension` field — one of "order_type", "tif",
    "session", "quantity_unit", "currency", "asset_class",
    "product_intent", "combo_type", "stream_transport". Allows the v2
    error body to point the client at exactly which dimension failed
    so the UI can mark the offending control.
    """

    DIMENSIONS = (
        "order_type",
        "tif",
        "session",
        "quantity_unit",
        "currency",
        "asset_class",
        "product_intent",
        "combo_type",
        "stream_transport",
    )

    def __init__(
        self,
        broker_code: str,
        capability_name: str,
        details: str | None = None,
        *,
        dimension: str | None = None,
    ) -> None:
        if dimension is not None and dimension not in self.DIMENSIONS:
            raise ValueError(
                f"unknown UnsupportedCapability.dimension {dimension!r}; "
                f"valid: {self.DIMENSIONS}"
            )
        msg = f"broker {broker_code!r} does not support capability {capability_name!r}"
        if dimension:
            msg = f"{msg} (dimension={dimension})"
        if details:
            msg = f"{msg}: {details}"
        super().__init__(msg)
        self.broker_code = broker_code
        self.capability_name = capability_name
        self.details = details
        self.dimension = dimension


class CapabilityMismatch(DomainError):
    """A request combines capabilities in a way the active broker does not allow.

    Distinct from UnsupportedCapability: each piece alone may be supported,
    but the combination is not (e.g., GTC on an IOC-only venue).
    """


class BrokerCapabilityError(DomainError):
    """A broker plugin is missing required capability metadata.

    Raised when a plugin declares a non-India `supported_regions` but
    omits one of the explicit fields the promoted lane requires
    (broker_type, market_families, default_currency, base_currency).
    The fail-closed behavior in Phase 1 prevents silent IN_stock/INR
    inference for foreign brokers.

    Attributes
    ----------
    broker_code : str
    missing_fields : list[str]
    """

    def __init__(
        self,
        broker_code: str,
        missing_fields: list[str] | None = None,
        message: str | None = None,
    ) -> None:
        self.broker_code = broker_code
        self.missing_fields = list(missing_fields or [])
        if message is None:
            if self.missing_fields:
                fields = ", ".join(self.missing_fields)
                message = (
                    f"broker {broker_code!r}: capability metadata incomplete; "
                    f"missing required fields: {fields}"
                )
            else:
                message = f"broker {broker_code!r}: capability metadata incomplete"
        super().__init__(message)


# Stable error codes that cross the API boundary. Frontends key off
# these to render localized messages and to decide fallback behavior.
class ErrorCode:
    """Stable, namespaced error codes returned in JSON error bodies."""

    # Phase 1 — capability/boundary
    CAPABILITY_INCOMPLETE = "capability_incomplete"

    # Phase 3 — promoted dispatch
    TRANSLATOR_NOT_REGISTERED = "translator_not_registered"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    RULE_VIOLATION = "rule_violation"
    PROMOTED_LANE_REQUIRED_FOR_NON_INDIA_BROKER = (
        "promoted_lane_required_for_non_india_broker"
    )

    # Phase 6 — region gating
    OPTION_CHAIN_DISABLED = "option_chain_disabled"
    OPTION_GRAMMAR_NOT_SUPPORTED_IN_REGION = "option_grammar_not_supported_in_region"
    EXPIRY_GRAMMAR_NOT_SUPPORTED_IN_REGION = "expiry_grammar_not_supported_in_region"
    FLOW_TEMPLATE_REGION_UNSUPPORTED = "flow_template_region_unsupported"
    SANDBOX_REGION_UNSUPPORTED = "sandbox_region_unsupported"
    ANALYZER_INDIA_REGION_ONLY = "analyzer_india_region_only"

    # Phase 4 v3 (ADR 0020) — service-layer region gates
    FLOW_TEMPLATES_DISABLED_IN_REGION = "flow_templates_disabled_in_region"
    FLOW_DEFAULT_UNAVAILABLE_IN_REGION = "flow_default_unavailable_in_region"
    OPTION_CHAIN_DISABLED_IN_REGION = "option_chain_disabled_in_region"
    IV_CHART_DISABLED_IN_REGION = "iv_chart_disabled_in_region"
    GEX_DISABLED_IN_REGION = "gex_disabled_in_region"
    OPTION_GREEKS_DISABLED_IN_REGION = "option_greeks_disabled_in_region"
    MULTI_OPTION_DISABLED_IN_REGION = "multi_option_disabled_in_region"
    SYNTHETIC_FUTURE_DISABLED_IN_REGION = "synthetic_future_disabled_in_region"
    STRADDLE_CHART_DISABLED_IN_REGION = "straddle_chart_disabled_in_region"
    VOL_SURFACE_DISABLED_IN_REGION = "vol_surface_disabled_in_region"

    # Phase 2 v4 (ADR 0023) — boundary enforcement + v1 hard-block
    REGION_RESOLUTION_ERROR = "region_resolution_error"
    CONFIGURATION_ERROR = "configuration_error"
    V1_UNAVAILABLE_FOR_NON_INDIA_BROKER = "v1_unavailable_for_non_india_broker"
    LEGACY_FALLBACK_BLOCKED_FOR_NON_INDIA = "legacy_fallback_blocked_for_non_india"
    INSTRUMENT_AMBIGUOUS = "instrument_ambiguous"
    INSTRUMENT_NOT_RESOLVABLE = "instrument_not_resolvable"

    # Phase 5 v4 (ADR 0023) — v2 read-side fail-closed adapters
    PROMOTED_CAPABILITY_UNAVAILABLE = "promoted_capability_unavailable"
    QUOTE_ADAPTER_NOT_REGISTERED = "quote_adapter_not_registered"
    BAR_ADAPTER_NOT_REGISTERED = "bar_adapter_not_registered"
    POSITION_ADAPTER_NOT_REGISTERED = "position_adapter_not_registered"
    BALANCE_ADAPTER_NOT_REGISTERED = "balance_adapter_not_registered"

    # Phase 8 v4 (ADR 0023) — sandbox provider dispatcher
    SANDBOX_PROVIDER_NOT_REGISTERED = "sandbox_provider_not_registered"

    # Phase 9 v4 (ADR 0023) — options provider dispatcher
    OPTIONS_PROVIDER_NOT_REGISTERED = "options_provider_not_registered"

    # Phase 10 v4 (ADR 0023) — screener provider dispatcher
    SCREENER_PROVIDER_NOT_REGISTERED = "screener_provider_not_registered"

    # Phase 1 v5 (ADR 0029) — structured market-context error taxonomy.
    # Net-new error codes promoted-lane callers can branch on. Existing
    # provider-specific *_NOT_REGISTERED codes above remain valid; the
    # umbrella UNSUPPORTED_PROVIDER carries a `feature` field so a
    # generic client can render a single message.
    UNSUPPORTED_REGION = "unsupported_region"
    MISSING_REGION_CONTEXT = "missing_region_context"
    UNSUPPORTED_VENUE = "unsupported_venue"
    MISSING_VENUE_CONTEXT = "missing_venue_context"
    MISSING_CURRENCY_CONTEXT = "missing_currency_context"
    MISSING_INSTRUMENT_IDENTITY = "missing_instrument_identity"
    MISSING_TRANSLATOR = "missing_translator"
    UNSUPPORTED_PROVIDER = "unsupported_provider"
    LEGACY_LANE_BLOCKED = "legacy_lane_blocked"
    ENTITLEMENT_REQUIRED = "entitlement_required"


class FeatureNotAvailableInRegion(DomainError):
    """A feature is gated to a specific region and the active region differs.

    Carries the region code that triggered the rejection plus the
    stable error code for the API surface.
    """

    def __init__(
        self,
        active_region: str | None,
        code: str = ErrorCode.OPTION_CHAIN_DISABLED,
        message: str | None = None,
    ) -> None:
        self.active_region = active_region
        self.code = code
        super().__init__(
            message
            or f"feature {code!r} not available in region {active_region!r}"
        )


class RegionResolutionError(DomainError):
    """The active region cannot be resolved from any source.

    Phase 2 v4 (ADR 0023, invariant 1): missing region context in
    promoted code is a structured error, not a silent India fallback.
    Raised by ``services.feature_gate_service.active_region_code`` when
    the broker has no ``supported_regions`` and no settings default is
    configured AND the caller has not opted into the legacy India
    compatibility path.

    Carries the stable error code ``ErrorCode.REGION_RESOLUTION_ERROR``.
    """

    def __init__(self, message: str | None = None, *, attempted_sources: list[str] | None = None) -> None:
        self.attempted_sources = list(attempted_sources or [])
        if message is None:
            message = (
                "could not resolve active region: no broker capability, "
                "no stored default, and no legacy India fallback opted in"
            )
        super().__init__(message)


class ConfigurationError(DomainError):
    """A required configuration value is missing or invalid.

    Phase 2 v4 (ADR 0023, invariant 5): non-India deployments must set
    ``SESSION_EXPIRY_TIMEZONE`` (and similar) explicitly. Missing
    configuration in a non-India context is an error, not a silent
    India fallback.
    """

    def __init__(self, message: str, *, missing_env: str | None = None) -> None:
        self.missing_env = missing_env
        super().__init__(message)


class SandboxNotAvailableInRegion(FeatureNotAvailableInRegion):
    """Specialization for sandbox/analyzer paths that fail the region gate."""

    def __init__(
        self,
        active_region: str | None,
        message: str | None = None,
    ) -> None:
        super().__init__(
            active_region=active_region,
            code=ErrorCode.SANDBOX_REGION_UNSUPPORTED,
            message=(
                message
                or "sandbox is not available in region "
                f"{active_region!r}; sandbox semantics are India-only "
                "until policy seeds for other regions are added."
            ),
        )


# --- v5 Phase 1 (ADR 0029) structured market-context error classes --- #


class UnsupportedRegion(DomainError):
    """Active region is not supported by the operation/provider/translator.

    Distinguished from `MissingRegionContext`: here the region is known
    and explicitly declared unsupported by something downstream (e.g.,
    a provider rejecting `eu` because it only registered for `india`).
    Carries `region_code` and `code = ErrorCode.UNSUPPORTED_REGION`.
    """

    code = ErrorCode.UNSUPPORTED_REGION

    def __init__(self, region_code: str | None, message: str | None = None) -> None:
        self.region_code = region_code
        super().__init__(message or f"region {region_code!r} is not supported")


class MissingRegionContext(DomainError):
    """The promoted lane needs a region but none could be resolved.

    Distinct from `RegionResolutionError` (which is what
    `feature_gate_service.active_region_code` raises): this one is
    raised by callers that receive `None` from a context lookup and
    need to communicate the gap to the API client.
    Carries `code = ErrorCode.MISSING_REGION_CONTEXT`.
    """

    code = ErrorCode.MISSING_REGION_CONTEXT

    def __init__(self, message: str | None = None, *, attempted_sources: list[str] | None = None) -> None:
        self.attempted_sources = list(attempted_sources or [])
        super().__init__(message or "missing region context for promoted request")


class UnsupportedVenue(DomainError):
    """The supplied venue code is not registered or not allowed here."""

    code = ErrorCode.UNSUPPORTED_VENUE

    def __init__(self, venue_code: str | None, message: str | None = None) -> None:
        self.venue_code = venue_code
        super().__init__(message or f"venue {venue_code!r} is not supported")


class MissingVenueContext(DomainError):
    """A promoted request requires a venue but none was supplied or resolvable."""

    code = ErrorCode.MISSING_VENUE_CONTEXT

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "missing venue context for promoted request")


class MissingCurrencyContext(DomainError):
    """A promoted request requires a currency but none was supplied or resolvable.

    Promoted code MUST NOT default to INR. Account context, venue
    base_currency, instrument currency, or explicit request fields are
    the only valid sources.
    """

    code = ErrorCode.MISSING_CURRENCY_CONTEXT

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "missing currency context for promoted request")


class MissingInstrumentIdentity(DomainError):
    """An instrument lookup failed because no identifier was supplied or resolvable.

    Hybrid identity (D-2): internal UUID, MIC+symbol, or external IDs
    (FIGI/ISIN/CUSIP/SEDOL/OSI). At least one must be supplied.
    """

    code = ErrorCode.MISSING_INSTRUMENT_IDENTITY

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "missing instrument identity for promoted request")


class MissingTranslator(DomainError):
    """No `BrokerTranslator` is registered for the active broker.

    Net-new in v5; alias-style code for `TRANSLATOR_NOT_REGISTERED`
    that promoted-lane v2 admission uses (the existing code stays
    valid for backward compatibility).
    """

    code = ErrorCode.MISSING_TRANSLATOR

    def __init__(self, broker_code: str | None, message: str | None = None) -> None:
        self.broker_code = broker_code
        super().__init__(
            message or f"no translator registered for broker {broker_code!r}"
        )


class UnsupportedProvider(DomainError):
    """No provider for the requested feature is registered for the active region.

    Umbrella class on top of the per-feature *_PROVIDER_NOT_REGISTERED
    codes. Carries `feature: "sandbox" | "options" | "screener" |
    "analyzer" | "flow" | "iv" | "gex" | "straddle" |
    "synthetic_future" | "oi"` so the UI can disable the matching tab.
    """

    code = ErrorCode.UNSUPPORTED_PROVIDER
    FEATURES = (
        "sandbox",
        "options",
        "screener",
        "analyzer",
        "flow",
        "iv",
        "gex",
        "straddle",
        "synthetic_future",
        "oi",
    )

    def __init__(
        self,
        feature: str,
        region_code: str | None = None,
        message: str | None = None,
    ) -> None:
        if feature not in self.FEATURES:
            raise ValueError(
                f"unknown UnsupportedProvider.feature {feature!r}; valid: {self.FEATURES}"
            )
        self.feature = feature
        self.region_code = region_code
        super().__init__(
            message
            or f"no {feature} provider registered for region {region_code!r}"
        )


class LegacyLaneBlocked(DomainError):
    """A non-India request reached an India-only legacy surface and was rejected.

    Companion to `V1_UNAVAILABLE_FOR_NON_INDIA_BROKER`. Used when a
    deeper component (not just the v1 entry guard) detects the
    misroute.
    """

    code = ErrorCode.LEGACY_LANE_BLOCKED

    def __init__(self, surface: str, broker_code: str | None = None, message: str | None = None) -> None:
        self.surface = surface
        self.broker_code = broker_code
        super().__init__(
            message
            or f"legacy lane {surface!r} blocked for broker {broker_code!r}"
        )


class EntitlementRequired(DomainError):
    """Account context lacks an entitlement the request requires.

    Carries `entitlement` (the missing entitlement code) and optional
    `account_id` for diagnostics. Used by Phase 7 promoted-order
    admission to gate options access, fractional/notional, shorting,
    extended-hours, etc.
    """

    code = ErrorCode.ENTITLEMENT_REQUIRED

    def __init__(
        self,
        entitlement: str,
        *,
        account_id: str | None = None,
        message: str | None = None,
    ) -> None:
        self.entitlement = entitlement
        self.account_id = account_id
        super().__init__(
            message
            or f"entitlement {entitlement!r} required (account_id={account_id!r})"
        )


__all__ = [
    "BrokerCapabilityError",
    "CapabilityMismatch",
    "ConfigurationError",
    "DomainError",
    "EntitlementRequired",
    "ErrorCode",
    "FeatureNotAvailableInRegion",
    "InstrumentNotResolvable",
    "LegacyLaneBlocked",
    "MissingCurrencyContext",
    "MissingInstrumentIdentity",
    "MissingRegionContext",
    "MissingTranslator",
    "MissingVenueContext",
    "RegionResolutionError",
    "SandboxNotAvailableInRegion",
    "UnsupportedCapability",
    "UnsupportedProvider",
    "UnsupportedRegion",
    "UnsupportedVenue",
    "ValidationError",
]
