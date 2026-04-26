# v4 Phase 1 — Complete

* **Branch:** `refactor/v4-phase-1-baseline-refresh`
* **Merged:** to `dev` with `--no-ff`
* **Effort:** high

## Goal

Refresh v3 baseline audits, install v4 invariants in the literal scanner
and lane-isolation tests, prepare contract tests as the regression net
for invariants enforced in later phases.

## Gaps closed (from `v3_baseline_audit.md`)

Phase 1 is governance — it does not directly close any of the 17 v3
gaps. It verifies status (see § "Gaps verified" below) and pre-stages
the contract tests that fire as later phases close gaps.

## Gaps verified

The 17 v3 gaps were re-checked against the live code on the v4 starting
commit. Result:

* **CONFIRMED (open):** gaps 6, 7, 13, 16
* **PARTIAL (residual):** gaps 3, 9, 14, 15
* **FIXED-SINCE (closed by v3 follow-up):** gaps 1, 2, 4, 5, 10, 11, 12, 17

Updated rows + closing-phase pointers committed to
`docs/refactor/v3_baseline_audit.md`.

## New contracts added

| File | Purpose |
|---|---|
| `docs/adr/0023-v4-scope-and-advanced-feature-providers.md` | Records v4 scope: close 17 v3 gaps + hard-block v1 for non-India + generalize Sandbox/Options/Screener as provider-pluggable + real Schwab/Webull out of v4 + additive migrations only + strict promoted plugin schema |
| `docs/refactor/v4-overview.md` | v4 phase tracker; lists 12 invariants and 12 phases with closing-gap mapping |
| `docs/refactor/v3_baseline_audit.md` | Re-purposed as the v4 progress tracker; every row has a Status + Closing v4 phase column |

## New tests added

| File | Purpose | Phase 1 result |
|---|---|---|
| `tests/contracts/test_v4_no_new_india_fallback.py` | Invariant 1: no `_FALLBACK_REGION = "india"` style constants in PROMOTED_CORE | xfail (Phase 2 fixes; xfail removed there) |
| `tests/contracts/test_v4_no_legacy_imports_from_promoted.py` | Invariant 5 (static AST view): PROMOTED_CORE files cannot import legacy India services / databases / schemas at module load time | **passes** (zero violations as of v4 starting commit) |
| `tests/contracts/test_v4_promoted_plugin_strict_mode.py` | Invariant 6: promoted plugins have all v4 required fields | xfail (Phase 4 fixes; xfail removed there) |
| `tests/contracts/test_v4_advanced_feature_provider_contracts.py` | Invariant 7: SandboxProvider / OptionsProvider / ScreenerProvider contracts exist with India + US implementations | 3 xfails (Phases 8 / 9 / 10 fix; xfails removed there) |

## Pre-allowlists prepared

`scripts/audit/classification_rules.yaml` extended with rules for
provider directories that Phases 7–10 will create:

* `services/sandbox/{__init__.py, dispatcher.py, providers/base.py}` → PROMOTED_CORE
* `services/sandbox/providers/{india,us,eu,uk}/` → REGION_PLUGIN
* `services/options/{__init__.py, dispatcher.py, providers/base.py}` → PROMOTED_CORE
* `services/options/providers/{india,us,eu,uk}/` → REGION_PLUGIN
* `services/screeners/{__init__.py, dispatcher.py, providers/base.py}` → PROMOTED_CORE
* `services/screeners/providers/{india,us}/` → REGION_PLUGIN
* `services/strategy/{__init__.py, scheduling/}` → PROMOTED_CORE

Pre-creation classification means later phases can drop files into
these paths without the classifier exiting non-zero on the first
addition.

## Comprehensive testing (gate 2.6)

| Step | Result |
|---|---|
| `pytest -x tests/contracts/ tests/parity/ tests/compliance/` | 101 passed, 5 xfailed (v4 invariant placeholders) — 20s |
| `python tests/parity/run_parity.py` | 7/7 passed |
| `pytest tests/` | 1811 passed, 7 skipped, 5 xfailed — 158s |
| `npm run lint:literals` | 253 files scanned, 0 violations |
| `python scripts/audit/classify_files.py --check` | 812 files classified, no drift |
| `python scripts/audit/route_fallback_scan.py` | 50 routes; valid drift (added `/api/v2/orders/combo` from v3 Phase 6) |
| `python scripts/audit/symtoken_callers.py` | 0 PROMOTED_LEAK rows |
| `python scripts/audit/canonical_vs_legacy_parity.py` | 13 pairs |

All gates pass.

## Deferred follow-ups

None. Phase 1 is governance only; subsequent phases close gaps per
the per-phase mapping in `v4-overview.md`.

## Files touched

* Modified: `docs/refactor/route_fallback_inventory.md` (regenerated; valid drift)
* Modified: `docs/refactor/v3_baseline_audit.md` (re-purposed as v4 tracker)
* Modified: `scripts/audit/classification_rules.yaml` (provider pre-allowlist)
* Created: `docs/adr/0023-v4-scope-and-advanced-feature-providers.md`
* Created: `docs/refactor/v4-overview.md`
* Created: `docs/refactor/v4-phase-1-complete.md` (this file)
* Created: `tests/contracts/test_v4_no_new_india_fallback.py`
* Created: `tests/contracts/test_v4_no_legacy_imports_from_promoted.py`
* Created: `tests/contracts/test_v4_promoted_plugin_strict_mode.py`
* Created: `tests/contracts/test_v4_advanced_feature_provider_contracts.py`
