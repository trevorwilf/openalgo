# utils/plugin_loader.py
"""Plugin loader for broker modules and their capability metadata.

Phase 1b of the market-agnostic refactor replaced the shallow three-field
capability dict with a rich `BrokerCapabilities` pydantic model. The
module-level entry points are unchanged so every existing caller keeps
working:

    load_broker_capabilities(broker_directory="broker")
    get_broker_capabilities(broker_name)
    load_broker_auth_functions(broker_directory="broker")

Internally the cache now holds `BrokerCapabilities` instances. Callers
that serialize the value get the same legacy keys they used to
(`broker_name`, `broker_type`, `supported_exchanges`, `leverage_config`)
plus the richer capability surface, via pydantic computed fields.

Startup validation uses the JSON Schema at
`docs/plugin-schema/plugin.schema.json`. Invalid plugins are logged and
skipped; app startup is never blocked.
"""

from __future__ import annotations

import importlib
import json
import os
from functools import lru_cache
from typing import Any

import jsonschema
from flask import current_app

from domain.capabilities import BrokerCapabilities, infer_capabilities_from_legacy
from domain.errors import BrokerCapabilityError
from utils.feature_flags import is_enabled
from utils.logging import get_logger

logger = get_logger(__name__)


# Phase 3 capability completeness fields (ADR 0008). When a plugin's
# `supported_regions` excludes "india", these MUST be present in
# plugin.json. Phase 1's narrower check on the four currency/family
# basics is a subset; this list extends it to the order-shape primitives
# the promoted lane reads at dispatch time.
#
# Phase 1 of v3 (ADR 0017) extends the list with
# ``master_contract_refresh_policy`` and ``auth_modes`` so promoted
# brokers must declare both up front. The first lets the UI render a
# correct refresh time without inferring "08:00 IST"; the second
# tells the operator at a glance whether the plugin needs HMAC
# signing or OAuth.
_REQUIRED_NON_INDIA_PLUGIN_FIELDS: tuple[str, ...] = (
    "broker_type",
    "market_families",
    "default_currency",
    "base_currency",
    "supported_regions",
    "supported_order_types",
    "supported_time_in_force",
    "supported_quantity_units",
    "supported_sessions",
    "master_contract_refresh_policy",
    "auth_modes",
)


def _is_legacy_india_plugin(plugin_data: dict[str, Any]) -> bool:
    if "supported_regions" not in plugin_data:
        return True
    regions = plugin_data.get("supported_regions") or []
    if not isinstance(regions, list):
        return True
    normalized = {str(r).strip().lower() for r in regions}
    return not normalized or normalized == {"india"}


def _check_plugin_completeness(
    broker_name: str, plugin_data: dict[str, Any]
) -> list[str]:
    """Return the list of required-but-missing fields for non-India plugins.

    Returns ``[]`` for legacy India plugins (no completeness check) and
    for non-India plugins that have all required fields.
    """
    if _is_legacy_india_plugin(plugin_data):
        return []
    return [
        f
        for f in _REQUIRED_NON_INDIA_PLUGIN_FIELDS
        if f not in plugin_data or plugin_data.get(f) in (None, "", [], {})
    ]

# In-memory cache for broker capabilities (populated once at startup)
_broker_capabilities: dict[str, BrokerCapabilities] = {}

# Brokers whose plugin.json failed validation — their auth functions
# must also be unavailable.
_skipped_brokers: set[str] = set()


# Phase 4 v4 (ADR 0025) — strict-mode validator for promoted plugins.
# A "promoted" plugin is one whose ``supported_regions`` excludes
# ``"india"`` OR whose plugin.json sets ``promoted: true`` explicitly.
# For these plugins, ALL keys must appear in the known set below
# (declared union of v4 required fields, JSON Schema properties, and
# explicit operational metadata). Unknown keys are validation errors.
#
# Legacy India plugins (``supported_regions`` includes ``"india"`` or
# absent) keep the existing non-strict mode for backward compatibility.

