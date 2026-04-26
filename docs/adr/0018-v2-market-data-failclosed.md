# ADR 0018 — v2 quotes/bars fail-closed + canonical instrument adoption

Status: accepted (v3 Phase 2)
Date: 2026-04-25

## Context

`/api/v2/orders` was made fail-closed for non-India brokers in the v2
prompt's Phase 3 (ADR 0008): a non-India non-crypto broker request
without a registered translator returns HTTP 503
`promoted_lane_required_for_non_india_broker`, never silently calls
`services.place_order_service`. The market-data routes
(`/api/v2/quotes`, `/api/v2/bars`) shipped with a softer policy: any
missing adapter fell back to the legacy `services.quotes_service` /
`services.history_service`. That meant a US broker without a quote
adapter could pull a quote from the legacy India market-data service
and silently produce wrong/garbage data.

Both expert reviews (E1-MAG-004, E1-MAG-005, E2-MG-041, E2-MG-042)
called this out as the largest remaining boundary leak.

## Decision

`restx_api/v2/quotes.py` and `restx_api/v2/bars.py` adopt the same
fail-closed contract `restx_api/v2/orders.py` already follows.

### Dispatch matrix

For each request, after auth resolution:

| flag | adapter | broker class | result |
|---|---|---|---|
| ON | registered | any | promoted dispatch |
| ON | missing | India / crypto | legacy fallback (parity) |
| ON | missing | non-India non-crypto | **HTTP 503 `promoted_capability_unavailable` / `quote_adapter_not_registered`** (or `bar_adapter_not_registered`) |
| OFF | n/a | India / crypto | legacy fallback (parity) |
| OFF | n/a | non-India non-crypto | **HTTP 503 `promoted_lane_required_for_non_india_broker`** |

The "non-India non-crypto" classification reads
`broker_capabilities.supported_regions` and `broker_type` exactly the
same way `restx_api/v2/orders._broker_lane_check` does — so a single
plugin manifest change flips both order and market-data routing
together.

### Canonical instrument adoption

The promoted dispatch path resolves every `InstrumentRef` via
`services.instrument_resolution.resolve_instrument` (canonical
`instruments` table). The legacy `_resolve_ref` helper that fell back
to `database.symbol.get_token` is kept for the legacy-fallback
dispatch path only. Per-ref resolution failures return a structured
`instrument_not_resolvable` error (per-instrument for `quotes`, top-
level 422 for `bars`).

### Metrics

Three new counters are emitted (matches the expert 1 §14.1 contract):

- `broker_adapter_missing_total` — labels: `broker`, `region`,
  `route`, `adapter_kind` ∈ {"quote","bar"}
- `instrument_resolution_failed_total` — labels: `broker`, `region`,
  `ref_kind`, `identifier_type`
- `unsupported_capability_total` — labels: `broker`, `region`,
  `venue`, `asset_class`, `capability_name`

Existing counters (`promoted_failclosed_total`,
`promoted_legacy_fallback_total`) are reused with consistent labels.

### Compliance harness

`tests/compliance/broker_plugin_compliance.py` adds:

- `BrokerComplianceMixin.assert_quote_adapter_compliance(adapter)` —
  protocol surface assertion called from broker-specific compliance
  tests once an adapter is registered.
- `BrokerComplianceMixin.assert_bar_adapter_compliance(adapter)` —
  same for `BrokerBarAdapter`.

These are explicit assertion helpers (not auto-discovered) since
adapter registration is per-test and the harness can't snapshot the
registry mid-run.

## Consequences

* A non-India broker without an adapter cannot silently produce wrong
  quotes/bars. Every leak surfaces as a structured 503 the operator
  can alert on.
* Parity is preserved for India and crypto brokers — the legacy
  fallback path is still reachable when the per-broker promoted flag
  is off.
* Operators get observable signals (`broker_adapter_missing_total`,
  `instrument_resolution_failed_total`) for the new failure modes.
* `tests/api_v2/test_quotes_failclosed.py`,
  `test_bars_failclosed.py`,
  `test_quotes_canonical_resolver.py`,
  `test_bars_canonical_resolver.py` enforce the contract end-to-end.

## Alternatives considered

* **Keep silent legacy fallback for quotes/bars, log a warning.**
  Rejected — wrong data is worse than no data. Both experts
  explicitly called for symmetric fail-closed semantics.
* **Hard fail at app boot if any non-India broker has no adapter.**
  Rejected — too rigid. Plugin development needs the per-broker flag
  to differentiate "registered for promotion" from "registered but
  not yet promoted".

## References

* `restx_api/v2/quotes.py` — fail-closed dispatch
* `restx_api/v2/bars.py` — fail-closed dispatch
* `services/instrument_resolution.py` — canonical resolver
* `services/broker_market_data_registry.py` — adapter registry
* `tests/api_v2/test_quotes_failclosed.py`
* `tests/api_v2/test_bars_failclosed.py`
* `tests/api_v2/test_quotes_canonical_resolver.py`
* `tests/api_v2/test_bars_canonical_resolver.py`
* `tests/fakes/fake_us_market_data.py` — FakeUS adapter fixtures
* `tests/compliance/broker_plugin_compliance.py` — quote/bar
  adapter compliance helpers
* ADR 0005, ADR 0008, ADR 0017
