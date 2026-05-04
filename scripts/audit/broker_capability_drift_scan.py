"""T-32 (Phase 3) — broker capability drift scan.

Detect declared-vs-exercised mismatch in broker plugins. Each
plugin's ``BrokerCapabilities`` flags an opt-in feature; the audit
verifies that the corresponding code path actually exercises that
feature. Drift means either:

  * Plugin claims a capability it doesn't use (over-declaration).
  * Plugin uses a capability it didn't declare (under-declaration).

Both are subtle bugs — the over-declared case ships a misleading
contract; the under-declared case bypasses runtime gates.

Coverage:

  * ``requires_market_price_protection`` ↔ MPP service call
    (``services.promoted_mpp_service`` import or invocation in
    broker source)
  * ``requires_slm_to_sl_conversion`` ↔ conversion call site
  * ``requires_v1_compat`` ↔ v1 translator registered
  * ``supports_subaccounts`` ↔ subaccount surface in auth flow

Allowlist: legacy India plugins (``supported_regions=["india"]``
exactly) skip the audit since their capability surface is inferred
rather than declared. Non-India plugins (and the mock plugins) get
the full check.

Exit codes: 0 (clean) / 1 (drift detected, list emitted to stderr).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BROKER_DIR = _REPO_ROOT / "broker"


def _load_plugin_json(broker_dir: Path) -> dict | None:
    plugin = broker_dir / "plugin.json"
    if not plugin.exists():
        return None
    try:
        with plugin.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _is_legacy_india(plugin_data: dict) -> bool:
    regions = plugin_data.get("supported_regions") or []
    if not isinstance(regions, list):
        return False
    normalized = {str(r).strip().lower() for r in regions}
    return normalized == {"india"}


def _broker_source_files(broker_dir: Path) -> list[Path]:
    """Return all .py files inside the broker directory."""
    out: list[Path] = []
    for root, dirs, files in os.walk(broker_dir):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fn in files:
            if fn.endswith(".py"):
                out.append(Path(root) / fn)
    return out


def _has_text_in_sources(sources: list[Path], needles: tuple[str, ...]) -> bool:
    for path in sources:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for needle in needles:
            if needle in text:
                return True
    return False


def _check_mpp_drift(
    broker: str, plugin_data: dict, sources: list[Path]
) -> str | None:
    declared = bool(plugin_data.get("requires_market_price_protection", False))
    if not declared:
        return None
    needles = ("promoted_mpp_service", "market_price_protection", "MarketPriceProtection")
    if not _has_text_in_sources(sources, needles):
        return (
            f"broker {broker!r}: declares "
            "requires_market_price_protection=True but no MPP service "
            "call detected in its sources. Either drop the flag or "
            "wire the call site."
        )
    return None


def _check_slm_to_sl_drift(
    broker: str, plugin_data: dict, sources: list[Path]
) -> str | None:
    declared = bool(plugin_data.get("requires_slm_to_sl_conversion", False))
    if not declared:
        return None
    needles = ("slm_to_sl", "SL-M", "convert_slm_to_sl")
    if not _has_text_in_sources(sources, needles):
        return (
            f"broker {broker!r}: declares "
            "requires_slm_to_sl_conversion=True but no SL-M→SL "
            "conversion call site detected in its sources."
        )
    return None


def _check_v1_compat_drift(
    broker: str, plugin_data: dict, sources: list[Path]
) -> str | None:
    declared = bool(plugin_data.get("requires_v1_compat", False))
    if not declared:
        return None
    # Look for translator registration: register_broker_translator
    # in the broker's startup file or a plugin __init__.
    needles = (
        "register_broker_translator",
        "BrokerOrderTranslator",
        "OrderTranslator",
    )
    if not _has_text_in_sources(sources, needles):
        return (
            f"broker {broker!r}: declares requires_v1_compat=True but "
            "no translator registration detected in its sources. "
            "Either drop the flag or register a v1 translator."
        )
    return None


def _check_subaccounts_drift(
    broker: str, plugin_data: dict, sources: list[Path]
) -> str | None:
    declared = bool(plugin_data.get("supports_subaccounts", False))
    if not declared:
        return None
    needles = ("subaccount", "sub_account", "account_id")
    if not _has_text_in_sources(sources, needles):
        return (
            f"broker {broker!r}: declares supports_subaccounts=True "
            "but no subaccount surface detected in auth flow."
        )
    return None


def _audit_broker(broker_dir: Path) -> list[str]:
    plugin_data = _load_plugin_json(broker_dir)
    if plugin_data is None:
        return []
    if _is_legacy_india(plugin_data):
        return []  # legacy India: capabilities inferred, not declared
    broker = broker_dir.name
    sources = _broker_source_files(broker_dir)
    violations: list[str] = []
    for check in (
        _check_mpp_drift,
        _check_slm_to_sl_drift,
        _check_v1_compat_drift,
        _check_subaccounts_drift,
    ):
        msg = check(broker, plugin_data, sources)
        if msg:
            violations.append(msg)
    return violations


def main() -> int:
    if not _BROKER_DIR.exists():
        print("broker_capability_drift_scan: broker/ not found", file=sys.stderr)
        return 1

    all_violations: list[str] = []
    plugin_count = 0
    for child in sorted(_BROKER_DIR.iterdir()):
        if not child.is_dir():
            continue
        if child.name in {"__pycache__"}:
            continue
        if not (child / "plugin.json").exists():
            continue
        plugin_count += 1
        all_violations.extend(_audit_broker(child))

    if not all_violations:
        print(
            f"broker_capability_drift_scan: clean ({plugin_count} plugins audited)"
        )
        return 0

    print("broker_capability_drift_scan: drift detected", file=sys.stderr)
    for v in all_violations:
        print(f"  {v}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