# v4 required promoted fields — every promoted plugin MUST declare
# all of these.
_V4_PROMOTED_REQUIRED_FIELDS: tuple[str, ...] = (
    "broker_code",
    "broker_display_name",
    "broker_type",
    "supported_regions",
    "market_families",
    "supported_venue_codes",
    "supported_asset_classes",
    "supported_order_types",
    "supported_time_in_force",
    "supported_sessions",
    "supported_quantity_units",
    "trading_currencies",
    "default_currency",
    "base_currency",
    "auth_modes",
    "account_context_supports",
    "master_contract_refresh_policy",
)

# WordPress-style header fields — non-operational, allowed.
_WP_HEADER_FIELDS: frozenset[str] = frozenset({
    "Plugin Name",
    "Plugin URI",
    "Description",
    "Version",
    "Author",
    "Author URI",
})

# Optional operational metadata explicitly accepted in promoted mode.
# Adding a new key here is the deliberate way to extend the strict
# schema. Keep it short — anything that affects routing or behavior
# should map to a typed BrokerCapabilities field.
_OPTIONAL_PROMOTED_FIELDS: frozenset[str] = frozenset({
    # legacy compat (still accepted on promoted plugins)
    "supported_exchanges",
    "leverage_config",
    # capability surface
    "supports_fractional",
    "supports_notional_orders",
    "supports_extended_hours",
    "supports_short_selling",
    "supports_analyzer",
    "supports_sandbox",
    "supports_options",
    "options_provider_region",
    "supports_screener_providers",
    "supports_combo_types",
    "streaming",
    "features",
    # explicit promotion marker
    "promoted",
    # documentation surface
    "documentation_url",
    "display",
    # v7 Phase 2 (T-04) — broker-declared default venue + product
    # for the v1 compat bridge. Optional; the bridge falls back to
    # ``supported_venue_codes[0]`` for venue and raises
    # ``BrokerCapabilityError`` for product.
    "default_venue_code",
    "default_product_code",
})


def _strict_known_fields() -> frozenset[str]:
    return (
        _WP_HEADER_FIELDS
        | _OPTIONAL_PROMOTED_FIELDS
        | frozenset(_V4_PROMOTED_REQUIRED_FIELDS)
    )


def _is_promoted_plugin(plugin_data: dict[str, Any]) -> bool:
    """Promoted = explicit ``promoted: true`` OR
    ``supported_regions`` excludes ``"india"``."""
    if plugin_data.get("promoted") is True:
        return True
    regions = plugin_data.get("supported_regions") or []
    if not isinstance(regions, list) or not regions:
        return False
    normalized = {str(r).strip().lower() for r in regions}
    return "india" not in normalized


def _strict_promoted_plugin_errors(
    broker_name: str, plugin_data: dict[str, Any]
) -> list[str]:
    """Return the list of strict-mode violations for a promoted plugin.

    * Missing required v4 fields.
    * Unknown keys (additionalProperties:false equivalent).
    """
    if not _is_promoted_plugin(plugin_data):
        return []
    errors: list[str] = []
    missing = [
        f
        for f in _V4_PROMOTED_REQUIRED_FIELDS
        if f not in plugin_data or plugin_data.get(f) in (None, "", [], {})
    ]
    for f in missing:
        errors.append(f"missing required promoted field {f!r}")
    known = _strict_known_fields()
    for key in plugin_data:
        if key not in known:
            errors.append(
                f"unknown promoted plugin field {key!r} (strict mode "
                "rejects additional properties; see ADR 0025)"
            )
    return errors


# Plugin diagnostics — populated by load_broker_capabilities. Keyed
# on broker_name; values describe loaded / loaded-with-warnings /
# skipped state plus the missing/unknown fields. Operator inspects via
# ``/api/v2/plugins/diagnostics``.
_plugin_diagnostics: dict[str, dict[str, Any]] = {}


