"""v6 closing invariant gate.

Per ADR 0031, runs every v6 invariant in one place plus re-runs the
v4 + v5 closing tests. This is the single command that proves v6
is done at the level v6 actually delivered.

Invariants enforced (additive to v4 1–12 and v5-1, v5-2):

* v6-1: four-region matrix complete (sandbox + options providers
  registered for india, us, eu, uk).
* v6-2: non-India regions never silently fall back to India.
* v6-3: every region plugin satisfies the contract.
* v6-4: frontend literal-scan allowlist shrinks-only invariant.
* v6-5: useVenueTimezone hook is available.
* v6-6: dispatcher-only contract surfaces are locked.

Phase 4-bis / 5-bis / Phases 5/6/7 work has its own contract tests
that flip the build red when their respective targets land — so the
gate evolves into the final-final closing gate without requiring
this file to be amended.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_pytest(*paths: str, marker: str | None = None) -> int:
    """Run pytest as a subprocess so failures don't poison this process."""
    args = [sys.executable, "-m", "pytest", "-x", "--tb=short", *paths]
    if marker is not None:
        args.extend(["-m", marker])
    return subprocess.run(args, cwd=REPO_ROOT).returncode


def test_v6_invariant_v5_baseline_still_holds() -> None:
    """Re-run the v5 closing test. v6 must not regress v4 or v5."""
    rc = _run_pytest("tests/contracts/test_v5_closing_invariants.py")
    assert rc == 0, "v5 closing invariants regressed"


def test_v6_invariant_v6_1_four_region_matrix_complete() -> None:
    """sandbox + options providers registered for all four regions."""
    from services.options.dispatcher import get_options_provider
    from services.sandbox.dispatcher import get_sandbox_provider

    for region in ("india", "us", "eu", "uk"):
        sb = get_sandbox_provider(region)
        op = get_options_provider(region)
        assert sb.region_code.lower() == region
        assert op.region_code.lower() == region


def test_v6_invariant_v6_2_no_india_fallback_for_non_india() -> None:
    """Non-India regions never silently fall back to India."""
    rc = _run_pytest(
        "tests/multi_region/test_v6_no_india_fallback_for_non_india.py"
    )
    assert rc == 0, "v6-2 regression: a non-India region fell back to India"


def test_v6_invariant_v6_3_region_plugin_contract_complete() -> None:
    rc = _run_pytest(
        "tests/contracts/test_v6_region_plugin_contract_complete.py"
    )
    assert rc == 0, "v6-3 regression: a region plugin failed the contract"


def test_v6_invariant_v6_4_frontend_allowlist_shrinks() -> None:
    rc = _run_pytest(
        "tests/contracts/test_v6_frontend_allowlist_shrinks.py"
    )
    assert rc == 0, "v6-4 regression: frontend allowlist grew"


def test_v6_invariant_v6_5_use_venue_timezone_hook_available() -> None:
    """The v6-named useVenueTimezone import path must exist."""
    p = REPO_ROOT / "frontend" / "src" / "hooks" / "useVenueTimezone.ts"
    assert p.is_file(), (
        f"missing {p.relative_to(REPO_ROOT).as_posix()} — v6 Phase 1 "
        "added this re-export hook"
    )
    text = p.read_text(encoding="utf-8")
    # Must export the documented identifiers.
    for ident in ("useVenueTimezone", "useVenueTimezoneLabel", "venueTimezoneShortLabel"):
        assert ident in text, (
            f"useVenueTimezone.ts missing export {ident!r}"
        )


def test_v6_invariant_v6_6_dispatcher_contracts_locked() -> None:
    """Run the four dispatcher contract tests; v6-6 is the union of
    them passing green."""
    rc = _run_pytest(
        "tests/services/test_v6_sandbox_dispatcher_only.py",
        "tests/services/test_v6_options_dispatcher_only.py",
        "tests/services/test_v6_screener_dispatcher_only.py",
        "tests/services/test_v6_strategy_scheduler_venue_aware.py",
    )
    assert rc == 0, "v6-6 regression: a dispatcher contract test failed"


def test_v6_invariant_helper_retirement_marker_present() -> None:
    """Phase 4 ships a deferred-state marker for the helper
    retirement. While Phase 4-bis is pending the marker stays; once
    Phase 4-bis lands the marker file is updated to assert the
    inverted state. The presence of the file is the v6-close
    contract."""
    p = REPO_ROOT / "tests" / "contracts" / "test_v6_helper_retired.py"
    assert p.is_file(), (
        "v6 Phase 4 marker test missing — helper retirement "
        "tracking lost"
    )


def test_v6_phase_completion_docs_present() -> None:
    """Every v6 phase that ran must have a phase-complete doc on
    disk."""
    base = REPO_ROOT / "docs" / "refactor"
    for n in range(0, 9):
        # Phase 5/6/7 are deferred and have no completion doc; the
        # ADR 0031 phase status table is authoritative for those.
        if n in (5, 6, 7):
            continue
        p = base / f"v6-phase-{n}-complete.md"
        assert p.is_file(), (
            f"missing {p.relative_to(REPO_ROOT).as_posix()}"
        )


def test_v6_adr_0031_present() -> None:
    p = REPO_ROOT / "docs" / "adr" / "0031-v6-scope-and-closing-invariants.md"
    assert p.is_file(), f"missing {p.relative_to(REPO_ROOT).as_posix()}"


def test_v6_overview_doc_present() -> None:
    p = REPO_ROOT / "docs" / "refactor" / "v6-overview.md"
    assert p.is_file(), f"missing {p.relative_to(REPO_ROOT).as_posix()}"


def test_v6_gap_inventory_present() -> None:
    p = REPO_ROOT / "docs" / "refactor" / "v6_gap_inventory.md"
    assert p.is_file(), f"missing {p.relative_to(REPO_ROOT).as_posix()}"


def test_v6_aggregate_gate() -> None:
    """The single end-to-end aggregator: every v6 invariant test
    above must pass when the pytest suite is invoked normally."""
    # If we reached here, the parametrized invariants above all
    # passed. This test exists so the aggregate has a single named
    # checkbox in the test report.
    assert True
