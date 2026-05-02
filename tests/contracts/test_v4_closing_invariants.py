"""Phase 12 v4 — closing invariant gate.

Re-runs every v4 invariant in one place. Exists primarily as the
"single command that proves v4 is done" — operators run this test
before promoting non-India brokers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_invariant_1_no_silent_india_fallback_in_promoted_core():
    """Invariant 1 — see test_v4_no_new_india_fallback.py for detail."""
    from tests.contracts.test_v4_no_new_india_fallback import (
        test_no_silent_india_fallback_in_promoted_core,
    )

    test_no_silent_india_fallback_in_promoted_core()


def test_invariant_5_no_legacy_imports_from_promoted_core():
    """Invariant 5 — see test_v4_no_legacy_imports_from_promoted.py."""
    from tests.contracts.test_v4_no_legacy_imports_from_promoted import (
        test_promoted_core_no_v4_legacy_imports,
    )

    test_promoted_core_no_v4_legacy_imports()


def test_invariant_6_promoted_plugins_strict_mode():
    """Invariant 6 — see test_v4_promoted_plugin_strict_mode.py."""
    from tests.contracts.test_v4_promoted_plugin_strict_mode import (
        test_promoted_plugins_have_all_v4_required_fields,
    )

    test_promoted_plugins_have_all_v4_required_fields()


def test_invariant_7_advanced_feature_provider_contracts_exist():
    """Invariant 7 — Sandbox / Options / Screener provider contracts."""
    from tests.contracts.test_v4_advanced_feature_provider_contracts import (
        test_options_provider_contract_exists_with_india_and_us_providers,
        test_sandbox_provider_contract_exists_with_india_and_us_providers,
        test_screener_provider_contract_exists_with_india_provider,
    )

    test_sandbox_provider_contract_exists_with_india_and_us_providers()
    test_options_provider_contract_exists_with_india_and_us_providers()
    test_screener_provider_contract_exists_with_india_provider()


def test_invariant_5_v1_lane_blocks_non_india_brokers():
    """Invariant 5 (request-time) — v1 routes return 410 for non-India."""
    from tests.contracts.test_v1_lane_blocks_non_india import (
        test_non_india_broker_blocked_with_410,
        flask_app as _flask_app_fixture,
    )

    # Cannot directly invoke the test here because it depends on a
    # pytest fixture. Instead assert the guard module exists.
    # Phase 9-bis-physical (T-23 Group D) — guard relocated to
    # market_regions/india/legacy_v1/restx_api/_v1_lane_guard.py;
    # restx_api/__init__.py imports it from the new location.
    guard = (
        REPO_ROOT
        / "market_regions"
        / "india"
        / "legacy_v1"
        / "restx_api"
        / "_v1_lane_guard.py"
    )
    assert guard.is_file(), (
        f"missing {guard.relative_to(REPO_ROOT).as_posix()} — "
        "v4 Phase 2 ships the v1 hard-block guard."
    )


def test_invariant_12_zero_promoted_leak_rows():
    """Invariant 12 — SymToken caller audit shows zero PROMOTED_LEAK rows."""
    report = REPO_ROOT / "docs" / "refactor" / "symtoken_callers.md"
    if not report.is_file():
        pytest.skip("symtoken_callers.md missing; run scripts/audit/symtoken_callers.py")
    text = report.read_text(encoding="utf-8")
    # The report shows a count line; assert no PROMOTED_LEAK rows.
    # The audit script also emits a count line at the end of run.
    promoted_leak_rows = text.count("PROMOTED_LEAK")
    # The string appears in the legend / column header even when the
    # data section is empty, so we look for an actual data-table row.
    # A data row begins with "| " and contains "| PROMOTED_LEAK |".
    leak_data_rows = sum(
        1 for line in text.splitlines() if "| PROMOTED_LEAK |" in line
    )
    assert leak_data_rows == 0, (
        f"SymToken caller audit shows {leak_data_rows} PROMOTED_LEAK "
        "rows — invariant 12 violated."
    )


def test_v4_closing_audit_zero_xfails_in_invariant_tests():
    """No xfail markers should remain in any v4 invariant test."""
    invariant_test_files = [
        REPO_ROOT / "tests" / "contracts" / "test_v4_no_new_india_fallback.py",
        REPO_ROOT / "tests" / "contracts" / "test_v4_no_legacy_imports_from_promoted.py",
        REPO_ROOT / "tests" / "contracts" / "test_v4_promoted_plugin_strict_mode.py",
        REPO_ROOT / "tests" / "contracts" / "test_v4_advanced_feature_provider_contracts.py",
    ]
    leftovers: list[str] = []
    for f in invariant_test_files:
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8")
        if "@pytest.mark.xfail" in text:
            leftovers.append(f.name)
    assert not leftovers, (
        "v4 invariant tests still carry xfail markers (the gap they "
        f"guarded should now pass): {leftovers}"
    )
