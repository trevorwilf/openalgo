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

from pydantic import BaseModel, ConfigDict, Field, computed_field

from domain.currency import Currency
from domain.enums import (
    AssetClass,
    MarketFamily,
    OrderType,
    QuantityUnit,
    Session,
    TimeInForce,
)


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
    features: dict[str, bool] = Field(default_factory=dict)

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
        "features",
    }
)


def infer_capabilities_from_legacy(
    plugin_data: dict[str, Any], broker_code: str
) -> dict[str, Any]:
    """Build a BrokerCapabilities-shaped dict from legacy plugin.json fields.

    Rules:
    * `broker_type="IN_stock"` → Indian defaults
    * `broker_type="crypto"` → crypto defaults
    * unknown `broker_type` → minimal skeleton, caller logs a warning
    * Any explicit new field in plugin.json wins over the inferred default
      (no merging — explicit fully replaces).
    * `supported_exchanges` from legacy becomes `supported_venue_codes`.
    """
    broker_type = str(plugin_data.get("broker_type", "IN_stock")).strip()
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


__all__ = ["BrokerCapabilities", "infer_capabilities_from_legacy"]
