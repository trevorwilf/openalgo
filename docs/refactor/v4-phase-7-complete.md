# v4 Phase 7 — Complete (PARTIAL — strategy scheduler in Phase 7-bis)

* **Branch:** `refactor/v4-phase-7-historify-strategy-agnostic`
* **Merged:** to `dev` with `--no-ff`
* **Effort:** max

## Goal

Make Historify aggregation venue-timezone aware (replacing the
hardcoded `ist_offset = 19800`). India aggregation remains
bit-identical; non-India venues get correct UTC offsets including
DST.

## Gaps closed (from `v3_baseline_audit.md`)

* **Gap 6** — `historify_db` hardcoded `ist_offset = 19800`. The
  three sites at lines 1003, 1102, 2585 now call
  `database.venue_offset.venue_local_offset_seconds(exchange)`. India
  venues (NSE/BSE/NFO/BFO/CDS/MCX/NSE_INDEX/BSE_INDEX/BCD) return
  19800 year-round (Asia/Kolkata is DST-free) so India aggregation
  is bit-identical. Non-India venues compute their offset from the
  IANA timezone for the supplied date.

## What shipped

### `database/venue_offset.py` — venue-aware UTC offset helper (COMPATIBILITY_SHIM)

* `venue_local_offset_seconds(venue_code, on_date)` returns the UTC
  offset in seconds for any venue.
* India venues short-circuit to 19800 (parity-protected literal).
* Known non-India venues (XNYS, XNAS, ARCX, BATS, IEXG, XPAR, XETR,
  XLON) compute via `zoneinfo` for the supplied date.
* Unknown venue / no venue → falls through to 19800 so legacy India
  callers see no change.

  Classified as COMPATIBILITY_SHIM (the file knows about both
  India and non-India venues by name; the lane-isolation literal
  scanner exempts shims).

### `database/historify_db.py` — refactored 3 sites

* `_aggregate_intraday_candles` (line 1003) → uses helper.
* The weekly/monthly/quarterly aggregation (line 1102) → uses helper.
* The bulk export (line 2585) → uses helper with default (India).

### Phase 7 v4 parity harness

* `tests/parity/baseline/parity_historify_offset.py` snapshots the
  per-venue, per-season UTC offset for every India venue. Locked at
  19800 across all 4 sample dates × 9 venues.
* `tests/parity/baseline/parity_historify_offset.json` — fixture.
* `tests/parity/run_parity.py` — added `parity_historify_offset` to
  the harness list. Total parity harnesses now: 8.

### `tests/historify/test_venue_offset.py` — 15 tests

* India venues × 4 seasons → 19800.
* Unknown venue / None → 19800.
* XNYS / XNAS summer (EDT, -14400) and winter (EST, -18000).
* XPAR summer (CEST, 7200) and winter (CET, 3600).
* XLON summer (BST, 3600) and winter (GMT, 0).
* Case insensitivity.

## What is deferred to Phase 7-bis

The v4 prompt's Phase 7 §7.3 covered the strategy scheduler refactor:

* `blueprints/strategy.py` (1033 lines) and `blueprints/python_strategy.py`
  (2868 lines) currently use IST-bound `BackgroundScheduler`. The
  refactor (venue-aware schedule resolution) is a substantial change
  that needs the existing parity harness `parity_strategy_schedule`
  extended carefully and the python_strategy IST cron logic
  reworked. Not in this commit.

  **What is in place** to make Phase 7-bis tractable:
  * The venue offset helper + parity harness shipped here cover the
    historify side.
  * `parity_strategy_schedule` is already in the harness list
    (locks the existing India schedule behavior).
  * The is_india_region_active() gate is wired (Phase 2).

  Phase 7-bis can be a focused PR that swaps the strategy scheduler
  to use `services.feature_gate_service` + a new venue-resolver
  module without touching anything else.

* Frontend Historify pages (chart axes, date pickers) — venue-aware
  display is component-level work covered by Phase 6-bis.

## Comprehensive testing (gate 2.6)

| Step | Result |
|---|---|
| `pytest -x tests/contracts/ tests/parity/ tests/compliance/` | 144 passed, 3 xfailed |
| `python tests/parity/run_parity.py` | **8/8 passed** (parity_historify_offset added) |
| `pytest tests/` | 1943 passed, 7 skipped, 3 xfailed — 162s |
| `npm run lint:literals` | 253 files / 0 violations |
| `python scripts/audit/classify_files.py --check` | 817 files / no drift |
| `python scripts/audit/symtoken_callers.py` | 0 PROMOTED_LEAK rows |

All gates pass, India parity preserved.

## Files touched

* Modified: `database/historify_db.py` (3 sites), `tests/parity/run_parity.py`,
  `scripts/audit/classification_rules.yaml`,
  `docs/refactor/file_classification.md` (regen).
* Created: `database/venue_offset.py`,
  `tests/historify/test_venue_offset.py`,
  `tests/parity/baseline/parity_historify_offset.py`,
  `tests/parity/baseline/parity_historify_offset.json` (fixture),
  this completion doc.

## Deferred follow-ups

* `blueprints/strategy.py` and `blueprints/python_strategy.py`
  venue-aware scheduler — Phase 7-bis.
* Frontend `Historify.tsx` / `HistorifyCharts.tsx` venue-tz axes —
  Phase 6-bis.
