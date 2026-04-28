# v6 Phase 0 — Complete

* **Branch:** `refactor/v6-phase-0-gap-inventory`
* **Branched from:** `dev` @ `0ab793bb` (HEAD: "updated gitignore" on top of v5 Phase 10 close)
* **Effort:** medium
* **Behavior changes:** none — Phase 0 is read-only gap inventory.

## What shipped

1. **`docs/refactor/v6_gap_inventory.md`** — the authoritative gap
   inventory. Maps every Expert-1 / Expert-2 finding row from
   `expert 1 - appendix A` and `expert 2 - appendix A` to one of
   `ALREADY-CLOSED`, `BIS-DEFERRED`, `OUT-OF-SCOPE`,
   `INTENTIONAL-INDIA-LIMIT`, or `GENUINE-GAP`. The aggregate is
   **184 distinct findings classified**:
   * Expert 1 §3 (explicit India): 81 rows
   * Expert 1 §4 (implicit): 14 rows
   * Expert 2 §3 (explicit India): 56 rows
   * Expert 2 §4 (implicit): 31 rows
   * 0 GENUINE-GAP rows — every finding reaches v6 by way of an
     existing in-repo ADR closure, a v5 bis-phase that v6 owns, or
     an out-of-scope notice.
2. **`tests/contracts/test_v6_gap_inventory_present.py`** — 7-test
   contract (parametrized) that asserts the inventory exists, has
   the four required section headings, has ≥ 50 finding-ID rows,
   and (vacuously today) that any GENUINE-GAP row has a non-empty
   owning-phase column.

The inventory's appendices feed the next four phases:

| Section | Feeds | Count |
|---|---|---|
| "Frontend per-component cleanup list (for Phase 1)" | Phase 1 | 11 components |
| "Legacy-compat named-caller list (for Phase 2)" | Phase 2 | 22 callers across 4 surfaces |
| "Region / provider matrix snapshot" | Phase 3 | EU + UK provider stubs (3 surfaces × 2 regions = 6 stubs) |
| "Mock plugin extension list (for Phase 4)" | Phase 4 | 5 mock-extension targets |
| "India broker enumeration for Phases 5–7" | Phases 5/6/7 | 30 brokers (5 + 12 + 13) |

## Comprehensive test gate (passed)

| Step | Result |
|---|---|
| `uv run pytest tests/ -x --tb=short` | **2177 passed, 7 skipped** in 3:34 (was 2170 / 7 / 0 at baseline; +7 = the new parametrized contract test) |
| `uv run pytest -x tests/contracts/test_v4_closing_invariants.py tests/contracts/test_v5_closing_invariants.py` | **20 passed** in 12.63 s |
| `uv run python tests/parity/run_parity.py` | **11/11** verify-mode harnesses |
| `uv run python tests/parity/run_parity.py --lane v1` | **11/11** v1-lane harnesses |
| `uv run python tests/parity/run_parity.py --lane v2` | **11/11** v2-lane harnesses |
| `uv run python scripts/audit/classify_files.py --check` | exit 0 — 840 files / no drift |
| `uv run python scripts/audit/route_fallback_scan.py` | exit 0 — 51 routes |
| `uv run python scripts/audit/symtoken_callers.py` | exit 0 — 0 PROMOTED_LEAK rows |
| `uv run python scripts/audit/canonical_vs_legacy_parity.py` | exit 0 — 13 pairs |
| `npm test -- --run` (frontend) | **150 passed across 14 test files** |
| `npm run lint:literals` | exit 0 — 255 files / 0 violations |

All v4 and v5 invariants still hold. India parity is bit-identical.

## Notable findings

* The v6 prompt's "123 expert findings" is approximate; the actual
  distinct-row aggregate across both Appendix A's §3+§4 is **184**.
  Every row has been classified.
* The v5 readiness matrix listed **29 India brokers**; the actual
  `broker/` directory lists **30 India brokers** (the matrix omitted
  `wisdom` and `zebu`). The v6 prompt's Phase 7 list explicitly
  contains both, so the inventory's broker enumeration totals 30.
* Of the 184 findings, **116 are INTENTIONAL-INDIA-LIMIT** rows —
  India broker adapters, India-specific UI surfaces with no non-India
  equivalent (Chartink, IV charts, Strategy Builder's India option
  grammar), and the explicit India compatibility paths gated by
  `services.feature_gate_service.is_india_region_active()`. None of
  these are gaps — they are the intentional outcome of v3-v5 design
  choices captured in ADRs 0011, 0017, 0019, 0020, 0024, 0026, 0027,
  0028.
* **32 ALREADY-CLOSED** rows are enforced by existing contract tests
  (`test_lane_isolation`, `test_v1_lane_blocks_non_india`,
  `test_v4_closing_invariants`, `test_v5_closing_invariants`).
* **35 BIS-DEFERRED** rows are owned by Phases 1–7 of this v6 prompt.

## Next phase

**Phase 1 — Frontend Per-Component Cleanup.** `/compact` then `/effort high`.
Closes the 11 frontend cleanup-target components enumerated in
inventory § "Frontend per-component cleanup list (for Phase 1)".
Adds `useVenueTimezone()` hook. Shrinks
`frontend/scripts/literal_scan_allowlist.json`.
