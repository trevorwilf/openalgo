"""BrokerCapabilities — a rich description of what a broker can do.

Extends the old plugin.json trio (`broker_type`, `supported_exchanges`,
`leverage_config`) into a model the backend and frontend can both
query for specific behavior: which order types? which TIFs? which
quantity units? fractional? extended hours? analyzer?

Legacy compatibility is preserved via pydantic v2 computed fields so
that serialized output always includes the three legacy keys that the
current frontend reads.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from domain.currency import Currency
from domain.enums import (
    AssetClass,
    AuthMode,
    ComboType,
    MarketFamily,
    OrderType,
    QuantityUnit,
    Session,
    StreamTransport,
    TimeInForce,
)
from domain.errors import BrokerCapabilityError
from utils.feature_flags import is_enabled
from utils.logging import get_logger

logger = get_logger(__name__)


# Required explicit fields for plugins whose `supported_regions`
# excludes "india". Phase 1 fail-closed inference requires these — no
# silent IN_stock/INR defaults for foreign brokers.
_REQUIRED_EXPLICIT_FIELDS_FOR_NON_INDIA: tuple[str, ...] = (
    "broker_type",
    "market_families",
    "default_currency",
    "base_currency",
)


_MARKET_FAMILY_REGION_MAP: dict[MarketFamily, str] = {
    MarketFamily.IN_STOCK: "india",
    MarketFamily.US_STOCK: "us",
    MarketFamily.EU_STOCK: "eu",
    MarketFamily.UK_STOCK: "uk",
}


def infer_supported_regions_from_market_families(
    families: list[MarketFamily | str],
) -> list[str]:
    """Infer market-region codes from market families.

    This keeps broker plugins backward-compatible: older plugin.json
    files that only declare ``market_families`` still gain a useful
    region surface for the new market-region framework.

    Only families with a clear regional mapping are inferred here. More
    global families (CRYPTO / FX / FUTURES / COMMODITY / OTHER) are
    intentionally left unmapped and should declare ``supported_regions``
    explicitly if needed.
    """
    regions: list[str] = []
    for family in families:
        try:
            key = family if isinstance(family, MarketFamily) else MarketFamily(str(family))
        except ValueError:
            continue
        region = _MARKET_FAMILY_REGION_MAP.get(key)
        if region and region not in regions:
            regions.append(region)
    return regions


class ProductCapabilities(BaseModel):
    """Per-product capability surface (Phase 8).

    Webull's docs make explicit that capabilities differ across
    stocks / options / futures / crypto. This per-product matrix lets
    a broker plugin declare different supported_order_types,
    quantity_units, sessions, and combo types for each product.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    asset_class: AssetClass
    supported_order_types: list[OrderType] = Field(default_factory=list)
    supported_time_in_force: list[TimeInForce] = Field(default_factory=list)
    supported_sessions: list[Session] = Field(default_factory=list)
    supported_quantity_units: list[QuantityUnit] = Field(default_factory=list)
    supports_fractional: bool = False
    supports_notional: bool = False
    supports_short: bool = False
    supports_combo_types: list[ComboType] = Field(default_factory=list)
    streaming: dict[str, Any] = Field(default_factory=dict)


