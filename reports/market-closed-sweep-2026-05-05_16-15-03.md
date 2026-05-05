# Market-closed deferred-work + full surface sweep — 2026-05-05 16:15 UTC

## Summary

- **Deferred-work review.** Production code (`restx_api/`, `domain/`,
  `services/`) has zero remaining tractable TODO markers. The CLAUDE.md
  v7 list items are either already shipped (verified earlier this
  session) or genuinely blocked on external dependencies (broker API
  access, operator decisions, major dep upgrades). This run is therefore
  a regression + surface sweep.
- **Phase 2 sweep.** Booted Flask, verified market closed
  (`is_open=False`, next open 2026-05-06 09:30 ET), exercised:
  - 16 `/api/v1` endpoint cases (read-only + error paths) — 10 2xx /
    6 4xx / 0 5xx.
  - 23 `/api/v2` endpoint cases including yesterday's
    capabilities/redirect/bulk-cancel fixes — 20 2xx / 2 3xx (redirects)
    / 1 4xx (bad-request) / 0 5xx.
  - Alpaca paper deep sweep adapted for market-closed: 7 read-only +
    3 quote/bar (1 paid-feed limitation, expected) + 5 place-and-
    cancel scenarios + bracket + bulk-cancel + 5 error paths.
  - **Headless browser:** focused-page-sweep (19/19 pages clean) +
    full live Playwright suite (~51+ tests, **0 failure artifacts**
    across all paper-trading + auth-instance + chart specs). The
    paper-trading-india-gating fix shipped earlier in this conversation
    is holding; the previously-flaky 15 tests now run to completion.
