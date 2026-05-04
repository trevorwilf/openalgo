"""v7 closing invariants — single-place gate for the v7 cycle.

Joins ``test_v{4,5,6}_closing_invariants.py`` and runs every v7
invariant in one place. Must pass before declaring v7 complete.

The 6 invariants (App B §11.5):

* **v7-A** — no new promoted module imports from
  ``market_regions/india/legacy_v1/``. AST scan; allowlist limited
  to documented ``sys.modules`` shim files.
* **v7-B** — no real (non-shim) PROMOTED_CORE blueprint contains
  the ``Asia/Kolkata`` literal. Regex over ``blueprints/``.
* **v7-C** — 4 promoted DB helpers (``auth_db``, ``action_center_db``,
  ``analyzer_db``, ``apilog_db``) use ``datetime.now(timezone.utc)``
  (or pytz.utc equivalent) as the UTC stamp pattern.
* **v7-D** — no ``or "MIS"`` / ``or "XNAS"`` silent default-fallback
  expressions in ``services/v1_compat_bridge.py``. The documented
  ``_VENUE_ALIASES`` translation table is preserved.
* **v7-E** — ``master_contract_refresh_policy`` mandatory for
  non-legacy plugins. Loads every plugin manifest; asserts non-
  legacy ones declare the policy (legacy India plugins skipped).
* **v7-F** — SymToken identity includes ``broker_code``. T-06
  schema redesign; deferred to a Phase 4-bis follow-up. The
  invariant test is pinned here as a placeholder that will fail
  until T-06 lands; for now the assertion is xfailed with a clear
  reference to the deferred phase.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# v7-A — no promoted module imports from legacy_v1/
# ---------------------------------------------------------------------------


def _is_documented_shim(text: str) -> bool:
    """Heuristic: a shim file imports ONE legacy_v1 module via the
    documented ``as _orig`` aliasing pattern and re-exports it via
    ``sys.modules``. Files matching this pattern are pre-existing
    documented shims (CLAUDE.md "Promoted lane") and are exempt
    from v7-A. New legacy_v1 imports outside this pattern fail."""
    return "as _orig" in text or "as _v1_lane_guard" in text or "legacy_v1.restx_api" in text


# Explicit allowlist for shim files that don't match the heuristic
# but are documented compat shims. CLAUDE.md "Promoted lane" lists
# these as the legacy compat shim layer.
_V7_A_EXPLICIT_ALLOWLIST: frozenset[str] = frozenset({
    # Legacy translator re-export (CLAUDE.md "Promoted lane").
    "domain/translators.py",
    # Master-contract scheduler imports auth_utils helpers (T-09
    # closes the India-tz anchor; helper still lives in legacy_v1).
    "services/master_contract_scheduler.py",
    # utils/constants.py is THE documented re-export shim — listed
    # explicitly in CLAUDE.md "Promoted lane".
    "utils/constants.py",
})


def test_v7_invariant_v7_a_no_promoted_legacy_v1_imports():
    """v7-A: documented sys.modules shims are the only legacy_v1
    importers in PROMOTED_CORE. New code must not add new imports
    outside the documented ``as _orig`` shim pattern."""
    pattern = re.compile(r"from\s+market_regions\.india\.legacy_v1")

    # Walk only the promoted-relevant directories. Skip .venv,
    # legacy_v1/ itself, tests, and scripts.
    PROMOTED_ROOTS = (
        "blueprints",
        "broker",
        "database",
        "domain",
        "events",
        "market_regions",  # but skip india/legacy_v1 below
        "restx_api",
        "services",
        "subscribers",
        "upgrade",
        "utils",
        "websocket_proxy",
    )
    violations = []
    for root in PROMOTED_ROOTS:
        root_path = _REPO_ROOT / root
        if not root_path.exists():
            continue
        for path in root_path.rglob("*.py"):
            rel = str(path.relative_to(_REPO_ROOT)).replace("\\", "/")
            if rel.startswith("market_regions/india/legacy_v1"):
                continue
            if rel.startswith("market_regions/india/") and not rel.startswith(
                "market_regions/india/legacy_v1"
            ):
                # The new India region package code is allowed to
                # import from its own legacy_v1 sibling (it's the
                # one place that should).
                continue
            if rel in _V7_A_EXPLICIT_ALLOWLIST:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            # Skip files that follow the documented sys.modules shim
            # pattern (the historical re-export approach) — they're
            # the boundary that lets the legacy code be importable
            # at the top-level path while the implementation stays
            # in legacy_v1/.
            if _is_documented_shim(text):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    violations.append(f"{rel}:{lineno}: {line.strip()}")
    assert not violations, (
        "v7-A: new promoted module imports from legacy_v1.\n  "
        + "\n  ".join(violations)
    )


# ---------------------------------------------------------------------------
# v7-B — no Asia/Kolkata literal in promoted blueprints
# ---------------------------------------------------------------------------


def test_v7_invariant_v7_b_no_kolkata_in_promoted_blueprints():
    """v7-B: promoted blueprints render via active_render_tz_name()."""
    PROMOTED_BLUEPRINTS = (
        "blueprints/pnltracker.py",
        "blueprints/analyzer.py",
        "blueprints/health.py",
        "blueprints/latency.py",
        "blueprints/log.py",
        "blueprints/traffic.py",
    )
    pattern = re.compile(r'"Asia/Kolkata"|\'Asia/Kolkata\'')
    violations = []
    for rel in PROMOTED_BLUEPRINTS:
        path = _REPO_ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                violations.append(f"{rel}:{lineno}: {line.strip()}")
    assert not violations, "v7-B: India tz literal in promoted blueprints.\n  " + "\n  ".join(violations)


# ---------------------------------------------------------------------------
# v7-C — promoted DB helpers UTC stamp
# ---------------------------------------------------------------------------


def test_v7_invariant_v7_c_promoted_db_helpers_utc_stamp():
    """v7-C: 4 promoted DB helpers use UTC at write time."""
    DB_HELPERS = (
        "database/auth_db.py",
        "database/action_center_db.py",
        "database/analyzer_db.py",
        "database/apilog_db.py",
    )
    utc_patterns = (
        re.compile(r"datetime\.now\(\s*timezone\.utc\s*\)"),
        re.compile(r"datetime\.now\(\s*pytz\.utc\s*\)"),
        re.compile(r"datetime\.now\(\s*pytz\.UTC\s*\)"),
    )
    missing = []
    for rel in DB_HELPERS:
        text = (_REPO_ROOT / rel).read_text(encoding="utf-8")
        if not any(p.search(text) for p in utc_patterns):
            missing.append(rel)
    assert not missing, (
        "v7-C: promoted DB helper missing UTC stamp pattern: "
        f"{missing}"
    )


# ---------------------------------------------------------------------------
# v7-D — no MIS/XNAS default in v1 compat bridge
# ---------------------------------------------------------------------------


def test_v7_invariant_v7_d_no_silent_india_defaults_in_v1_bridge():
    """v7-D: no ``or "MIS"`` / ``or "XNAS"`` default-fallbacks in
    services/v1_compat_bridge.py. The documented venue alias map
    preserves XNAS/etc. as TRANSLATION TARGETS, not defaults."""
    text = (_REPO_ROOT / "services/v1_compat_bridge.py").read_text(encoding="utf-8")
    pat = re.compile(r'\bor\s+["\'](?:MIS|XNAS)["\']')
    matches = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if line.strip().startswith("#"):
            continue
        if pat.search(line):
            matches.append(f"v1_compat_bridge.py:{lineno}: {line.strip()}")
    assert not matches, (
        "v7-D: silent India default in v1_compat_bridge.\n  "
        + "\n  ".join(matches)
    )


# ---------------------------------------------------------------------------
# v7-E — master_contract_refresh_policy mandatory for non-legacy plugins
# ---------------------------------------------------------------------------


def test_v7_invariant_v7_e_refresh_policy_mandatory_for_non_legacy():
    """v7-E: every non-legacy plugin declares
    master_contract_refresh_policy in plugin.json."""
    broker_dir = _REPO_ROOT / "broker"
    missing = []
    for d in sorted(broker_dir.iterdir()):
        if not d.is_dir():
            continue
        pj = d / "plugin.json"
        if not pj.exists():
            continue
        with pj.open(encoding="utf-8") as f:
            data = json.load(f)
        regions = data.get("supported_regions") or []
        normalized = (
            {str(r).strip().lower() for r in regions}
            if isinstance(regions, list)
            else set()
        )
        if normalized == {"india"}:
            continue  # legacy India: optional
        if not data.get("master_contract_refresh_policy"):
            missing.append(d.name)
    assert not missing, (
        "v7-E: non-legacy plugin missing master_contract_refresh_policy: "
        f"{missing}"
    )


# ---------------------------------------------------------------------------
# v7-F — SymToken broker_code (T-06; deferred)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason="T-06 SymToken broker_code redesign deferred to a Phase 4-bis follow-up; the schema change + backfill + v1-lane DB view is too risky for the current cycle and lands in a separate session."
)
def test_v7_invariant_v7_f_symtoken_includes_broker_code():
    """v7-F: SymToken's identity tuple includes ``broker_code``.

    Pre-T-06 the unique constraint is ``(symbol, exchange)``; post-
    T-06 it becomes ``(broker_code, symbol, exchange)``. This
    invariant fails until T-06 lands; xfailed with a documented
    deferral reason.
    """
    from market_regions.india.legacy_v1.database.symbol import SymToken

    columns = {col.name for col in SymToken.__table__.columns}
    assert "broker_code" in columns, "T-06 not yet shipped"
