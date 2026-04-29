# v6 Phase 1-bis — Complete (frontend per-component cleanup, partial)

* **Branch:** `refactor/v6-phase-1-bis-frontend-cleanup`
* **Branched from:** `dev` @ `88aab320` (HEAD: v6 Phase 5-bis merge)
* **Effort:** high — 6 of the 11 Phase 0 inventory components cleaned.

## Scope honesty (Q3 default)

CLAUDE.md says UI changes need browser verification. Per Q3 default,
this phase ships **component-test-only verification** — Vitest covers
the surface; an operator should do a manual browser pass on India
broker before going live. Tier-3/4 components (capability hooks, flow
defaults, strategy options grammar) **stay deferred** because they
touch hot trading paths where browser verification is non-negotiable.

## What shipped

### Tier 1 — operational dashboards (3 pages)

Replaced hardcoded `Asia/Kolkata` + `'en-IN'` locale with
`useVenueTimezone()` hook + `undefined` locale (browser default).
Display label `"(IST)"` becomes the dynamic `useVenueTimezoneLabel()`
value.

* `frontend/src/pages/HealthMonitor.tsx`
* `frontend/src/pages/monitoring/LatencyDashboard.tsx`
* `frontend/src/pages/monitoring/SecurityDashboard.tsx`

For India users: timestamp display still shows Asia/Kolkata + IST
label (capability-driven). For US/EU/UK users: dashboard shows the
correct venue timezone.

### Tier 2 — strategy display (3 components)

Replaced hardcoded `₹` + `'en-IN'` locale with `useFormatCurrency()`
hook. PayoffChart's Plotly hovertemplate string uses the new
`currencyDisplaySymbol(currency)` helper (added to
`@/lib/format/currency`) since Plotly templates are strings, not
React.

* `frontend/src/components/strategy-builder/PnLTab.tsx`
* `frontend/src/components/strategy-builder/PositionsPanel.tsx`
* `frontend/src/components/strategy-builder/PayoffChart.tsx`

### Helper module addition

* `frontend/src/lib/format/currency.ts` gained
  `currencyDisplaySymbol(currency)` — INR / USD / EUR / GBP / JPY /
  AUD / CAD / CHF / HKD / SGD symbol map. Called by Plotly chart code
  that can't use `Intl.NumberFormat`.

### Frontend allowlist shrunk

`frontend/scripts/literal_scan_allowlist.json` shrunk from **84 → 78
entries** (-6). The shrinks-only invariant
(`tests/contracts/test_v6_frontend_allowlist_shrinks.py`) confirms
the new allowlist is a strict subset of the Phase 1 baseline.

## What is deferred to Phase 1-bis-2 / v7

Five components from the Phase 0 inventory still on the allowlist:

* `src/hooks/useSupportedExchanges.ts` — central capability hook;
  null-caps→India fallback affects every consumer. **High blast
  radius** — needs browser verification.
* `src/lib/flow/constants.ts` + `components/flow/panels/ConfigPanel.tsx`
  — flow builder defaults; needs `/api/v2/regions/<code>/flow_defaults`
  client-side helper. **Touches flow execution.**
* `src/components/trading/PlaceOrderDialog.tsx` — order dialog
  product / exchange picker. **Touches every trading flow.**
* `src/pages/admin/MarketTimings.tsx` — needs region-plugin client.
* `src/pages/CustomStraddle.tsx` — Indian options grammar embedded
  (DDMMMYY, NIFTY/BANKNIFTY lots, 5.5h IST shift). India-only feature
  per ADR 0011; the literals are intentional but the timezone
  conversion can be cleaned up.
* `src/pages/python-strategy/{New,Schedule,Index}.tsx`,
  `src/pages/Historify*.tsx`, `src/pages/StrategyPortfolio.tsx` —
  scheduler-related; depends on Phase 2-bis venue-aware scheduler.

These should land per-PR with browser verification on a live India
broker.

## Comprehensive test gate (passed)

| Step | Result |
|---|---|
| `uv run pytest tests/ -x --tb=short` | **2613 passed, 7 skipped, 2 xfailed** in 4:00 (unchanged — frontend-only changes) |
| `uv run pytest -x tests/contracts/test_v4_closing_invariants.py tests/contracts/test_v5_closing_invariants.py tests/contracts/test_v6_closing_invariants.py` | **35 passed** |
| `uv run python tests/parity/run_parity.py` | **41/41** verify-mode harnesses |
| `uv run python tests/parity/run_parity.py --lane v1` | **11/11** v1-lane harnesses |
| `uv run python tests/parity/run_parity.py --lane v2` | **41/41** v2-lane harnesses |
| `uv run python scripts/audit/classify_files.py --check` | exit 0 — 879 files / no drift |
| `uv run python scripts/audit/route_fallback_scan.py` | 51 routes |
| `uv run python scripts/audit/symtoken_callers.py` | 0 PROMOTED_LEAK |
| `uv run python scripts/audit/canonical_vs_legacy_parity.py` | 13 pairs |
| `npm test -- --run` (frontend) | **160 passed across 15 files** |
| `npm run lint:literals` | exit 0 — 256 files / 0 violations |
| `tests/contracts/test_v6_frontend_allowlist_shrinks.py` | 4 passed (allowlist 78 ⊆ baseline 84) |

## Operator verification checklist (before going live)

For each cleaned page, manually verify on a live India broker:

1. HealthMonitor: "Last updated (IST):" timestamp matches IST.
2. LatencyDashboard / SecurityDashboard: timestamps in Indian time.
3. Strategy Builder PnL tab: amounts show `₹X,XXX.XX`.
4. Positions panel: same.
5. Payoff chart: hovertemplate shows `₹...`.

If any page renders unexpected currency / timezone for an India
broker, file an issue against this phase — the capability hook is
returning null when it shouldn't.

## Next phase

`v6-phase-2-bis-sandbox` — first of four per-surface dispatcher
migration sub-phases.
