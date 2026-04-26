# ADR 0024 — Calendar precedence (non-India)

* **Status:** accepted
* **Date:** 2026-04-26
* **Phase:** v4 Phase 3
* **Supersedes:** none

## Context

Two calendar data sources exist in the repo:

* `database/market_calendar_db.py` — the legacy India source. Stores
  Indian exchange holidays (NSE / BSE / NFO / BFO / CDS / MCX). Used
  by the legacy lane today; parity-protected.
* `database/venue_schedule_repo.py` — the v4 promoted lane source.
  Stores venue-keyed session templates and calendar exceptions.
  Populated from region plugin metadata via
  `scripts/seed_region_data.py`.

Phase 3 v4 of the market-agnostic refactor seeds the venue schedule
tables for India / US / EU / UK from the four region plugins. The
question this ADR answers: which source is authoritative for which
broker?

## Decision

**Promoted (non-India) paths read calendar data from
`database/venue_schedule_repo` only.** They must not import
`database/market_calendar_db` at module load time. The runtime import
lock and a new static AST contract test enforce this.

**Legacy India paths read from `database/market_calendar_db` as
today** (parity-protected). Phase 3 of v4 does not migrate India
calendar data to the venue schedule repo — that would risk parity
regressions. A future Phase 4-bis (or v5) handles the India
migration after one full release of held parity.

## Consequences

* Non-India brokers (Alpaca, Schwab-mock, Webull-mock, future real
  Schwab/Webull) get DST-correct, region-pluggable calendar data
  out of the box.
* India deployments are bit-identical — `market_calendar_db` is
  unchanged; the new `venue_schedule_repo` rows for India are
  populated by the seeder but India read paths do not consult them.
* Adding a new region (EU, UK pilot) is purely additive: write a
  region plugin, run the seeder, and the new region's venues +
  sessions + calendars are available to the promoted lane.

## Enforcement

* `tests/contracts/test_calendar_precedence.py` — static AST scan
  asserting no PROMOTED_CORE file imports
  `database.market_calendar_db`.
* `tests/contracts/test_promoted_imports_runtime.py` — already covers
  the runtime import lock (extends the broader promoted lane).
* `tests/migrations/test_seed_region_data_idempotent.py` — confirms
  the seeder writes the expected venues and is idempotent.
* `tests/venue_session/test_dst_promoted_venues.py` — DST-correct
  conversion across the spring-forward and fall-back boundaries for
  every promoted venue (XNYS, XNAS, ARCX, XPAR, XETR, XLON).

## Cross-references

* ADR 0023 — v4 scope
* ADR 0007 — region plugin schema v2
* ADR 0009 — TZ decoupling and holiday migration
* `docs/refactor/v3_baseline_audit.md` — gap 16 (region-plugin
  compliance harness) closed in v4 Phase 3.
