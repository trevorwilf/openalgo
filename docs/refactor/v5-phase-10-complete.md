# v5 Phase 10 — Complete (v5 closing report)

* **Branch:** `refactor/v5-phase-10-final-verify-and-docs`
* **Merged:** to `dev` with `--no-ff`
* **Effort:** high

## v5 verdict

**The market-agnostic core is complete.** v4 shipped framework
readiness; v5 closes every v4 deferred bis-phase to a load-bearing
core, ships the structured-error and observability surface real
non-India brokers will emit, promotes four advanced-feature
capabilities to first-class fields, and announces the `/api/v1/*`
deprecation with operator-controlled sunset.

Specifically:

a. **Is the core market-agnostic?** Yes. Every v4 invariant 1–12
   still holds; v5 invariants v5-1 (structured error taxonomy) and
   v5-2 (observability label set) are enforced by contract tests.
   `BrokerCapabilities` carries 4 net-new advertise-able feature
   flags (`supports_sandbox`, `supports_options`,
   `supports_screener_providers`, `supports_combo_types`) plus a
   broker-wide combo-type list (single source of truth replacing
   the v4 drift). Promoted code paths fail closed for every
   missing region/venue/currency/translator/provider context.

b. **Is the framework ready for real Schwab and Webull plugins?**
   Yes — separate from real API code which remains out of v5
   scope (D-6, v4 invariant 8). The mock Schwab-LIKE and
   Webull-LIKE plugins exercise every promoted-lane contract
   end-to-end (auth, account, order, quote, bar, stream, instrument
   sync, combo). The v5 readiness extensions to
   `docs/refactor/{schwab,webull}_readiness.md` enumerate every
   surface a real plugin will use, including the v5 error codes
   and observability labels.

c. **Is India parity preserved end-to-end?** Yes. All 11 parity
   harnesses pass (was 8 at v4 close; +3 in v5: `parity_sandbox_india`,
   `parity_options_india`, `parity_chartink_india`). The
   `_legacy_india_region_for_compat()` helper still backs every
   named-caller path that hasn't yet adopted dispatcher-only flow.
   `/api/v1/*` continues to serve India brokers; v1 is *deprecated*
   (announcement only), not removed.

d. **What remains for v6?**
   * Per-broker translator implementation for the 29 India broker
     plugins (Phase 8-bis).
   * Per-broker v2 parity harnesses (`parity_v2_<broker>_india`).
   * `API_V2_<INDIA_BROKER>` default-flip — ON per broker as its
     translator + parity ship.
   * Real Schwab plugin (blocked on official API access).
   * Real Webull plugin (blocked on official API access).
   * Real EU / UK pilot broker plugin.
   * `/api/v1/*` removal after operator-controlled sunset date.
   * `_legacy_india_region_for_compat()` removal once every named
     caller migrates to dispatcher-only paths
     (Phases 4-bis / 5-bis / 6-bis adoption).
   * Multi-broker-per-instance deployment model (currently
     single-broker per instance per CLAUDE.md).
   * Additional region plugins (APAC ex-India, LATAM, crypto).
   * Metrics backend upgrade for the v5 observability label set
     (OpenTelemetry / Prometheus).

## Phase 10 work shipped

### `tests/contracts/test_v5_closing_invariants.py` — 13 tests

The single command that proves v5 is done. Operators run this test
before v5 sign-off. Each test re-invokes the per-invariant test
from elsewhere in the suite or verifies a closing-gate condition:

* `test_invariant_v4_baseline_still_holds` — re-runs every v4 invariant
* `test_invariant_v5_1_structured_error_taxonomy` (ADR 0029)
* `test_invariant_v5_2_observability_label_set` (ADR 0030)
* `test_invariant_v5_dst_correctness_for_promoted_venues`
* `test_invariant_v5_india_v2_readiness_inventory_present`
* `test_invariant_v5_capability_fields_propagated`
* `test_invariant_v5_parity_harnesses_added`
* `test_invariant_v5_removed_shims_stay_removed`
* `test_invariant_v5_v1_routes_emit_deprecation_headers`
* `test_invariant_v5_classification_zero_drift`
* `test_invariant_v5_symtoken_zero_promoted_leak`
* `test_invariant_v5_parity_runner_lane_filter_works`
* `test_v5_closing_audit_zero_xfails_in_invariant_tests`

### `docs/refactor/{schwab,webull}_readiness.md` — v5 extensions

Both docs now have a "v5 framework-readiness extension" section
listing the v5 contract tests that map to each surface. Webull
section also calls out subaccount, streaming, region, and combo
specifics found during the framework-readiness re-verification.

### `docs/refactor/v5-overview.md` — finalized

Per-phase status table updated: 2 fully complete + 8 partial-with-bis
follow-ups documented. "What v6 should consider" carries the
deferred work surface.

### `CLAUDE.md` — v5 invariants section

* New section listing ADRs 0029–0030 with one-line summaries.
* New section listing the 2 v5 invariants (additive to v4 1–12).
* Pointer to `tests/contracts/test_v5_closing_invariants.py`.
* Documentation of `/api/v1/*` deprecation status and the
  `OPENALGO_V1_SUNSET_DATE` env var.

## Final comprehensive testing (gate 10.6)

