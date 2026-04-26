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
    """

    def __init__(
        self,
        broker_code: str,
        capability_name: str,
        details: str | None = None,
    ) -> None:
        msg = f"broker {broker_code!r} does not support capability {capability_name!r}"
        if details:
            msg = f"{msg}: {details}"
        super().__init__(msg)
        self.broker_code = broker_code
        self.capability_name = capability_name
        self.details = details


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


__all__ = [
    "BrokerCapabilityError",
    "CapabilityMismatch",
    "ConfigurationError",
    "DomainError",
    "ErrorCode",
    "FeatureNotAvailableInRegion",
    "InstrumentNotResolvable",
    "RegionResolutionError",
    "SandboxNotAvailableInRegion",
    "UnsupportedCapability",
    "ValidationError",
]