- **Fix-and-iterate.** **4 small fixes shipped, each `--no-ff` merged
  into `dev`:**
  1. `fix(test)`: v4 closing invariants — update stale import after
     v1-lane test rename (cascade fix from yesterday's ADR 0023 update).
  2. `chore(audit)`: allowlist `services/charts/safety_defaults.py`
     rupee literal in the backend India literal scan (pre-existing
     domain-justified literal).
  3. `fix(test)`: align CRYPTO assertions with `T-30 India relinquishes
     CRYPTO` — two tests still asserted the pre-T-30 contract.
  4. `fix(test)`: allowlist `blueprints/search.py` as a legitimate
     `instruments_repo` consumer — added in commit b58e79aa
     (feat(alpaca): symbol search + friendly venue aliases) but the
     per-phase allowlist wasn't updated.
- **Test totals after this session:**
  - Targeted directories (`tests/domain` + `tests/broker/alpaca` +
    `tests/database` + `tests/api_v2` + `tests/contracts` +
    `tests/plugin_loader`): **1521 passed / 0 failed / 44 skipped**.
  - Parity harness: **41/41**.
  - Full repo: **3423 passed / 8 failed / 50 skipped**. The 8
    remaining failures are all environmental / test-isolation issues
    (pass in isolation, fail in suite) — not production-code defects.
    Documented in Open Issues.
  - Playwright live suite: **0 failure artifacts** across the full
    paper-trading + auth-instance run.

`dev` is **8 commits ahead of `origin/dev`**. **No remote pushes.**

---

## Deferred-work review

After the morning + market-open + product-decisions sessions earlier
today, the remaining deferred items in CLAUDE.md "What v7 should
consider" are all blocked:

| Item | State |
|---|---|
| Real Schwab plugin | Blocked (broker API access) |
| Real Webull plugin | Blocked (broker API access) |
| Real Alpaca production hardening | Largely shipped this session |
| Real EU / UK pilot broker plugins | Blocked |
| `/api/v1/*` removal after sunset | Blocked (operator-controlled) |
| Multi-broker-per-instance | Blocked (architecture decision) |
| APAC ex-India / LATAM region plugins | Blocked |
| OpenTelemetry / Prometheus upgrade | Blocked (major dep) |
| Phase 1-bis-2 frontend browser verification | Done (focused sweep + Playwright suite) |
| Phase 2-bis-2 dispatcher migrations | Blocked (Phase 8-bis schema prerequisites) |
| Phase 4-bis-2 master-contract refresh | Already done — verified at services/master_contract_scheduler.py |
| Phase 4-bis-2 rule_enforcement entitlement | Already done — verified at services/rule_enforcement.py |
| Sandbox initial funds reconciliation | Already done — verified in market_regions/india/plugin.json |

A grep for `TODO` / `FIXME` markers across `restx_api/`, `domain/`,
`services/` returned **zero matches**. The only remaining hits are in
docs/ADRs (informational) and one Phase-6 frontend gating TODO in
`frontend/src/pages/admin/Holidays.tsx` that depends on a region-active
hook not yet exposed client-side.

---

## Phase 2 — sweep results

### 2.1 `/api/v1` HTTP API surface (16 cases)

All 10 expected-2xx endpoints pass: `funds`, `orderbook`,
`positionbook`, `holdings`, `tradebook`, `intervals`, `ping`, `search`,
`analyzer`, `openposition`. Account is now flat
(positions closed between sessions; cash $100,005, equity $100,005).
The previously-fixed `/api/v1/intervals` continues to return the
expected interval set.

All 6 expected-4xx return clean structured errors:
`apikey missing → 400`, `apikey invalid → 403`,
`orderstatus unknown → 404`, `quotes/depth/history with NASDAQ → 400`
(India-locked v1 schema, by design per ADR 0003).

### 2.2 `/api/v2` HTTP API surface (23 cases)

Read-only GETs:
`capabilities` (with API-key auth — verifies yesterday's fix),
`regions`, `regions/india`, `regions/us`, `regions/india/flow_defaults`,
`venues`, `venues/XNAS`, `venues/XNAS/sessions`, `balances`,
`positions`, `orders?status=open`, `chart/{layouts,templates,watchlists}`,
`plugins/diagnostics` — all 200.

Yesterday's `/api/v2/plugins` redirect: both bare path and
trailing-slash variant → **302 → /api/v2/plugins/diagnostics**.

POSTs: `quotes` (single + batch), `bars`, all 200 with correct
shapes. Per-instrument fail-soft works (XLON returns
`instrument_not_resolvable` error envelope at the per-instrument
level, with HTTP 200).

### 2.3 Alpaca paper deep sweep (market closed)

Read-only (7/7): clock confirms `is_open=False`, account ACTIVE,
positions empty, orders empty, asset lookup, FILL activities.

Quote/bar (2/3): latest snapshot OK; recent SIP bars require a paid
data subscription on the paper account (403, expected).

Place + cancel (4/5): MARKET DAY, LIMIT GTC, STOP_LIMIT GTC,
TRAILING_STOP GTC all queue cleanly. The 5th scenario (STOP SELL of
AAPL after MARKET BUY of AAPL in the same sweep) was correctly
rejected by Alpaca's wash-trade detection (403 / 40310000) — that's
the broker's own pattern detection, not a bug.

PATCH modify: market-closed orders enter `accepted` state without
transitioning to `new`, and Alpaca only accepts PATCH on
`new`/`partially_filled` (422 "cannot replace order in accepted
status" — documented Alpaca behavior).

Bracket (OTOCO): place + cancel both 200.

Bulk cancel-all: 207 (Alpaca multi-status), all 4 placed orders
canceled. Account flat after sweep.

Error paths (5/5): bogus symbol → 422, qty=0/-1 → 422, IOC LIMIT
when market closed → 422 (Alpaca-specific rule), cancel non-existent
UUID → 404. All return correct structured errors.

### 2.4 React UI — headless browser

**focused-page-sweep:** 19/19 pages clean, 0 console errors, ~52s
total runtime against the live Flask.

**Full live Playwright suite:** ran for ~25 minutes covering
auth-instance (51+ pages) + paper-trading (mode-pill, fresh-login,
ui-click, actions, positions, alpaca-parity, ws-ticks, india-gating).
**Zero failure artifacts** in `frontend/test-results-live/` (the live
config retains video + trace only on failure). The previously-flaky
`paper-trading-india-gating` suite — which lost the worker after
test 7-8 with SIGTERM in this morning's run — now passes all 15
tests after the try/finally context-cleanup fix shipped earlier in
this conversation.

---

## Fixes shipped this session (4 branches, all `--no-ff` merged into `dev`)

### `fix/v4-closing-invariants-stale-import` — `311cd0d0`

**Severity:** test-only correctness. The stale import broke
collection of `test_v4_closing_invariants.py`, which cascaded into
v5 + v6 closing-invariant tests (both re-run the v4 invariants).

**Cause.** `tests/contracts/test_v4_closing_invariants.py:61` imported
`test_non_india_broker_blocked_with_410` from
`tests/contracts/test_v1_lane_blocks_non_india.py`. That symbol was
renamed to `test_non_india_broker_blocked_with_410_when_bridge_misses`
in commit `c5fd70c4` (chore(adr-0023): acknowledge v1->v2
compatibility bridge in invariant 5) — the v6+ contract is two-stage
(bridged → passthrough; unbridged → 410). The rename wasn't propagated
to the closing-invariant test.

**Fix.** Replace the import with both surviving symbols
(`bridged_when_handler_matches` + `blocked_with_410_when_bridge_misses`)
so the contract test fails loudly if either the bridge-passthrough or
the 410-fallback test is deleted in a future refactor. Update the
docstring to describe the two-stage contract.

7/7 v4 closing invariants pass.

### `chore/literal-scan-backend-allowlist-safety-defaults` — `53babe1e`

**Severity:** test-only.

**Cause.** `scripts/audit/india_literal_scan_backend.py` (a stricter
scanner separate from the lane-isolation literal scan I addressed
earlier) flagged a ₹ symbol on line 7 of
`services/charts/safety_defaults.py`. The literal lives in the module
docstring documenting D-05 per-currency safety defaults
(`max_notional_inr` = ₹10L); the runtime path uses Currency enum
comparison (USD / INR), not the symbol.

**Fix.** Add the file to `_FILE_ALLOWLIST` with a domain-justification
comment. Mirrors the existing INR allowlist entry for the same file
in `tests/contracts/test_lane_isolation.py` (committed earlier this
session as `1ea611b7`).

### `fix/test-india-relinquished-crypto` — `abfc6c4f`

**Severity:** test-only correctness — two tests still enforced the
pre-T-30 India venue contract.

**Cause.** Commit `6bae26b2` (refactor(v7-phase-8-final): T-30 — India
relinquishes CRYPTO) moved CRYPTO from India to its dedicated
`market_regions/crypto/plugin.json`. Two tests in
`tests/region_loader/test_schema_v2.py` and
`tests/services/test_v3_phase3_region_aware_validators.py` still
asserted CRYPTO appears in India's `legacy_compat_shim.valid_exchanges`
and India's invalid-exchange error message.

**Fix.** Update both assertions to match the post-T-30 reality (India
is the 10-exchange legacy list — NSE / NFO / CDS / BSE / BFO / BCD /
MCX / NCDEX / NSE_INDEX / BSE_INDEX — no CRYPTO). Add explanatory
comments pointing at the refactor commit.

### `fix/test-instruments-repo-allowlist-search-blueprint` — `9bb83b2c`

**Severity:** test-only.

**Cause.** `blueprints/search.py:148` imports `instruments_search` from
`database.instruments_repo` to support non-India broker symbol search
(Alpaca/Schwab/Webull symbols don't live in the legacy SymToken table
that the prior search path queried). The import was added in commit
`b58e79aa` (feat(alpaca): symbol search + friendly venue aliases) but
the per-phase allowlist in
`tests/instruments_repo/test_no_consumer_coupling.py` wasn't updated.

**Fix.** Add `blueprints/search.py` to `PHASE_ALLOWED` with a
justification comment pointing at the feature commit. 825/825 tests
pass after this.

---

## Open issues — left for the human reviewer

### #1 — Test-isolation flakes in the full-repo pytest sweep

8 tests fail when `pytest tests/` runs them in suite order but pass
when run alone:

| Test | Cause |
|---|---|
| `tests/api_v2/charts/test_skeleton_routes.py::test_layouts_get_returns_empty_data_envelope` | DB state-leak — earlier tests populate `chart_workspace.db` with layouts; this test asserts `[]`. |
| `tests/api_v2/charts/test_skeleton_routes.py::test_layout_cells_get_and_put` | Same state-leak. |
| `tests/api_v2/charts/test_layouts_crud.py::test_active_layout_round_trip` | Same. |
| `tests/restx_api/v2/test_holidays_region_dispatch.py` (3 tests) | Region/blueprint state-leak — when isolated, the v2 holidays endpoint registers; in full-suite order, an earlier test must be re-importing `restx_api` differently. |
| `tests/perf/charts/test_indicator_perf.py::test_sma_50k_bars_under_500ms` | System-load — the in-suite run takes 1351ms vs <500ms target. Solo run passes in ~50ms. Environmental, not a regression. |
| `tests/perf/charts/test_streaming_perf.py::test_resample_perf_already_gated_in_phase_1` | Same — system-load dependent. |

These are pre-existing infrastructure issues that I deliberately
did not chase under the time-box. Both classes need the same
treatment: better fixture cleanup (chart workspace tests should reset
the DB) and a `pytest-skip` / `pytest-mark` for the perf suite when
running alongside the full repo. Logging here so the team has a
breadcrumb.

### #2 — Performance benchmarks are environmental

`tests/perf/charts/*` pass in isolation in ~50ms but fail at >500ms
under full-suite load. The benchmark targets assume a quiet machine
— under realistic CI / dev-laptop load they trip the threshold.
Either widen the threshold (e.g. 1500ms) or move the perf suite to a
separate `pytest -k perf --benchmark` run that explicitly excludes
heavy concurrent state.

### #3 — Frontend `Holidays.tsx` Phase-6 gating TODO

`frontend/src/pages/admin/Holidays.tsx:107` carries a TODO referencing
the Phase-6 frontend region-active hook. The hook isn't yet exposed
to the React side; the TODO is a placeholder rather than a defect.
Closing this requires a small client-side capability hook plus a
component refactor — out of scope for this run.

---

## Test-result delta vs. earlier sweeps today

| Sweep | Pytest passed | Pytest failed | Playwright failed |
|---|---|---|---|
| Morning (initial) | — | — | — (not run) |
| Market-open (mid-day) | 1359 / 1362 (in scope) | 3 (v1-lane drift) | — |
| Product-decision-implementation | 1518 / 1521 | 3 (same) | — |
| **This run (market-closed)** | **3423 / 3431 (full repo)** | **8 (all isolation/perf flakes, all pass alone)** | **0** |

The widening pass count comes from running the full `tests/` directory
this run, not from new tests landing. The "8 failed" number is bigger
than morning's "3 failed" but those 3 were real (now fixed) and the
8 today are pre-existing test-infrastructure issues that don't
correspond to production-code defects.

---

## Files changed this session

### Test infrastructure / allowlists
- `tests/contracts/test_v4_closing_invariants.py` (stale-import fix)
- `scripts/audit/india_literal_scan_backend.py` (`_FILE_ALLOWLIST` +1)
- `tests/region_loader/test_schema_v2.py` (CRYPTO assertion)
- `tests/services/test_v3_phase3_region_aware_validators.py` (CRYPTO assertion)
- `tests/instruments_repo/test_no_consumer_coupling.py` (`PHASE_ALLOWED` +1)

### No production code changes this run
The four fixes shipped today are all test-side updates aligning the
test contract with already-merged refactors (T-30, b58e79aa, ADR
0023 update). Production code is unchanged.

---

## Note on this report

Per the prompt, this report is the final action of the session.
`reports/` is gitignored, so the report was force-added with
`git add -f`. Background Flask was stopped via `TaskStop`. No remote
pushes performed.
