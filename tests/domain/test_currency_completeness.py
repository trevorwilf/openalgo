"""Phase 3 v4 (ADR 0023) — currency completeness audit.

Every region plugin's ``default_currency`` and every venue's
``base_currency`` must resolve to a known
:class:`domain.currency.Currency` member. This guards against region
plugin authors using ad-hoc currency codes that the rest of the
domain layer can't price.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from domain.currency import Currency

REPO_ROOT = Path(__file__).resolve().parents[2]
REGION_ROOT = REPO_ROOT / "market_regions"


def _all_region_plugins() -> list[Path]:
    return sorted(p / "plugin.json" for p in REGION_ROOT.iterdir() if (p / "plugin.json").is_file())


@pytest.mark.parametrize("plugin_path", _all_region_plugins(), ids=lambda p: p.parent.name)
def test_region_default_currency_is_known(plugin_path: Path):
    data = json.loads(plugin_path.read_text(encoding="utf-8"))
    code = data.get("default_currency")
    assert code, f"{plugin_path}: missing default_currency"
    Currency(code)  # raises if unknown


@pytest.mark.parametrize("plugin_path", _all_region_plugins(), ids=lambda p: p.parent.name)
def test_every_venue_base_currency_is_known(plugin_path: Path):
    data = json.loads(plugin_path.read_text(encoding="utf-8"))
    for v in data.get("venues", []):
        code = v.get("base_currency")
        if not code:
            continue
        Currency(code)  # raises if unknown


def test_all_regions_have_first_class_currencies():
    """Confirm USD, EUR, GBP, INR are all present in domain.currency.Currency."""
    for code in ("USD", "EUR", "GBP", "INR"):
        Currency(code)
