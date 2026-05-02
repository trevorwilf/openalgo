"""Loader for market-region plugin metadata.

This is intentionally parallel to utils.plugin_loader but for market
regions instead of brokers. Startup loads the region catalog once and
keeps it in memory; invalid region plugins are logged and skipped so the
app remains boot-stable.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

import jsonschema
from flask import current_app

from domain.regions import MarketRegion
from utils.logging import get_logger

logger = get_logger(__name__)

_market_regions: dict[str, MarketRegion] = {}
_skipped_regions: set[str] = set()


def _schema_path(version: str = "v2") -> str:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fname = "plugin.schema.json" if version == "v1" else "plugin.v2.schema.json"
    return os.path.join(repo_root, "docs", "region-plugin-schema", fname)


@lru_cache(maxsize=2)
def _load_schema(version: str = "v2") -> dict[str, Any]:
    path = _schema_path(version)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# v2 fields that, if present on a plugin, force v2 validation. v1
# plugins (none of these keys present) are validated against v1 so the
# stricter v2 ``additionalProperties: false`` does not reject them when
# they have legacy fields the v2 schema deliberately renamed.
_V2_INDICATOR_KEYS: tuple[str, ...] = (
    "venues",
    "session_templates",
    "calendar_exceptions",
    "symbol_display",
    "feature_flags",
)


def _detect_schema_version(plugin_data: dict[str, Any]) -> str:
    return "v2" if any(k in plugin_data for k in _V2_INDICATOR_KEYS) else "v1"


def _validate_plugin_json(plugin_data: dict[str, Any]) -> list[str]:
    """Validate a region plugin.json against the appropriate schema.

    v1 plugins (no v2 sections) validate against the original
    ``plugin.schema.json``. Plugins that include any v2 section
    (``venues``, ``session_templates``, ``calendar_exceptions``,
    ``symbol_display``, ``feature_flags``) validate against
    ``plugin.v2.schema.json``. Both schemas share the v1 required
    fields, so v1 plugins continue to validate verbatim.
    """
    version = _detect_schema_version(plugin_data)
    try:
        validator = jsonschema.Draft202012Validator(_load_schema(version))
    except (FileNotFoundError, json.JSONDecodeError, jsonschema.SchemaError) as e:
        logger.exception(f"market region schema unusable ({e}); skipping validation")
        return []

    return [
        f"/{'/'.join(str(p) for p in err.absolute_path)}: {err.message}"
        if err.absolute_path
        else err.message
        for err in sorted(validator.iter_errors(plugin_data), key=lambda e: list(e.path))
    ]


def _region_root_path(region_directory: str) -> str:
    if os.path.isabs(region_directory):
        return region_directory
    # Look in app.root_path first (production), then the current
    # working directory (parity / standalone tests), then the repo
    # root inferred from this module's path. The first candidate
    # whose target directory exists wins so test apps that don't have
    # the project's market_regions/ folder still see the shipped
    # plugins.
    candidates: list[str] = []
    try:
        candidates.append(os.path.join(current_app.root_path, region_directory))
    except RuntimeError:
        pass
    candidates.append(os.path.join(os.getcwd(), region_directory))
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates.append(os.path.join(repo_root, region_directory))
    for path in candidates:
        if os.path.isdir(path):
            return path
    return candidates[0]  # let the caller log/skip cleanly


def _augment_region_defaults(region_name: str, plugin_data: dict[str, Any]) -> dict[str, Any]:
    """Inject default region_code from the directory name when omitted."""
    enriched = dict(plugin_data)
    enriched.setdefault("region_code", region_name)
    return enriched


def _build_region(region_name: str, plugin_data: dict[str, Any]) -> MarketRegion | None:
    try:
        return MarketRegion(**_augment_region_defaults(region_name, plugin_data))
    except Exception as e:
        logger.error(
            "market region plugin for %s could not be coerced into MarketRegion: %s",
            region_name,
            e,
        )
        return None


def load_market_regions(region_directory: str = "market_regions") -> dict[str, MarketRegion]:
    """Scan market_regions/*/plugin.json and cache valid MarketRegion objects."""
    global _market_regions, _skipped_regions

    region_path = _region_root_path(region_directory)
    regions: dict[str, MarketRegion] = {}
    skipped: set[str] = set()

    try:
        entries = sorted(os.listdir(region_path))
    except FileNotFoundError:
        logger.warning("market region directory %r does not exist", region_path)
        _market_regions = {}
        _skipped_regions = set()
        return {}

    for region_name in entries:
        region_dir = os.path.join(region_path, region_name)
        if not os.path.isdir(region_dir) or region_name == "__pycache__":
            continue

        plugin_file = os.path.join(region_dir, "plugin.json")
        if not os.path.exists(plugin_file):
            continue

        try:
            with open(plugin_file, encoding="utf-8") as f:
                plugin_data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Error reading market region plugin for %s: %s", region_name, e)
            skipped.add(region_name)
            continue

        candidate = _augment_region_defaults(region_name, plugin_data)
        errors = _validate_plugin_json(candidate)
        if errors:
            logger.error(
                "market region plugin for %s failed schema validation; skipping. Errors: %s",
                region_name,
                "; ".join(errors),
            )
            skipped.add(region_name)
            continue

        region = _build_region(region_name, plugin_data)
        if region is None:
            skipped.add(region_name)
            continue

        regions[region.region_code] = region

    _market_regions = regions
    _skipped_regions = skipped
    logger.debug(
        "Loaded %d market region plugins (skipped %d)",
        len(regions),
        len(skipped),
    )
    return regions


def get_market_region(region_code: str) -> MarketRegion | None:
    return _market_regions.get(str(region_code).strip().lower())


def list_market_regions() -> dict[str, MarketRegion]:
    return dict(_market_regions)


# ---------------------------------------------------------------------------
# Phase 7 — RegionPlugin instantiation cache.
#
# In addition to the MarketRegion (parsed plugin.json) the loader caches
# one :class:`RegionPlugin` instance per loaded region. Region packages
# that don't ship a ``plugin.py`` continue to work — :func:`get_region_plugin`
# returns ``None`` for them and callers fall through to the legacy
# direct-data-import paths.
# ---------------------------------------------------------------------------

_region_plugins: dict[str, Any] = {}


def get_region_plugin(region_code: str) -> Any | None:
    """Return the cached :class:`domain.region_plugin.RegionPlugin`
    instance for ``region_code``, or ``None`` if the region package
    has no ``plugin.py`` (e.g. EU / UK stubs in this engagement).

    Lazy-imports the region package's ``plugin`` module on first call.
    The cache is cleared by :func:`_reset_cache_for_tests`.
    """
    code = str(region_code).strip().lower()
    if code in _region_plugins:
        return _region_plugins[code]
    if code not in _market_regions:
        return None

    import importlib

    try:
        mod = importlib.import_module(f"market_regions.{code}.plugin")
    except ImportError as exc:
        logger.debug(
            "region %s has no plugin.py module yet (%s); RegionPlugin "
            "Protocol unavailable for this region",
            code, exc,
        )
        _region_plugins[code] = None
        return None

    cls_name_candidates = (
        # Title-case (e.g. India → IndiaRegionPlugin)
        f"{code.capitalize()}RegionPlugin",
        # Upper-case (e.g. us → USRegionPlugin, eu → EURegionPlugin)
        f"{code.upper()}RegionPlugin",
        # Plain alias for region packages that don't want a code-
        # specific class name
        "RegionPlugin",
    )
    cls = None
    for name in cls_name_candidates:
        cls = getattr(mod, name, None)
        if cls is not None:
            break
    if cls is None:
        logger.warning(
            "region %s has plugin.py but no <Code>RegionPlugin / "
            "RegionPlugin class — skipping",
            code,
        )
        _region_plugins[code] = None
        return None
    instance = cls()
    _region_plugins[code] = instance
    return instance


# Test hooks ---------------------------------------------------------------


def _reset_cache_for_tests() -> None:
    global _market_regions, _skipped_regions, _region_plugins
    _market_regions = {}
    _skipped_regions = set()
    _region_plugins = {}
    _load_schema.cache_clear()


def detect_schema_version(plugin_data: dict[str, Any]) -> str:
    """Public test helper exposing the v1/v2 detection."""
    return _detect_schema_version(plugin_data)


def _skipped_regions_for_tests() -> set[str]:
    return set(_skipped_regions)


__all__ = [
    "get_market_region",
    "list_market_regions",
    "load_market_regions",
]