def get_plugin_diagnostics() -> dict[str, dict[str, Any]]:
    """Return the per-broker plugin diagnostics dict produced by the
    last call to :func:`load_broker_capabilities`. Used by
    ``/api/v2/plugins/diagnostics`` and operator tools.
    """
    # Return a shallow copy so callers cannot mutate the cache.
    return {k: dict(v) for k, v in _plugin_diagnostics.items()}


def _schema_path() -> str:
    """Absolute path to the plugin.schema.json file."""
    # utils/plugin_loader.py -> repo root -> docs/plugin-schema/plugin.schema.json
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(repo_root, "docs", "plugin-schema", "plugin.schema.json")


@lru_cache(maxsize=1)
def _load_schema() -> dict[str, Any]:
    """Load the plugin.json JSON Schema once and cache it."""
    path = _schema_path()
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _validate_plugin_json(plugin_data: dict[str, Any]) -> list[str]:
    """Validate plugin.json contents against the schema.

    Returns a list of human-readable error messages. Empty list means
    the file is valid. Never raises — invalid plugins are skipped by
    the caller, not crashed on.
    """
    try:
        validator = jsonschema.Draft202012Validator(_load_schema())
    except (FileNotFoundError, json.JSONDecodeError, jsonschema.SchemaError) as e:
        # Schema file itself is broken — log loudly and accept everything.
        # Better to keep brokers loading than to take down the app because
        # of a dev-time schema typo.
        logger.exception(f"plugin schema unusable ({e}); skipping validation")
        return []

    return [
        f"/{'/'.join(str(p) for p in err.absolute_path)}: {err.message}"
        if err.absolute_path
        else err.message
        for err in sorted(validator.iter_errors(plugin_data), key=lambda e: list(e.path))
    ]


def _broker_root_path(broker_directory: str) -> str:
    """Resolve `broker_directory` against the Flask app root.

    Absolute paths pass through unchanged. Relative paths resolve
    against `current_app.root_path` when a Flask app context is
    available, otherwise against the current working directory (tests
    that drive the loader directly typically chdir into a tmp tree).
    """
    if os.path.isabs(broker_directory):
        return broker_directory
    try:
        return os.path.join(current_app.root_path, broker_directory)
    except RuntimeError:
        return os.path.join(os.getcwd(), broker_directory)


def _build_capabilities(
    broker_name: str, plugin_data: dict[str, Any]
) -> BrokerCapabilities | None:
    """Produce a BrokerCapabilities from a plugin.json dict.

    Returns None if construction fails — caller logs and skips the
    broker but does not re-raise.
    """
    inferred = infer_capabilities_from_legacy(plugin_data, broker_name)
    try:
        return BrokerCapabilities(**inferred)
    except Exception as e:  # pydantic ValidationError or otherwise
        logger.error(
            f"plugin.json for {broker_name} could not be coerced into "
            f"BrokerCapabilities: {e}"
        )
        return None