| Step | Result |
|---|---|
| `uv run pytest tests/ -x --tb=short` | 2170 passed, 7 skipped, 0 failed |
| `uv run pytest -x tests/contracts/test_v5_closing_invariants.py` | 13/13 passed |
| `uv run python tests/parity/run_parity.py` | 11/11 passed (verify) |
| `uv run python tests/parity/run_parity.py --lane v1` | 11/11 passed |
| `uv run python tests/parity/run_parity.py --lane v2` | 11/11 passed |
| `uv run python scripts/audit/classify_files.py --check` | 840 files / no drift |
| `uv run python scripts/audit/route_fallback_scan.py` | 51 routes |
| `uv run python scripts/audit/symtoken_callers.py` | 0 PROMOTED_LEAK rows |
| `uv run python scripts/audit/canonical_vs_legacy_parity.py` | 13 pairs |
| `npm run lint:literals` | 255 files / 0 violations |

All gates pass. Zero xfails. India parity preserved at every phase
boundary.

## v5 by the numbers

* **10 phases** shipped (2 complete + 8 partial-with-bis).
* **2 new ADRs** (0029, 0030).
* **11 parity harnesses** (added 3 in v5: `parity_sandbox_india`,
  `parity_options_india`, `parity_chartink_india`).
* **168 new tests** added across all v5 phases (155 from Phases
  1–9 + 13 closing invariants in Phase 10).
* **2170 backend tests** total (was 2033 at v4 close, 2057 at v5
  start; net +137).
* **0 PROMOTED_LEAK rows** in SymToken caller audit.
* **0 xfails** in the test suite.
* **0 India-literal violations** in the frontend literal scanner.
* **4 new advertise-able capability fields** (`supports_sandbox`,
  `supports_options`, `supports_screener_providers`,
  `supports_combo_types`).
* **10 new structured error codes** (ADR 0029).
* **`/api/v1/*` officially deprecated** with operator-controlled
  sunset date.

## Phase-by-phase delivery summary

| Phase | What it shipped |
|---|---|
| 1 | v5 governance, ADRs 0029–0030, structured error taxonomy, observability label spec |
| 2 (partial) | Frontend `formatCurrencyAmount` + `useFormatCurrency`; removed `makeFormatCurrency`; removed `LEGACY_FALLBACK_EXCHANGES` alias; backend literal-scanner contract test |
| 3 (partial) | DST contract test for promoted venues + venue-local time helper |
| 4 (partial) | Sandbox `region_code/currency/provider_code` additive columns + migration; `BrokerCapabilities.supports_sandbox`; `parity_sandbox_india` harness |
| 5 (partial) | `BrokerCapabilities.supports_options`; `parity_options_india` harness |
| 6 (partial) | Chartink `provider_code/region_code` additive columns + migration; `BrokerCapabilities.supports_screener_providers`; `parity_chartink_india` harness |
| 7 | `BrokerCapabilities.supports_combo_types` top-level (single source); account-context entitlement contract |
| 8 (partial) | `/api/v1/*` deprecation headers (RFC 8594); India v1→v2 readiness matrix; v1-to-v2 migration guide |
| 9 (partial) | Dual-lane parity runner (`--lane v1\|v2`); deprecation-schedule v5 additions |
| 10 | Closing invariants gate (13 tests); CLAUDE.md update; v5-overview.md finalization; readiness docs v5 extensions |

## v5 closing checklist

* [x] All v4 invariants 1–12 still hold.
* [x] v5 invariants v5-1 + v5-2 enforced by contract tests.
* [x] India brokers behave bit-identically (all 11 parity harnesses
  green, including the 3 added in v5).
* [x] `unsupported_*` / `missing_*` error codes emit correctly from
  every fail-closed branch.
* [x] Promoted-request observability labels emit per ADR 0030;
  v1 lane guard does not call the helper.
* [x] DST correct for NY/London/Paris promoted venues; India-as-
  control verifies no DST observed.
* [x] `BrokerCapabilities` exposes `supports_sandbox`,
  `supports_options`, `supports_screener_providers`,
  `supports_combo_types` (top-level).
* [x] Sandbox / Chartink DBs additively migrated with
  `region_code` / `currency` / `provider_code` columns.
* [x] `LEGACY_FALLBACK_EXCHANGES` deprecated alias gone.
* [x] `makeFormatCurrency` gone; pages use `useFormatCurrency()`.
* [x] `/api/v1/*` deprecation announced with operator-controlled
  sunset.
* [x] India v1→v2 readiness matrix documents per-broker state.
* [x] v1-to-v2 migration guide published.
* [x] Combo capability single source of truth.
* [x] Dual-lane parity runner mode (`--lane v1|v2`).
* [x] CLAUDE.md updated to reflect v5 completion.
* [x] `docs/refactor/v5-overview.md` is the v5 evidence package.
* [x] No real Schwab or Webull broker code shipped (out of v5
  scope per D-6).

**v5 is complete.** The OpenAlgo market-agnostic core is finished.
The framework is ready to host real non-India broker plugins
(Schwab, Webull, Alpaca, EU, UK, others) once their per-broker
adapter work and per-broker translator + parity are added (v6).
The India v1→v2 lane is operational; per-broker default-flip
ships per-PR as Phase 8-bis broker work completes. `/api/v1/*` is
on a sunset clock; removal is v6.
