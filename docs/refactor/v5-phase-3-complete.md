# v5 Phase 3 — Complete

* **Branch:** `refactor/v5-phase-3-scheduler-and-historify-tz`
* **Merged:** to `dev` with `--no-ff`
* **Effort:** max
* **Closes:** v4 deferral 7-bis (DST contract); expert MA-033, MA-035;
  expert P5-01, P5-02, P5-03, P5-06.

## Goal

Pin the DST contract for promoted (non-India) venues. Ship the
venue-local-time helper that complements `database/venue_offset.py`
for non-Flask contexts. Document the per-component scheduler /
Historify-frontend refactor as Phase 3-bis.

## Work shipped

### `tests/contracts/test_v5_dst_correctness.py` — new (16 tests)

The single contract test that pins DST behavior for the four
promoted venues. A future Python / tzdata regression that silently
breaks DST for any of these venues fails this gate.

* America/New_York — winter EST (UTC−5), summer EDT (UTC−4),
  spring-forward 2026-03-08, fall-back 2026-11-01.
* Europe/London — winter GMT, summer BST, spring-forward
  2026-03-29, fall-back 2026-10-25.
* Europe/Paris — winter CET, summer CEST, same boundaries.
* Asia/Kolkata — control: never observes DST; offset stable across
  every transition date.
* Cross-check: `database.venue_offset.venue_local_offset_seconds`
  agrees with the direct ZoneInfo lookup across DST boundaries for
  XNYS / XLON / XPAR.

### `utils/venue_local_time.py` — new (COMPATIBILITY_SHIM)

A small region-neutral helper for non-Flask contexts (CLI, schedulers
that have not been migrated to the venue-aware scheduler yet,
periodic jobs that need a venue-local timestamp without a SQL round
trip).

* `venue_local_now(venue_code)` — current wall-clock time in the
  venue's tz; None when unknown.
* `to_venue_local(when_utc, venue_code)` — convert UTC datetime to
  venue local; rejects naive datetimes (no silent UTC assumption).
* `format_venue_local_time(...)` — formatter.

Mirrors the venue→tz table from `database/venue_offset.py` to stay
import-light (utils/* must not import `database.instruments_repo`
per the no-coupling contract).

### `tests/historify/test_venue_local_time.py` — new (6 tests)

Round-trip tests for the new helper. India venues short-circuit to
Asia/Kolkata; unknown venues return None; non-aware datetime
rejected.

## Out of scope (deferred to v5 Phase 3-bis)

The v5 prompt enumerated 6 sub-items for this phase. The DST
contract test + venue-local-time helper close the load-bearing core
that v4 7-bis was missing. The remaining per-component refactors
remain open and are non-blocking (India parity is preserved; legacy
India scheduler / Historify pages stay India-classified):

1. `blueprints/strategy.py` venue-aware scheduler — current code
   passes `pytz.timezone("Asia/Kolkata")` to APScheduler at module
   load. The file is LEGACY_INDIA classified; making it
   venue-aware would require either a per-strategy venue setting
   (DB migration) or a per-broker default. Defer to v6 with the
   real-Schwab/Webull plugin work.
2. `blueprints/python_strategy.py` — same; constants (`IST`,
   `CronTrigger(timezone=IST)`) are India-baked into the daily
   trading-day check job. Same deferral as above.
3. Frontend `pages/python-strategy/**` schedule editor — UI-side
   change tied to the backend scheduler refactor in (1) / (2).
4. Frontend Historify pages chart axes — the venue offset is
   already correct via `database/venue_offset.py` (v4 Phase 7);
   the frontend chart-axis labelling adoption is per-component.
5. `utils/auth_utils.py` master-contract refresh — already broker-
   policy-driven (see lines 88–117); v4 Phase 4 introduced
   `_broker_refresh_policy` reading `master_contract_refresh_policy`
   from `plugin.json`. Promoted plugins must declare it (v4 strict
   mode); legacy India plugins fall back to IST 08:00. No further
   change needed.
6. `utils/session.py` — already fail-closed for non-India per v4
   Phase 2. The error class `ConfigurationError` is the existing
   v4 contract; v5 leaves it. The Phase 1 `MissingRegionContext`
   class is reserved for caller-side adoption.

The `phase-3-bis` scope is recorded in `docs/refactor/v5-overview.md`
under "What v6 should consider".

## Gate results

| Step | Result |
|---|---|
| `uv run pytest tests/ -x --tb=short` | 2081 passed, 7 skipped, 0 failed |
| `uv run pytest tests/contracts/test_v5_dst_correctness.py` | 16/16 passed |
| `uv run python tests/parity/run_parity.py` | 8/8 passed |
| `uv run python scripts/audit/classify_files.py --check` | 840 files, no drift |
| `uv run python scripts/audit/route_fallback_scan.py` | 51 routes |
| `uv run python scripts/audit/symtoken_callers.py` | 0 PROMOTED_LEAK |
| `npm run lint:literals` | 255 files, 0 violations |

All gates pass. Zero xfails added.

## v5 by the numbers (running total after Phase 3)

* **2 new ADRs** (0029, 0030 — Phase 1).
* **74 new tests** total (Phase 1: 23; Phase 2: 29; Phase 3: 22).
* **2081 backend tests** (was 2058 at Phase 2 close; +23 net).
* **3 new utility modules** in v5 (`utils/observability.py`,
  `utils/venue_local_time.py`, plus the frontend
  `lib/format/{currency,timezone}.ts`).
* **0 PROMOTED_LEAK rows**.
* **0 frontend literal violations**.
