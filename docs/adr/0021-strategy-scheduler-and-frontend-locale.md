# ADR 0021 — Strategy/scheduler region gating + frontend locale + region API completeness

Status: accepted (v3 Phase 5 — partial)
Date: 2026-04-25

## Context

Phase 4 closed the back-end service-layer gates for the India-shaped
options surfaces. Phase 5 in the v3 prompt asks for:

1. Strategy / python_strategy / chartink scheduler venue-aware
   labels and a venue_code field on the schedule record.
2. Frontend chart timezone refactor (replace hardcoded "+05:30" /
   "IST" with a venue-aware label fetched from
   `/api/v2/venues/<venue_code>`).
3. Frontend MasterContract page reading
   `master_contract_refresh_policy` from the broker plugin.
4. Frontend admin pages (MarketTimings, Holidays, HealthMonitor,
   LatencyDashboard, SecurityDashboard, PythonStrategyIndex)
   replacing hardcoded "+05:30" / "IST" / "Asia/Kolkata" /
   "en-IN" with locale-aware formatting.
5. Backend `/api/v2/regions/*` and `/api/v2/regions/<code>/flow_defaults`
   completeness with the field set the frontend FlowBuilder requires.
6. New `useFlowDefaults(region_code)` hook in the frontend.

## Decision

### Region API completeness (delivered)

The v2 prompt's Phase 5 had already shipped most of the regions
endpoints. This phase adds explicit shape-pinning tests at
`tests/api_v2/test_regions_endpoint_complete.py` so future code can't
quietly drop fields the frontend depends on. The shape contract is:

```
GET /api/v2/regions/<code>:
  region_code, display_name, country_codes, default_currency,
  timezone_name, market_families, default_venue_codes,
  default_sessions, venues[], session_templates[],
  calendar_exceptions[], symbol_display{}, feature_flags{}

GET /api/v2/regions/<code>/flow_defaults:
  region_code, flow_templates_enabled, exchanges[], products[],
  option_underlyings[], lot_sizes{}, schedule_default
```

All 8 new tests pass for the four shipped regions (india, us, uk, eu).
The non-India regions return the "disabled" empty shape because
their `flow_templates_enabled` is false — exactly what the
FlowBuilder needs to render an "unavailable" state.

### Strategy entry-point gates

The strategy execute path goes through
`services.flow_executor_service.execute_workflow`, which Phase 4 has
already gated behind `is_india_region_active()`. A non-India active
region returns the structured `flow_templates_disabled_in_region`
error before any node default fires. This satisfies the
"strategy_region_mismatch" intent of the Phase 5 prompt for the
flow-driven strategies.

The standalone `blueprints/python_strategy.py`,
`blueprints/strategy.py`, and `blueprints/chartink.py` schedulers
still emit IST-tagged schedule labels and assume India trading-day
boundaries. Adding the `venue_code` schema field on the schedule
record + cron-evaluation refactor + per-strategy region check is
deferred to a follow-up Phase 5-bis (see § Deferred).

### Deferred to a follow-up Phase 5-bis

These items from the v3 Phase 5 prompt are explicitly **deferred**:

1. **Schema migration on `strategies` / `chartink_strategies` to add
   a `venue_code` column** with `NSE` default for existing rows.
   Cron expression conversion at evaluation time (local-time-in-venue
   → UTC) is non-trivial and risks parity drift on existing India
   schedules.
2. **Frontend chart timezone refactor.** `frontend/src/pages/HistorifyCharts.tsx`
   and `frontend/src/api/charts*.ts` still embed "+05:30" / "IST"
   labels. The replacement requires a `VenueLocalTime` component and
   a hook that fetches `/api/v2/venues/<venue_code>` per chart.
3. **Frontend MasterContract page.** `frontend/src/pages/MasterContract.tsx`
   still shows `"08:00 IST"` hardcoded. Reading from
   `master_contract_refresh_policy` requires a small UI refactor +
   tests.
4. **Frontend admin pages locale-aware refactor.** A reusable
   `VenueLocalTime` component plus replacing the IST literals across
   `MarketTimings.tsx`, `Holidays.tsx`, `HealthMonitor.tsx`,
   `LatencyDashboard.tsx`, `SecurityDashboard.tsx`,
   `PythonStrategyIndex.tsx`.
5. **`useFlowDefaults(region_code)` hook** + `frontend/src/lib/flow/constants.ts`
   refactor. The backend endpoint exists; the frontend still reads
   the hardcoded India arrays for FlowBuilder.

These deferrals leave India behavior bit-identical and the non-India
flow gated at the backend; the frontend showing IST labels for
non-India users is a UX issue but not a correctness issue (the
backend gates ensure no India-default data is emitted).

## Consequences

* The backend `/api/v2/regions/*` surface is now contract-pinned —
  the frontend can rely on every documented field being present.
* Non-India regions get a deterministic empty shape from
  `/flow_defaults` so the frontend knows to render "unavailable".
* The flow_executor_service entry-point gate (Phase 4) covers the
  strategy execute path for flow-driven strategies. The standalone
  Python-strategy / Chartink schedulers still need their own gates
  (Phase 5-bis).
* Frontend visual labels remain India-shaped for non-India brokers.
  This is documented and tracked.

## Alternatives considered

* **Land the venue_code schema migration in this phase.** Rejected —
  the schema migration touches existing strategy rows, the cron
  evaluator's tz-conversion path, and the APScheduler bindings; the
  combined change is bigger than the phase's risk-budget.
* **Refactor the frontend chart/admin TZ surfaces in this phase.**
  Rejected — the surface is broad enough that a focused phase
  dedicated to the UX migration is the right shape, with its own
  Vitest fixtures and locale-aware component design.

## References

* `restx_api/v2/regions.py` — endpoint (already present)
* `tests/api_v2/test_regions_endpoint_complete.py` — shape-pinning
  tests
* `services/flow_executor_service.py` — Phase 4 gate (covers flow-
  driven strategy execute path)
* `docs/refactor/v3_baseline_audit.md` — gap 13 (open follow-up)
* ADR 0010 (capability-driven frontend), ADR 0011 (region gating),
  ADR 0020 (service region gating)
