# v4 Phase 3 — Complete

* **Branch:** `refactor/v4-phase-3-region-data`
* **Merged:** to `dev` with `--no-ff`
* **Effort:** high

## Goal

Make region plugins authoritative for venues, sessions, calendars,
currencies, and symbol-display grammar. Cut over non-India calendar
data to `database.venue_schedule_repo` only.

## Gaps closed (from `v3_baseline_audit.md`)

* **Gap 11** — `database.symbol` and `database.token_db_enhanced`
  reads not classified across all callers. Re-confirmed: SymToken
  caller audit shows zero PROMOTED_LEAK rows; runtime + static AST
  import locks now also cover the calendar source
  (`database.market_calendar_db`).
* **Gap 16** — region plugin compliance harness. Mixin +
  per-region tests now exist (8 contracts × 4 regions = 32 tests).

## New contracts added

| File | Purpose |
|---|---|
| `tests/compliance/region_plugin_compliance.py` | `RegionComplianceMixin` — A through H contracts (metadata, timezone IANA, currency, venues, session templates, calendar exceptions, symbol_display, feature_flags). Mirrors `BrokerComplianceMixin`. |
| `scripts/seed_region_data.py` | Idempotent seeder — reads each region plugin and upserts venues + session templates + calendar exceptions into `instruments_repo` + `venue_schedule_repo`. CLI: `uv run python -m scripts.seed_region_data [--region <code>]`. |
| `tests/contracts/test_calendar_precedence.py` | Static AST contract: PROMOTED_CORE files must not import `database.market_calendar_db`. |
| `docs/adr/0024-calendar-precedence.md` | Documents the dual-source decision: legacy India keeps `market_calendar_db`; promoted reads `venue_schedule_repo`. |

## New tests added

| File | Tests |
|---|---|
| `tests/compliance/test_india_region_compliance.py` | 8 |
| `tests/compliance/test_us_region_compliance.py` | 8 |
| `tests/compliance/test_eu_region_compliance.py` | 8 |
| `tests/compliance/test_uk_region_compliance.py` | 8 |
| `tests/migrations/test_seed_region_data_idempotent.py` | 4 (clean run, idempotency, US tz seeded, EU/UK tz seeded) |
| `tests/venue_session/test_dst_promoted_venues.py` | 7 (6 promoted venues × DST boundaries, plus India DST-free) |
| `tests/domain/test_currency_completeness.py` | 9 (default currency × 4 regions, venue currency × 4 regions, first-class assertion) |
| `tests/contracts/test_calendar_precedence.py` | 1 (zero PROMOTED_CORE imports of `market_calendar_db`) |
| **Total** | **53 new tests** |

## Comprehensive testing (gate 2.6)

| Step | Result |
|---|---|
| `pytest -x tests/contracts/ tests/parity/ tests/compliance/` | 141 passed, 4 xfailed — 8s |
| `python tests/parity/run_parity.py` | 7/7 passed |
| `pytest tests/` | 1893 passed, 7 skipped, 4 xfailed — 158s |
| `npm run lint:literals` | 253 files / 0 violations |
| `python scripts/audit/classify_files.py --check` | 813 files / no drift |
| `python scripts/audit/route_fallback_scan.py` | 50 routes |
| `python scripts/audit/symtoken_callers.py` | 0 PROMOTED_LEAK rows |
| `python scripts/audit/canonical_vs_legacy_parity.py` | 13 pairs |

All gates pass.

## Files touched

* Created: 11 files (region compliance mixin + 4 per-region invocations,
  seeder, calendar precedence contract, ADR 0024, 3 new test files,
  this completion doc).
* Modified: 0 (Phase 3 is purely additive).

## Deferred follow-ups

* Identifier resolution matrix tests (per the v4 prompt's Phase 3 §
  3.5) — deferred to Phase 5 of v4 where instrument resolution is
  exercised end-to-end through the v2 read-side adapters. The
  identifier-kind enum + helper from v3 Phase 3a (ADR 0019) already
  cover the contract; what's missing is per-identifier integration
  coverage which Phase 5's mock-broker e2e expansion (Phase 11)
  brings together.
* Ambiguity handling (e.g., `VOD` ambiguous across XLON and another)
  — same; Phase 5/11 add the structured `instrument_ambiguous`
  response on the v2 dispatch path. The error code is already
  reserved (`ErrorCode.INSTRUMENT_AMBIGUOUS`).
* India calendar migration to `venue_schedule_repo` — out of v4 scope
  per ADR 0024; deferred to v5.