def load_broker_capabilities(
    broker_directory: str = "broker",
) -> dict[str, BrokerCapabilities]:
    """Scan broker/*/plugin.json at startup and cache rich capabilities.

    Behavior:
    * Each broker directory that has a plugin.json with either a
      legacy ``supported_exchanges`` field or the richer
      ``supported_venue_codes`` field is considered a candidate.
    * The plugin.json is validated against the Phase 1b JSON Schema.
      If validation fails, the broker is logged and skipped — the app
      must remain boot-stable.
    * Valid plugin.json contents are merged with legacy-family defaults
      (see ``domain.capabilities.infer_capabilities_from_legacy``) to
      produce a ``BrokerCapabilities`` instance.
    * The cache is returned as a dict keyed by broker_name so existing
      callers that iterate ``capabilities.items()`` keep working.
    """
    global _broker_capabilities, _skipped_brokers, _plugin_diagnostics

    broker_path = _broker_root_path(broker_directory)
    capabilities: dict[str, BrokerCapabilities] = {}
    skipped: set[str] = set()
    diagnostics: dict[str, dict[str, Any]] = {}

    try:
        entries = sorted(os.listdir(broker_path))
    except FileNotFoundError:
        logger.warning(f"broker directory {broker_path!r} does not exist")
        _broker_capabilities = {}
        _skipped_brokers = set()
        return {}

    for broker_name in entries:
        broker_dir = os.path.join(broker_path, broker_name)
        if not os.path.isdir(broker_dir) or broker_name == "__pycache__":
            continue

        plugin_file = os.path.join(broker_dir, "plugin.json")
        if not os.path.exists(plugin_file):
            continue

        try:
            with open(plugin_file, encoding="utf-8") as f:
                plugin_data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Error reading plugin.json for {broker_name}: {e}")
            skipped.add(broker_name)
            continue

        # Keep a light discovery gate: only brokers that declare either the
        # legacy venue list or the richer supported_venue_codes are considered
        # usable. Skipping here (rather than failing) matches existing behavior.
        if (
            "supported_exchanges" not in plugin_data
            and "supported_venue_codes" not in plugin_data
        ):
            continue

        errors = _validate_plugin_json(plugin_data)
        if errors:
            logger.error(
                f"plugin.json for {broker_name} failed schema validation; "
                f"skipping. Errors: {'; '.join(errors)}"
            )
            skipped.add(broker_name)
            diagnostics[broker_name] = {
                "state": "skipped",
                "promoted": _is_promoted_plugin(plugin_data),
                "reason": "json_schema_validation_failed",
                "errors": errors,
            }
            continue

        # Phase 3 completeness gate. Non-India plugins must declare the
        # full required-fields set or be skipped (or warned-only when
        # STRICT_CAPABILITY_INFERENCE is off).
        missing = _check_plugin_completeness(broker_name, plugin_data)
        if missing:
            if is_enabled("STRICT_CAPABILITY_INFERENCE", default=True):
                logger.error(
                    "plugin.json for %s is incomplete (non-India plugin "
                    "missing required fields: %s); skipping. See ADR 0008.",
                    broker_name,
                    ", ".join(missing),
                )
                skipped.add(broker_name)
                diagnostics[broker_name] = {
                    "state": "skipped",
                    "promoted": _is_promoted_plugin(plugin_data),
                    "reason": "completeness_check_failed",
                    "missing_fields": missing,
                }
                continue
            logger.warning(
                "plugin.json for %s is incomplete (missing %s) but "
                "STRICT_CAPABILITY_INFERENCE is off; loading anyway.",
                broker_name,
                ", ".join(missing),
            )

        # Phase 4 v4 (ADR 0025) — strict-mode validator for promoted
        # plugins. Promoted plugins must have all v4 required fields
        # AND no unknown keys (additionalProperties:false equivalent).
        # Legacy India plugins keep non-strict mode for back-compat.
        strict_errors = _strict_promoted_plugin_errors(broker_name, plugin_data)
        if strict_errors:
            if is_enabled("STRICT_CAPABILITY_INFERENCE", default=True):
                logger.error(
                    "plugin.json for %s failed promoted-plugin strict mode; "
                    "skipping. Errors: %s. See ADR 0025.",
                    broker_name,
                    "; ".join(strict_errors),
                )
                skipped.add(broker_name)
                diagnostics[broker_name] = {
                    "state": "skipped",
                    "promoted": True,
                    "reason": "strict_mode_failed",
                    "errors": strict_errors,
                }
                continue
            logger.warning(
                "plugin.json for %s failed strict mode but "
                "STRICT_CAPABILITY_INFERENCE is off; loading with warnings: %s",
                broker_name,
                "; ".join(strict_errors),
            )

        try:
            caps = _build_capabilities(broker_name, plugin_data)
        except BrokerCapabilityError as e:
            logger.error("plugin.json for %s rejected by capability check: %s", broker_name, e)
            skipped.add(broker_name)
            diagnostics[broker_name] = {
                "state": "skipped",
                "promoted": _is_promoted_plugin(plugin_data),
                "reason": "capability_check_failed",
                "error": str(e),
            }
            continue
        if caps is None:
            skipped.add(broker_name)
            diagnostics[broker_name] = {
                "state": "skipped",
                "promoted": _is_promoted_plugin(plugin_data),
                "reason": "capabilities_build_failed",
            }
            continue

        capabilities[broker_name] = caps
        diagnostics[broker_name] = {
            "state": "loaded",
            "promoted": _is_promoted_plugin(plugin_data),
            "broker_type": plugin_data.get("broker_type"),
            "supported_regions": plugin_data.get("supported_regions") or [],
        }

    _broker_capabilities = capabilities
    _skipped_brokers = skipped
    _plugin_diagnostics = diagnostics
    promoted_loaded = sum(1 for d in diagnostics.values()
                          if d.get("state") == "loaded" and d.get("promoted"))
    logger.info(
        "plugin loader: loaded=%d (promoted=%d), skipped=%d",
        len(capabilities),
        promoted_loaded,
        len(skipped),
    )
    return capabilities


