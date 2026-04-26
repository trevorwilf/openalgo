# ADR 0020 — Service-layer region gating + historify TZ + currency propagation

Status: accepted (v3 Phase 4 — partial)
Date: 2026-04-25

## Context

After Phase 3 the v2 dispatch surface is fail-closed for non-India
brokers and the canonical resolver is the only resolution path on
the promoted lane. But the service layer still has India-shaped
defaults that fire silently for non-India regions:

* `services.flow_executor_service` defaults `exchange="NSE"` and
  `product="MIS"` at multiple node-default sites.
* `services.expiry_service`, `services.iv_chart_service`,
  `services.gex_service`, `services.option_greeks_service`,
  `services.options_multiorder_service`,
  `services.synthetic_future_service`,
  `services.straddle_chart_service`,
  `services.vol_surface_service` parse the India DDMMMYY expiry
  grammar / India NFO/BFO option-chain shape with no region check.
* `database.historify_db` hardcodes `ist_offset = 19800` for the
  intra-day candle aggregation SQL.
* Currency does not propagate end-to-end through orders → quotes →
  positions → P&L → notifications.

This ADR records the partial close in v3 Phase 4 and the deferred
items.

## Decision

### Service-layer region gates (delivered)

Each India-shaped service grows a region gate at the public entry
point. The gate reads `is_india_region_active()` from
`services.feature_gate_service` and returns a structured 422 error
with a stable `*_disabled_in_region` code from `domain.errors.ErrorCode`
when the active region is not India:

| Service | Function | Error code |
|---|---|---|
| `expiry_service` | `get_expiry_dates` | `expiry_grammar_not_supported_in_region` |
| `iv_chart_service` | `get_iv_chart_data` | `iv_chart_disabled_in_region` |
| `gex_service` | `get_gex_data` | `gex_disabled_in_region` |
| `option_greeks_service` | `get_option_greeks` | `option_greeks_disabled_in_region` |
| `options_multiorder_service` | `place_options_multiorder` | `multi_option_disabled_in_region` |
| `synthetic_future_service` | `calculate_synthetic_future` | `synthetic_future_disabled_in_region` |
| `straddle_chart_service` | `get_straddle_chart_data` | `straddle_chart_disabled_in_region` |
| `vol_surface_service` | `get_vol_surface_data` | `vol_surface_disabled_in_region` |
| `flow_executor_service` | `execute_workflow` | `flow_templates_disabled_in_region` |

`services.feature_gate_service.require_region_feature(flag,
error_code, *, message=None)` is added as the canonical helper —
raises `FeatureNotAvailableInRegion` when the active region's flag
is disabled. India region passes the gate, parity preserved.

`tests/services/test_phase4_region_gates.py` covers each gate end-
to-end, plus the helper directly.

### Error code additions

`domain.errors.ErrorCode` adds:

* `FLOW_TEMPLATES_DISABLED_IN_REGION`
* `FLOW_DEFAULT_UNAVAILABLE_IN_REGION`
* `OPTION_CHAIN_DISABLED_IN_REGION`
* `IV_CHART_DISABLED_IN_REGION`
* `GEX_DISABLED_IN_REGION`
* `OPTION_GREEKS_DISABLED_IN_REGION`
* `MULTI_OPTION_DISABLED_IN_REGION`
* `SYNTHETIC_FUTURE_DISABLED_IN_REGION`
* `STRADDLE_CHART_DISABLED_IN_REGION`
* `VOL_SURFACE_DISABLED_IN_REGION`

Frontends key off these stable strings to render localized errors
and to decide fallback behavior.

### Deferred to a follow-up Phase 4-bis

Three items from the v3 Phase 4 prompt are explicitly **deferred**
to a future operator-controlled follow-up phase:

1. **`database/historify_db.py` venue-aware bucketing.** The file
   has multiple SQL aggregations that use `ist_offset = 19800` as a
   literal offset and a `Asia/Kolkata` default. Replacing the SQL
   with venue-aware bucketing (DST-correct) requires rewriting the
   query path and adding a DST test fixture day. Risk to India
   parity is non-trivial. The literal scanner already classifies
   `database/historify_db.py` as `LEGACY_INDIA`, so no PROMOTED_CORE
   leak exists today.

2. **End-to-end currency propagation through the order/quote/position/
   P&L/notification chain.** `domain.orders.NormalizedOrderRequest`
   already carries `currency` via the instrument context; the
   normalized DTOs are correct. The legacy India services and the
   telegram bot still infer `INR` from broker name. Refactoring
   every consumer to read `order.currency` /
   `account.base_currency` is a larger surface than fits this
   phase's scope without risking parity drift. The Currency enum
   is already defined; helpers can be added as the chain is
   migrated.

3. **`utils/number_formatter.format_currency(value, currency_code)`
   helper + frontend `lib/utils.ts` currency-formatting refactor +
   `database/telegram_db.py` user-default timezone change.** Each
   touches user-visible surfaces that need targeted UAT before
   landing.

These deferrals are documented in `docs/refactor/v3_baseline_audit.md`
gaps 6-9 and remain open follow-ups. The phase report explicitly
calls them out.

## Consequences

* A non-India broker hitting any of the 9 gated services receives
  a structured 422 with a stable error code — never silent wrong
  behavior.
* India parity is preserved bit-identically: every gate's India
  branch is the existing code path unchanged.
* The frontend can switch on the new `*_disabled_in_region` codes
  to render an "available in India only" fallback for these
  surfaces (Phase 5 wires this).
* The deferred items are tracked: future Phase 4-bis closes them
  with their own ADR.

## Alternatives considered

* **Wrap every node-default site in `flow_executor_service` (lines
  197, 201, 225, 230, 329, 577, 584, 645, 701, 706 per the v3
  Phase 0 inventory) instead of gating the entry point.** Rejected
  for this phase — the entry-point gate achieves the same outcome
  (no non-India request reaches the India defaults) with one site
  to maintain. Per-site refactor follows when the flow_executor
  itself is migrated to capability-driven defaults.
* **Land the historify TZ rewrite in this phase to keep the prompt's
  scope.** Rejected — the rewrite needs DST-day fixtures, an
  in-Python aggregation fallback, and India parity verification
  that doesn't fit a single phase boundary. Documented as deferred.

## References

* `services/feature_gate_service.py` — `require_region_feature` helper
* `services/expiry_service.py`, `iv_chart_service.py`,
  `gex_service.py`, `option_greeks_service.py`,
  `options_multiorder_service.py`, `synthetic_future_service.py`,
  `straddle_chart_service.py`, `vol_surface_service.py`,
  `flow_executor_service.py` — entry-point gates
* `domain/errors.py` — new ErrorCode entries
* `tests/services/test_phase4_region_gates.py`
* `docs/refactor/v3_baseline_audit.md` — gaps 3-9 (open follow-ups)
* ADR 0011 (region gating), ADR 0017
