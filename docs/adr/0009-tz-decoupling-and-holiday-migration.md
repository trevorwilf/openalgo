# ADR 0009 — Auth/session TZ decoupling and holiday data migration

Status: accepted (Phase 4, market-agnostic v2)
Date: 2026-04-25

## Context

Prior CC passes built the venue/session infrastructure
(`database/venue_schedule_repo.py`, `services/venue_session_service.py`,
`upgrade/migrate_venue_schedule.py`,
`upgrade/seed_venue_schedule_defaults.py`) but stopped short of these
last-mile pieces:

* the Docker image still set `TZ=Asia/Kolkata` and ran
  `ln -fs /usr/share/zoneinfo/Asia/Kolkata /etc/localtime` at build,
  which silently shaped every timestamp in non-IST deployments;
* `utils/session.py` and `database/auth_db.py` hardcoded
  `pytz.timezone("Asia/Kolkata")` for session expiry math;
* `utils/auth_utils.py` defaulted master-contract cutoff to 08:00 IST
  for any non-crypto broker, with no per-broker override path;
* `market_holidays` / `market_holiday_exchanges` rows had no
  representation in the new `venue_calendar_exceptions` table;
* `/api/v2` had no endpoint that exposed the venue catalog.

This ADR closes the gap.

## Decision

### Container TZ

`Dockerfile` sets `TZ=UTC` and removes the
`ln -fs /usr/share/zoneinfo/Asia/Kolkata /etc/localtime` step.
Operators running Indian deployments can override with
`-e TZ=Asia/Kolkata`. The change is documented in the Dockerfile
itself.

### Session expiry timezone

`SESSION_EXPIRY_TIMEZONE` is a new env var (default
`Asia/Kolkata` for backward compatibility). `utils/session.py` and
`database/auth_db.py` read it into a `pytz.timezone` and compute the
daily expiry boundary in that tz. `_session_tz()` falls back to
`Asia/Kolkata` when the value is unrecognised.

### Per-broker master-contract refresh policy

`BrokerCapabilities` gains
`master_contract_refresh_policy: dict | None = None`:

```json
{
  "timezone": "Asia/Kolkata",
  "cutoff_local": "08:00",
  "frequency": "daily",
  "skip_if_24x7": false
}
```

`utils.auth_utils.get_master_contract_cutoff` reads the broker's
`BrokerCapabilities` first; legacy India brokers (no policy) keep the
existing 08:00 IST default. `frequency: "never"` returns
`(None, None, None)` and `should_download_master_contract` short-
circuits with `(False, "broker plugin master_contract_refresh_policy=never")`.

Crypto plugins (`broker_type == "crypto"`) without an explicit policy
get the 24x7-skip default automatically — this preserves the historical
`CRYPTO_BROKERS` behavior in `utils/constants.py`.

### Holiday data migration

`upgrade/migrate_holidays_to_venue_calendar.py` copies every
`(date, exchange)` pair from `market_holidays` +
`market_holiday_exchanges` into `venue_calendar_exceptions`:

* `holiday_type=="SPECIAL_SESSION"` (or `is_open=True` with epoch
  offsets) maps to `exception_type="SPECIAL_SESSION"` with
  `starts_at_local` / `ends_at_local` derived from the legacy
  `start_time`/`end_time` epoch-milliseconds offsets.
* Anything else maps to `exception_type="CLOSED"`.

Migrated rows carry `metadata = {"source":
"legacy_market_holidays_migration", "legacy_holiday_id": ...}` so the
provenance is queryable. Legacy rows are NOT deleted — the legacy
lane continues to read from `market_holidays`. A re-run is idempotent.

### `/api/v2/venues` endpoints

* `GET /api/v2/venues` — every seeded venue.
* `GET /api/v2/venues/<venue_code>` — one venue.
* `GET /api/v2/venues/<venue_code>/sessions?date=YYYY-MM-DD` —
  session windows for that date, computed via
  `services.venue_session_service.VenueSessionService.session_boundaries_for_date`.

The routes are registered in `restx_api/v2/__init__.py` alongside the
other v2 namespaces.

### Frontend admin pages and python_strategy

The legacy `admin/Holidays.tsx` and `admin/MarketTimings.tsx` pages
remain India-only. `Holidays.tsx` carries a TODO referencing Phase 6
(`is_india_region_active()` gate). `blueprints/python_strategy.py`
keeps its IST scheduler default for legacy strategies; venue-aware
scheduling is deferred to a follow-up because it requires schema
changes to `strategy_db.strategies` to carry a `venue_code` column.

## Consequences

* **Indian deployments are a no-op upgrade.** Every default preserves
  current behavior. Parity harness is bit-identical.
* **US/EU operators set one env var** (`SESSION_EXPIRY_TIMEZONE`) and
  configure their broker plugin's `master_contract_refresh_policy`
  block to get correct session expiry and master-contract refresh
  cadence.
* **Legacy holiday data is queryable from the new schema** via the
  venue calendar table after a single `uv run python
  upgrade/migrate_holidays_to_venue_calendar.py` run.
* **Admin UI gains `/api/v2/venues`** for non-India deployments to
  inspect the venue catalog without touching the legacy India tables.

## Alternatives considered

* **Per-broker env var for session tz.** Rejected — single-broker per
  instance per ADR 0001 means a single env var is sufficient and
  simpler to operate.
* **Replace the `market_holidays` table.** Rejected — destructive
  migration violates Phase 9's no-DROP rule. Additive copy is the
  policy.

## References

* ADR 0005 — Two lanes
* ADR 0006 — Literal scanner and fail-closed capabilities
* `database/venue_schedule_repo.py`
* `services/venue_session_service.py`
* `upgrade/migrate_holidays_to_venue_calendar.py`
* `restx_api/v2/venues.py`
