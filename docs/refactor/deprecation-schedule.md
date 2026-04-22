# Legacy surface deprecation schedule

> **Status:** commitment, not execution. Each item below is the
> **earliest date** at which a follow-up cleanup phase may delete the
> surface. The deletion itself is a separate PR (or phase); this doc
> commits the ordering and the gating conditions.

Every item here has at least one invariant in `CLAUDE.md` naming it
as the legacy path. When the item ships for removal, the matching
invariant becomes enforceable (e.g. a lint rule, a startup assertion).

## Schedule

### `database.token_db.get_token(symbol, exchange)` and friends

- **Gating condition:** `RESOLVER_V2` stable in production for **60
  consecutive days** with:
  - Zero `resolver_exception` entries beyond the baseline noise.
  - Zero `legacy_fallback_used=true` outcomes on the top-20 symbols
    of the active broker (baseline-noise bottom-20 is acceptable).
  - `broker_instrument_map` covers every `(broker_code, venue_code)`
    pair listed in the broker's plugin.json `supported_exchanges`
    (verify with a repo-level query against a prod DB snapshot).
- **Phase 3a's synthetic `uuid5` legacy-fallback** must also be
  unused — that means new symbols are reaching the new instruments
  table before any user requests them. The sync runner's catch-up
  rate governs this.
- **Removal PR scope:** delete `database/token_db.py`,
  `database/token_db_enhanced.py`, `database/symbol.py`'s
  `enhanced_search_symbols` / `fno_search_symbols_db` if they have
  replacements in `instruments_repo.py`. Keep `SymToken` the table
  one phase longer — see next item.

### `delete_symtoken_table()` and every broker's master-contract writer

- **Gating condition:** `INSTRUMENT_CORE_V2` stable for **60
  consecutive days** AND every Phase 3-or-later service reads from
  Phase 2a's `instruments` / `broker_instrument_map` — no remaining
  `SymToken` import outside `database/symbol.py` and
  `database/token_db*.py`.
- The `get_token` deprecation (above) must have already landed, so
  `symtoken` is definitively unread.
- **Removal PR scope:** edit every `broker/*/database/master_contract_db.py`
  to delete the `delete_symtoken_table` call + its bulk INSERT, in
  favor of calling `InstrumentSyncRunner`. At that point the
  `symtoken` table itself can be dropped in a subsequent migration.
  This is the single highest-risk deletion in the whole refactor
  and is explicitly gated behind the `get_token` deprecation's
  stability window.

### `utils.constants.VALID_EXCHANGES / VALID_PRODUCT_TYPES / VALID_PRICE_TYPES`

- **Gating condition:** `/api/v2` is the primary API (not a
  skeleton) AND `/api/v1` is in announced sunset mode (date-TBD).
- **Why gated on v2-primary rather than a flag-stability window:**
  these three lists appear in 60+ validator call sites across
  `utils/api_analyzer.py`, `services/*`, `restx_api/schemas.py`, and
  `restx_api/data_schemas.py`. Each one depends on an `/api/v1`
  response shape frozen under ADR 0003. The cleanup PR rewrites all
  validator call sites to consume `BrokerCapabilities` directly,
  and that rewrite is only safe once v1 is being retired.
- **Removal PR scope:** replace every import of these three names
  with `cap.supported_order_types`, `cap.supported_asset_classes`,
  etc. Then delete the three constants and the `VALID_EXCHANGES` /
  `VALID_PRODUCT_TYPES` / `VALID_PRICE_TYPES` shadow copies in
  `blueprints/chartink.py` and `blueprints/strategy.py`.

### `frontend.brokerStore.broker_type` legacy alias + `makeFormatCurrency(broker)`

- **Gating condition:** every React component has migrated off
  `broker_type` (string union `'IN_stock' | 'crypto'`) to reading
  `market_families` / `supported_asset_classes` / etc. from the rich
  `BrokerCapabilities`. The existing `useSupportedExchanges` hook,
  the `PlaceOrderDialog` order-type dropdown, and the
  `currency` formatter are the three known consumers.
- **Removal PR scope:** delete the `broker_type` property getter
  from the backend pydantic model (`domain/capabilities.py`) and
  the matching alias in `frontend/src/types/capabilities.ts`.
  Delete `makeFormatCurrency` from `frontend/src/lib/utils.ts`
  entirely; force all callers to `formatCurrencyByCode(amount,
  capabilities.base_currency)`.

### `"Asia/Kolkata"` / `"IST"` string literals in legacy services

- **Gating condition:** `VENUE_SESSION_V2` covers every consumer
  named in `docs/refactor/inventory/03-ist-kolkata-references.md` —
  specifically:
  - `services/historify_scheduler_service.py`
  - `services/iv_chart_service.py`
  - `services/straddle_chart_service.py`
  - `blueprints/python_strategy.py`
- Phase 4 wired the flag into `services/market_calendar_service.py`
  only. The four remaining consumers are the gating condition.
- **Removal PR scope:** add a ruff rule that bans `"Asia/Kolkata"`
  in every file under `services/` and `blueprints/`. Allowlist the
  known-exception files — migration scripts, seed data, and tests
  that assert against fixed tz strings.

### Tests and harness commentary

The Phase 0 parity fixtures and the `run_parity_matrix.py` runner
stay. They are the arbiter during the deprecation phase too — if any
row turns red during a removal PR, that PR reverts, not merges.

## Not on the schedule (deliberate)

The following remain indefinitely, per ADR:

- `database.market_calendar_db` — the IST-only legacy calendar. ADR
  0004 keeps the analyzer India-only and the legacy calendar is its
  authoritative source. The new `venue_schedule_templates` are
  additive; the old tables are untouched.
- Every broker-specific module under `broker/*/` — the refactor does
  not restructure broker code. Adapters live in `services/instrument_sync_adapters/`.
- Auth / session / credential single-tenant shape — ADR 0001 locks
  one-broker-per-instance.

## When this schedule unlocks

None of the items above are "ready to remove today." They unlock
when the matching flag has been stable in a specific production
deployment for its named window, verified against that deployment's
logs. This document is **not** a cleanup work order — it is a record
of the gating conditions so that when a future operator says "can I
delete `get_token` now?" the answer is objectively yes or no.
