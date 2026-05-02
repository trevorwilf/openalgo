# v5 Phase 1 — Complete

* **Branch:** `refactor/v5-phase-1-governance-and-errors`
* **Merged:** to `dev` with `--no-ff`
* **Effort:** high
* **Closes:** v5 prompt scope items 1–7; expert MA-000…MA-003,
  MA-012, MA-043; expert P0-01, P0-02, P0-04, P0-07, P0-08, P9-01.

## Goal

Stand up v5 governance and harden the structured-error / observability
surface. No behavior changes outside error response shapes and log
fields.

## Work shipped

### `docs/refactor/v5-overview.md` — new

Mirrors the v4 format. v5 invariants (v5-1 structured error codes;
v5-2 promoted-request observability label set), per-phase status
table, what v6 should consider.

### `docs/refactor/file_classification.md` — refreshed

Added one entry: `utils/observability.py` → PROMOTED_CORE. 839 files
classified, no drift after refresh.

### `docs/refactor/route_fallback_inventory.md` — refreshed

Re-scanned via `scripts/audit/route_fallback_scan.py`. 51 routes; v1/v2
disposition columns populated; no v2 routes added in this phase.

### `domain/errors.py` — extended

10 net-new error codes + 9 net-new exception classes (Phase 1 v5,
ADR 0029). `UnsupportedCapability` extended with constrained
`dimension` field.

* `unsupported_region`         → `UnsupportedRegion`
* `missing_region_context`     → `MissingRegionContext`
* `unsupported_venue`          → `UnsupportedVenue`
* `missing_venue_context`      → `MissingVenueContext`
* `missing_currency_context`   → `MissingCurrencyContext`
* `missing_instrument_identity`→ `MissingInstrumentIdentity`
* `missing_translator`         → `MissingTranslator`
* `unsupported_provider`       → `UnsupportedProvider` (10-feature enum)
* `legacy_lane_blocked`        → `LegacyLaneBlocked`
* `entitlement_required`       → `EntitlementRequired`
* `unsupported_capability` extended with 9-dimension enum.

### `utils/observability.py` — new

Single canonical site for promoted-request structured-log emission.
Defines:

* `PromotedRequestContext` frozen dataclass (10 required labels).
* `build_context(...)` keyword-only constructor.
* `log_promoted_request(ctx, *, event)` — one log line per request.
* Defensive `assert_complete()` + warning when
  `legacy_lane=True` + `route="v2"`.

### `docs/api/v2/v2_errors.md` — new

Full taxonomy with per-code response shape, when emitted, and what
the client should do. Existing v3/v4 codes preserved alongside.

### `docs/observability/promoted_request_labels.md` — new

Canonical label spec. 10 labels, stability contract (additions via
new ADR; renames forbidden), test enforcement pointers.

### ADRs

* `0029-structured-market-context-errors.md` — accepted.
* `0030-promoted-request-observability-labels.md` — accepted.

### Contract tests

* `tests/contracts/test_v5_structured_errors_emitted.py` — 16 tests
  covering every new code, both `dimension` and `feature` enums, and
  collision-free distinct strings.
* `tests/contracts/test_v5_observability_labels_complete.py` — 7
  tests covering the canonical label set, default values, helper
  emission, the `legacy_lane=True` + `route="v2"` warning, and the
  contract that v1 lane guard never imports the helper.

## Out of scope deferred

* No changes to `domain/regions.py`, `domain/capabilities.py`,
  plugin loaders, route bodies, or feature gates beyond the error
  taxonomy expansion. Per-route adoption of the new error codes
  happens inline in the phases that touch those routes (e.g.,
  Phase 4 Sandbox uses `unsupported_provider`/`feature=sandbox`).
* No metrics backend introduced. Deferred to v6 explicitly.

## Gate results

| Step | Result |
|---|---|
| `uv run pytest tests/ -x --tb=short` | 2057 passed, 7 skipped, 0 failed |
| `uv run pytest -x tests/contracts/ tests/parity/ tests/compliance/` | 190 passed |
| `uv run python tests/parity/run_parity.py` | 8/8 passed |
| `uv run python scripts/audit/classify_files.py --check` | 839 files, no drift |
| `uv run python scripts/audit/route_fallback_scan.py` | 51 routes |
| `uv run python scripts/audit/symtoken_callers.py` | 0 PROMOTED_LEAK |
| `uv run python scripts/audit/canonical_vs_legacy_parity.py` | 13 pairs |
| `npm run lint:literals` | 253 files, 0 violations |
| `python -c "import app"` | OK |

All gates pass. Zero xfails added.

## v5 by the numbers (running total after Phase 1)

* **2 new ADRs** (0029, 0030).
* **23 new tests** (Phase 1).
* **1 new utility module** (`utils/observability.py`).
* **2 new docs** (`docs/api/v2/v2_errors.md`,
  `docs/observability/promoted_request_labels.md`).
* **2057 backend tests** total (was 2033 at v4 close; +24 net).
* **0 PROMOTED_LEAK rows** in SymToken caller audit.
* **0 frontend literal violations**.
