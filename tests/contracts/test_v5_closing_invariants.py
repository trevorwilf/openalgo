"""Phase 10 v5 — closing invariant gate.

The "single command that proves v5 is done." Operators run this
test as the final gate before declaring v5 complete.

Re-runs every v4 invariant via the v4 closing test, then adds the
v5-specific invariants:

* v5-1 — structured error taxonomy (ADR 0029).
* v5-2 — observability label set (ADR 0030).
* DST correctness for promoted venues.
* India v1→v2 readiness inventory present.
* Per-feature capability fields propagated (`supports_sandbox`,
  `supports_options`, `supports_screener_providers`,
  `supports_combo_types` top-level).
* Parity harnesses cover sandbox/options/chartink India.
* Compatibility shims listed as REMOVED in Phase 9 are gone.
* `/api/v1/*` deprecation headers present.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_invariant_v4_baseline_still_holds():
    """Re-runs every v4 invariant in one place."""
    from tests.contracts.test_v4_closing_invariants import (
        test_invariant_1_no_silent_india_fallback_in_promoted_core,
        test_invariant_5_no_legacy_imports_from_promoted_core,
        test_invariant_5_v1_lane_blocks_non_india_brokers,
        test_invariant_6_promoted_plugins_strict_mode,
        test_invariant_7_advanced_feature_provider_contracts_exist,
        test_invariant_12_zero_promoted_leak_rows,
        test_v4_closing_audit_zero_xfails_in_invariant_tests,
    )

    test_invariant_1_no_silent_india_fallback_in_promoted_core()
    test_invariant_5_no_legacy_imports_from_promoted_core()
    test_invariant_6_promoted_plugins_strict_mode()
    test_invariant_7_advanced_feature_provider_contracts_exist()
    test_invariant_5_v1_lane_blocks_non_india_brokers()
    test_invariant_12_zero_promoted_leak_rows()
    test_v4_closing_audit_zero_xfails_in_invariant_tests()


def test_invariant_v5_1_structured_error_taxonomy():
    """ADR 0029 — every v5 error code is reachable via its class."""
    from domain.errors import (
        EntitlementRequired,
        ErrorCode,
        LegacyLaneBlocked,
        MissingCurrencyContext,
        MissingInstrumentIdentity,
        MissingRegionContext,
        MissingTranslator,
        MissingVenueContext,
        UnsupportedCapability,
        UnsupportedProvider,
        UnsupportedRegion,
        UnsupportedVenue,
    )

    expected_codes = {
        UnsupportedRegion("eu").code: ErrorCode.UNSUPPORTED_REGION,
        MissingRegionContext().code: ErrorCode.MISSING_REGION_CONTEXT,
        UnsupportedVenue("X").code: ErrorCode.UNSUPPORTED_VENUE,
        MissingVenueContext().code: ErrorCode.MISSING_VENUE_CONTEXT,
        MissingCurrencyContext().code: ErrorCode.MISSING_CURRENCY_CONTEXT,
        MissingInstrumentIdentity().code: ErrorCode.MISSING_INSTRUMENT_IDENTITY,
        MissingTranslator("x").code: ErrorCode.MISSING_TRANSLATOR,
        UnsupportedProvider("sandbox").code: ErrorCode.UNSUPPORTED_PROVIDER,
        LegacyLaneBlocked("place_order_service").code: ErrorCode.LEGACY_LANE_BLOCKED,
        EntitlementRequired("ent").code: ErrorCode.ENTITLEMENT_REQUIRED,
    }
    for actual, expected in expected_codes.items():
        assert actual == expected
    # `unsupported_capability` extended with dimension enum.
    err = UnsupportedCapability("x", "tif", dimension="tif")
    assert err.dimension == "tif"


def test_invariant_v5_2_observability_label_set():
    """ADR 0030 — promoted-request canonical label set."""
    from utils.observability import REQUIRED_LABELS, build_context

    expected = {
        "region_code", "broker_code", "venue_code", "instrument_id",
        "currency", "provider_code", "capability_source",
        "legacy_lane", "route", "request_id",
    }
    assert set(REQUIRED_LABELS) == expected
    ctx = build_context(capability_source="region")
    ctx.assert_complete()


def test_invariant_v5_dst_correctness_for_promoted_venues():
    from tests.contracts.test_v5_dst_correctness import (
        test_ny_dst_starts_second_sunday_of_march,
        test_london_dst_ends_last_sunday_of_october,
        test_paris_dst_starts_last_sunday_of_march,
        test_kolkata_january_is_ist_plus_5h30m,
    )

    test_ny_dst_starts_second_sunday_of_march()
    test_london_dst_ends_last_sunday_of_october()
    test_paris_dst_starts_last_sunday_of_march()
    test_kolkata_january_is_ist_plus_5h30m()


def test_invariant_v5_india_v2_readiness_inventory_present():
    matrix = REPO_ROOT / "docs" / "refactor" / "v5_india_v2_readiness_matrix.md"
    migration = REPO_ROOT / "docs" / "migration" / "v1-to-v2.md"
    assert matrix.is_file()
    assert migration.is_file()


def test_invariant_v5_capability_fields_propagated():
    """Every v5 capability field exists on `BrokerCapabilities`."""
    from domain.capabilities import BrokerCapabilities, ComboType

    for field in (
        "supports_sandbox",
        "supports_options",
        "supports_screener_providers",
        "supports_combo_types",
    ):
        assert field in BrokerCapabilities.model_fields, (
            f"missing capability field {field!r} on BrokerCapabilities"
        )


def test_invariant_v5_parity_harnesses_added():
    """Sandbox / options / chartink India parity harnesses exist."""
    baseline_dir = REPO_ROOT / "tests" / "parity" / "baseline"
    for name in (
        "parity_sandbox_india",
        "parity_options_india",
        "parity_chartink_india",
    ):
        assert (baseline_dir / f"{name}.py").is_file()
        assert (baseline_dir / f"{name}.json").is_file()


def test_invariant_v5_removed_shims_stay_removed():
    """Compatibility shims explicitly removed in v5 must stay removed."""
    utils_text = (REPO_ROOT / "frontend" / "src" / "lib" / "utils.ts").read_text(
        encoding="utf-8"
    )
    assert "export function makeFormatCurrency" not in utils_text

    legacy_text = (
        REPO_ROOT
        / "frontend"
        / "src"
        / "india_legacy"
        / "lib"
        / "legacy_fallback_exchanges.ts"
    ).read_text(encoding="utf-8")
    assert "export const LEGACY_FALLBACK_EXCHANGES" not in legacy_text


def test_invariant_v5_v1_routes_emit_deprecation_headers():
    """RFC 8594 headers stamped on every /api/v1/* response."""
    from app import app

    client = app.test_client()
    resp = client.post("/api/v1/ping/", json={"apikey": "test"})
    assert resp.headers.get("Deprecation") == "true"
    assert resp.headers.get("Sunset"), "missing Sunset header"


def test_invariant_v5_classification_zero_drift():
    """Classification audit must report no drift."""
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "audit" / "classify_files.py"),
            "--check",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"classification drift: {result.stdout}\n{result.stderr}"
    )


def test_invariant_v5_symtoken_zero_promoted_leak():
    """SymToken caller audit must report zero PROMOTED_LEAK rows."""
    report = REPO_ROOT / "docs" / "refactor" / "symtoken_callers.md"
    assert report.is_file()
    text = report.read_text(encoding="utf-8")
    leak_rows = sum(1 for line in text.splitlines() if "| PROMOTED_LEAK |" in line)
    assert leak_rows == 0, f"{leak_rows} PROMOTED_LEAK rows found"


def test_invariant_v5_parity_runner_lane_filter_works():
    """`--lane v1` and `--lane v2` modes both succeed."""
    for lane in ("v1", "v2"):
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "tests" / "parity" / "run_parity.py"),
                "--lane",
                lane,
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, (
            f"--lane {lane} failed: {result.stdout}\n{result.stderr}"
        )


def test_v5_closing_audit_zero_xfails_in_invariant_tests():
    """No xfail markers in any v5 invariant test."""
    invariant_files = [
        REPO_ROOT / "tests" / "contracts" / "test_v5_structured_errors_emitted.py",
        REPO_ROOT / "tests" / "contracts" / "test_v5_observability_labels_complete.py",
        REPO_ROOT / "tests" / "contracts" / "test_v5_dst_correctness.py",
        REPO_ROOT / "tests" / "contracts" / "test_v5_combo_capability_single_source.py",
        REPO_ROOT / "tests" / "contracts" / "test_v5_india_v2_readiness.py",
        REPO_ROOT / "tests" / "contracts" / "test_v5_india_v2_default_on.py",
        REPO_ROOT / "tests" / "contracts" / "test_v5_no_india_synthesis_in_promoted_frontend.py",
    ]
    leftovers = []
    for f in invariant_files:
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8")
        if "@pytest.mark.xfail" in text:
            leftovers.append(f.name)
    assert not leftovers, (
        f"v5 invariant tests still carry xfail markers: {leftovers}"
    )