class BrokerCapabilities(BaseModel):
    """What a single broker adapter can and cannot do.

    Frozen + `extra="forbid"`: any unknown field in the plugin.json
    turns into an explicit ValidationError at startup, which is the
    behavior Phase 1b's schema validation wants.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    broker_code: str
    broker_display_name: str
    market_families: list[MarketFamily]
    supported_regions: list[str] = Field(default_factory=list)
    supported_venue_codes: list[str]
    supported_asset_classes: list[AssetClass]
    supported_order_types: list[OrderType]
    supported_time_in_force: list[TimeInForce]
    supported_sessions: list[Session]
    supported_quantity_units: list[QuantityUnit]
    trading_currencies: list[Currency]
    base_currency: Currency | None = None
    leverage_config: bool = False
    supports_fractional: bool = False
    supports_notional_orders: bool = False
    supports_extended_hours: bool = False
    supports_short_selling: bool = False
    supports_analyzer: bool = False
    # v5 Phase 4 — does the broker plugin advertise sandbox/paper trading?
    # India brokers default True (preserves the existing analyzer/
    # sandbox surfaces). Non-India brokers default False; an explicit
    # plugin.json declaration is required to enable.
    supports_sandbox: bool = False
    features: dict[str, bool] = Field(default_factory=dict)
    # Phase 8 — Schwab/Webull readiness fields. All optional; legacy
    # plugins that don't declare them get sensible defaults.
    products: list[ProductCapabilities] = Field(default_factory=list)
    auth_modes: list[AuthMode] = Field(default_factory=list)
    streaming_transports: list[StreamTransport] = Field(default_factory=list)
    supports_account_hashes: bool = False
    supports_subaccounts: bool = False
    # Phase 4 — broker-declared master-contract refresh policy. Schema:
    # {
    #   "timezone": "Asia/Kolkata",   # IANA tz to anchor `cutoff_local`
    #   "cutoff_local": "08:00",      # daily refresh boundary
    #   "frequency": "daily",         # "daily" | "never"
    #   "skip_if_24x7": false
    # }
    # When None (legacy India plugins), auth_utils retains the existing
    # 08:00 IST behavior for backward compat.
    master_contract_refresh_policy: dict[str, Any] | None = None

    @model_validator(mode="before")
    @classmethod
    def _default_supported_regions(cls, data: Any) -> Any:
        """Backfill supported_regions from market_families when omitted."""
        if not isinstance(data, dict):
            return data
        if data.get("supported_regions"):
            return data
        market_families = list(data.get("market_families", []))
        if not market_families:
            return data
        enriched = dict(data)
        enriched["supported_regions"] = infer_supported_regions_from_market_families(
            market_families
        )
        return enriched

    # ---- Legacy-compat computed fields ----------------------------------
    # These appear in `model_dump()` so serialized output always carries
    # the keys today's frontend expects.

    @computed_field  # type: ignore[prop-decorator]
    @property
    def broker_name(self) -> str:
        """Alias the frontend reads — same as broker_code."""
        return self.broker_code

    @computed_field  # type: ignore[prop-decorator]
    @property
    def broker_type(self) -> str:
        """Derive the old `broker_type` string from market_families.

        Rules:
        * IN_STOCK present → "IN_stock" (original Indian family wins)
        * only CRYPTO      → "crypto"
        * otherwise        → first family's name lowercased
        """
        families = self.market_families
        if MarketFamily.IN_STOCK in families:
            return "IN_stock"
        if families == [MarketFamily.CRYPTO]:
            return "crypto"
        if families:
            return families[0].value.lower()
        return "unknown"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def supported_exchanges(self) -> list[str]:
        """Alias the frontend reads — same contents as supported_venue_codes."""
        return list(self.supported_venue_codes)

    def has_capability(self, name: str) -> bool:
        """Bool feature check tolerant of both first-class flags and `features[]`.

        First-class capability flags (e.g. supports_fractional) take
        precedence; otherwise fall through to `self.features`.
        """
        first_class = getattr(self, name, None)
        if isinstance(first_class, bool):
            return first_class
        return bool(self.features.get(name, False))


# -------- Legacy inference ----------------------------------------------


def _common_defaults() -> dict[str, Any]:
    """Shared skeleton for every inferred capability set."""
    return {
        "features": {},
        "leverage_config": False,
        "supports_fractional": False,
        "supports_notional_orders": False,
        "supports_extended_hours": False,
        "supports_short_selling": False,
        "supports_analyzer": False,
        # v5 Phase 4 — sandbox is opt-in for non-India brokers.
        "supports_sandbox": False,
    }


def _indian_defaults() -> dict[str, Any]:
    """Defaults for brokers declaring broker_type='IN_stock'."""
    base = _common_defaults()
    base.update(
        {
            "market_families": [MarketFamily.IN_STOCK],
            "supported_asset_classes": [
                AssetClass.EQUITY,
                AssetClass.FUTURE,
                AssetClass.OPTION,
                AssetClass.INDEX,
                AssetClass.ETF,
            ],
            "supported_order_types": [
                OrderType.MARKET,
                OrderType.LIMIT,
                OrderType.STOP,
                OrderType.STOP_LIMIT,
            ],
            "supported_time_in_force": [TimeInForce.DAY],
            "supported_sessions": [Session.REGULAR],
            "supported_quantity_units": [QuantityUnit.WHOLE, QuantityUnit.LOTS],
            "trading_currencies": [Currency.INR],
            "base_currency": Currency.INR,
            "supports_analyzer": True,
            # v5 Phase 4 — India brokers historically had sandbox enabled.
            "supports_sandbox": True,
        }
    )
    return base


def _crypto_defaults() -> dict[str, Any]:
    """Defaults for brokers declaring broker_type='crypto'."""
    base = _common_defaults()
    base.update(
        {
            "market_families": [MarketFamily.CRYPTO],
            "supported_asset_classes": [
                AssetClass.SPOT,
                AssetClass.PERPETUAL,
                AssetClass.FUTURE,
                AssetClass.OPTION,
            ],
            "supported_order_types": [
                OrderType.MARKET,
                OrderType.LIMIT,
                OrderType.STOP,
                OrderType.STOP_LIMIT,
                OrderType.TRAILING_STOP,
            ],
            "supported_time_in_force": [
                TimeInForce.DAY,
                TimeInForce.GTC,
                TimeInForce.IOC,
                TimeInForce.FOK,
            ],
            "supported_sessions": [Session.ALL_DAY],
            "supported_quantity_units": [QuantityUnit.FRACTIONAL, QuantityUnit.CONTRACTS],
            "trading_currencies": [Currency.USDT, Currency.USDC, Currency.USD],
            "base_currency": Currency.USDT,
            "supports_fractional": True,
            "supports_analyzer": False,
        }
    )
    return base


# Fields that plugin.json can provide explicitly and that should override
# the inferred defaults. Excludes `broker_code` / `broker_display_name`
# because those are computed from the filesystem and plugin-metadata fields.
_EXPLICIT_OVERRIDE_KEYS: frozenset[str] = frozenset(
    {
        "market_families",
        "supported_regions",
        "supported_venue_codes",
        "supported_asset_classes",
        "supported_order_types",
        "supported_time_in_force",
        "supported_sessions",
        "supported_quantity_units",
        "trading_currencies",
        "base_currency",
        "leverage_config",
        "supports_fractional",
        "supports_notional_orders",
        "supports_extended_hours",
        "supports_short_selling",
        "supports_analyzer",
        "supports_sandbox",
        "features",
        "master_contract_refresh_policy",
        # Phase 8 — Schwab/Webull readiness fields
        "products",
        "auth_modes",
        "streaming_transports",
        "supports_account_hashes",
        "supports_subaccounts",
    }
)


def _is_legacy_india_plugin(plugin_data: dict[str, Any]) -> bool:
    """A plugin is treated as legacy India for inference purposes when
    it omits ``supported_regions`` entirely or declares only ``india``.

    The legacy 24+ Indian broker plugins do not declare
    ``supported_regions`` at all — they get IN_stock inference. A new
    plugin that declares ``supported_regions=["us"]`` (or anything that
    excludes "india") must provide explicit metadata; the legacy
    inference is intentionally unavailable for it.
    """
    if "supported_regions" not in plugin_data:
        return True
    regions = plugin_data.get("supported_regions") or []
    if not isinstance(regions, list):
        return True  # malformed — let pydantic complain downstream
    normalized = {str(r).strip().lower() for r in regions}
    return not normalized or normalized == {"india"}


def _check_explicit_fields_for_non_india(
    plugin_data: dict[str, Any], broker_code: str
) -> None:
    """Fail closed when a non-India plugin omits required explicit fields.

    See ADR 0006. Behavior is gated by the
    ``STRICT_CAPABILITY_INFERENCE`` flag (default on). When the flag
    is off, the missing fields are logged as a warning and inference
    proceeds — this is the rollback escape hatch.
    """
    missing = [
        field
        for field in _REQUIRED_EXPLICIT_FIELDS_FOR_NON_INDIA
        if field not in plugin_data or plugin_data.get(field) in (None, "", [], {})
    ]
    if not missing:
        return

    if is_enabled("STRICT_CAPABILITY_INFERENCE", default=True):
        raise BrokerCapabilityError(broker_code, missing)
    logger.warning(
        "broker %r: STRICT_CAPABILITY_INFERENCE disabled — proceeding with "
        "incomplete metadata. Missing: %s",
        broker_code,
        ", ".join(missing),
    )


def infer_capabilities_from_legacy(
    plugin_data: dict[str, Any], broker_code: str
) -> dict[str, Any]:
    """Build a BrokerCapabilities-shaped dict from legacy plugin.json fields.

    Rules:
    * Legacy India plugins (no ``supported_regions`` or
      ``supported_regions=["india"]``):
        - ``broker_type="IN_stock"`` → Indian defaults
        - ``broker_type="crypto"`` → crypto defaults
        - unknown ``broker_type`` → minimal skeleton
    * Plugins whose ``supported_regions`` excludes "india":
        - REQUIRE ``broker_type``, ``market_families``,
          ``default_currency``, ``base_currency``. Missing fields raise
          ``BrokerCapabilityError`` (gated by
          ``STRICT_CAPABILITY_INFERENCE`` env flag, default on).
        - No silent IN_stock/INR defaults are applied.
    * Any explicit new field in plugin.json wins over the inferred default
      (no merging — explicit fully replaces).
    * ``supported_exchanges`` from legacy becomes ``supported_venue_codes``.
    """
    is_legacy_india = _is_legacy_india_plugin(plugin_data)
    if not is_legacy_india:
        _check_explicit_fields_for_non_india(plugin_data, broker_code)

    if is_legacy_india:
        broker_type = str(plugin_data.get("broker_type", "IN_stock")).strip()
    else:
        broker_type = str(plugin_data.get("broker_type", "")).strip()
    supported_exchanges = list(plugin_data.get("supported_exchanges", []))
    display_name = str(
        plugin_data.get("Plugin Name")
        or plugin_data.get("broker_display_name")
        or broker_code
    )

    if broker_type == "IN_stock":
        result = _indian_defaults()
    elif broker_type == "crypto":
        result = _crypto_defaults()
    else:
        result = _common_defaults()
        result.update(
            {
                "market_families": [MarketFamily.OTHER],
                "supported_asset_classes": [AssetClass.OTHER],
                "supported_order_types": [OrderType.MARKET, OrderType.LIMIT],
                "supported_time_in_force": [TimeInForce.DAY],
                "supported_sessions": [Session.REGULAR],
                "supported_quantity_units": [QuantityUnit.WHOLE],
                "trading_currencies": [],
                "base_currency": None,
            }
        )

    result["broker_code"] = broker_code
    result["broker_display_name"] = display_name
    result["supported_venue_codes"] = supported_exchanges
    # Legacy `leverage_config` is the only legacy flag that's also a
    # first-class field on the new shape; pull it through by default.
    if "leverage_config" in plugin_data:
        result["leverage_config"] = bool(plugin_data["leverage_config"])

    # Explicit new fields take precedence (no merging). Preserve the
    # literal value the plugin author wrote.
    for key in _EXPLICIT_OVERRIDE_KEYS:
        if key in plugin_data:
            result[key] = plugin_data[key]

    return result


__all__ = [
    "BrokerCapabilities",
    "infer_capabilities_from_legacy",
    "infer_supported_regions_from_market_families",
]
