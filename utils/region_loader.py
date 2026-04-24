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


def _schema_path() -> str:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(repo_root, "docs", "region-plugin-schema", "plugin.schema.json")


@lru_cache(maxsize=1)
def _load_schema() -> dict[str, Any]:
    path = _schema_path()
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _validate_plugin_json(plugin_data: dict[str, Any]) -> list[str]:
    """Validate a region plugin.json against the JSON schema."""
    try:
        validator = jsonschema.Draft202012Validator(_load_schema())
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
    try:
        return os.path.join(current_app.root_path, region_directory)
    except RuntimeError:
        return os.path.join(os.getcwd(), region_directory)


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


# Test hooks ---------------------------------------------------------------


def _reset_cache_for_tests() -> None:
    global _market_regions, _skipped_regions
    _market_regions = {}
    _skipped_regions = set()
    _load_schema.cache_clear()


def _skipped_regions_for_tests() -> set[str]:
    return set(_skipped_regions)


__all__ = [
    "get_market_region",
    "list_market_regions",
    "load_market_regions",
]