def get_broker_capabilities(broker_name: str) -> BrokerCapabilities | None:
    """Return cached capabilities for a specific broker, or None."""
    return _broker_capabilities.get(broker_name)


def load_broker_auth_functions(broker_directory: str = "broker") -> "_LazyBrokerAuthDict":
    """Return a lazy dict that imports broker auth modules on first access.

    A broker whose plugin.json failed validation is filtered out of the
    discoverable set — its auth function is never loaded.
    """
    broker_path = _broker_root_path(broker_directory)
    broker_names = {
        d
        for d in os.listdir(broker_path)
        if os.path.isdir(os.path.join(broker_path, d)) and d != "__pycache__"
    }
    # Remove brokers that were skipped during capability validation.
    broker_names -= _skipped_brokers
    return _LazyBrokerAuthDict(broker_names, broker_directory)


class _LazyBrokerAuthDict(dict):
    """Dict-like object that lazily imports broker auth modules on access."""

    def __init__(self, broker_names: set[str], broker_directory: str) -> None:
        super().__init__()
        self._broker_names = broker_names
        self._broker_directory = broker_directory

    def get(self, key, default=None):
        if key not in self and isinstance(key, str) and key.endswith("_auth"):
            broker_name = key[: -len("_auth")]
            if broker_name in self._broker_names:
                self._load_broker(broker_name)
        return super().get(key, default)

    def __getitem__(self, key):
        if key not in self and isinstance(key, str) and key.endswith("_auth"):
            broker_name = key[: -len("_auth")]
            if broker_name in self._broker_names:
                self._load_broker(broker_name)
        return super().__getitem__(key)

    def __contains__(self, key):
        if not super().__contains__(key) and isinstance(key, str) and key.endswith("_auth"):
            broker_name = key[: -len("_auth")]
            if broker_name in self._broker_names:
                self._load_broker(broker_name)
        return super().__contains__(key)

    def _load_broker(self, broker_name: str) -> None:
        """Import a single broker's auth module on demand."""
        key = f"{broker_name}_auth"
        if super().__contains__(key):
            return
        try:
            module_name = f"{self._broker_directory}.{broker_name}.api.auth_api"
            auth_module = importlib.import_module(module_name)
            auth_function = getattr(auth_module, "authenticate_broker", None)
            if auth_function:
                self[key] = auth_function
            else:
                logger.error(f"authenticate_broker not found in {module_name}")
        except ImportError as e:
            logger.error(f"Failed to import broker plugin {broker_name}: {e}")
        except AttributeError as e:
            logger.error(
                f"Authentication function not found in broker plugin {broker_name}: {e}"
            )


# Test hooks — these are not part of the public API but let tests reset
# module state between runs without resorting to reload().
def _reset_cache_for_tests() -> None:
    global _broker_capabilities, _skipped_brokers
    _broker_capabilities = {}
    _skipped_brokers = set()
    _load_schema.cache_clear()


def _skipped_brokers_for_tests() -> set[str]:
    return set(_skipped_brokers)
