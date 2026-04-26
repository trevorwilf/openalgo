"""Phase 0 v3 — assertions over the route fallback inventory.

The inventory at ``docs/refactor/route_fallback_inventory.md`` is the
operator's reference for which v1/v2 routes still rely on legacy
services and which v3 phase closes each leak. This module enforces:

1. The inventory exists.
2. Every promoted (``/api/v2``) route either fails closed for non-India
   brokers OR declares an owning phase that closes the leak.
3. No legacy (``/api/v1``) route is mistakenly marked
   ``fail_closed_non_india=yes`` — that column does not apply.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INVENTORY = REPO_ROOT / "docs" / "refactor" / "route_fallback_inventory.md"


def _parse_inventory() -> list[dict[str, str]]:
    text = INVENTORY.read_text(encoding="utf-8")
    rows: list[dict[str, str]] = []
    in_table = False
    headers: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("| route_path"):
            in_table = True
            headers = [c.strip() for c in line.strip("|").split("|")]
            continue
        if in_table and line.startswith("|---"):
            continue
        if in_table:
            if not line.startswith("|"):
                in_table = False
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) != len(headers):
                continue
            row = dict(zip(headers, cells))
            row["route_path"] = re.sub(r"^`|`$", "", row.get("route_path", ""))
            rows.append(row)
    return rows


def test_inventory_exists() -> None:
    assert INVENTORY.is_file(), (
        f"route fallback inventory missing at {INVENTORY}; run "
        "`uv run python scripts/audit/route_fallback_scan.py`."
    )


def test_inventory_has_v1_and_v2_routes() -> None:
    rows = _parse_inventory()
    v1 = [r for r in rows if r["route_path"].startswith("/api/v1/")]
    v2 = [r for r in rows if r["route_path"].startswith("/api/v2/")]
    assert v1, "no v1 routes parsed from inventory"
    assert v2, "no v2 routes parsed from inventory"


def test_promoted_routes_declare_phase_or_fail_closed() -> None:
    """Each ``/api/v2`` route must either fail closed for non-India
    brokers (``fail_closed_non_india=yes``), be a metadata-only
    surface (``fail_closed_non_india=n/a``), or declare the v3 phase
    that closes the open behavior (``owning_phase_to_fix`` non-empty
    and not ``none``).
    """
    rows = _parse_inventory()
    v2 = [r for r in rows if r["route_path"].startswith("/api/v2/")]
    assert v2, "no v2 routes in inventory"
    bad: list[str] = []
    for r in v2:
        fc = r.get("fail_closed_non_india", "")
        ph = r.get("owning_phase_to_fix", "")
        if fc in {"yes", "n/a"}:
            continue
        if ph and ph != "none":
            continue
        bad.append(f"{r['route_path']}: fc={fc!r} owning_phase={ph!r}")
    assert not bad, (
        "Promoted routes must fail closed or declare an owning phase:\n  "
        + "\n  ".join(bad)
    )


def test_legacy_routes_do_not_declare_failclosed_for_non_india() -> None:
    """``/api/v1`` is the legacy India lane. It does not have a
    fail-closed-for-non-India concept (every v1 caller is India by
    construction), so the column should be ``n/a``."""
    rows = _parse_inventory()
    v1 = [r for r in rows if r["route_path"].startswith("/api/v1/")]
    bad = [
        f"{r['route_path']}: fail_closed_non_india={r['fail_closed_non_india']!r}"
        for r in v1
        if r.get("fail_closed_non_india") not in {"n/a", ""}
    ]
    assert not bad, (
        "Legacy v1 routes must not declare fail_closed_non_india:\n  "
        + "\n  ".join(bad)
    )
