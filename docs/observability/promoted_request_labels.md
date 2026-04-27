# Promoted-request observability labels (v5 Phase 1, ADR 0030)

Every promoted (v2) request emits **one structured-log line** with the
canonical label set defined here. Legacy (v1) requests do not emit
this line — they emit only the existing traffic-log entry handled by
`utils/traffic_logger.py`.

The single emission site for promoted requests is
`utils/observability.py::log_promoted_request`. Downstream metrics
exporters can rely on the schema below being stable until the next
ADR explicitly adds or renames a key.

## Label set

| Key | Type | Required | Source | Notes |
|---|---|---|---|---|
| `region_code` | string \| null | yes (nullable) | `services.feature_gate_service.active_region_code()` | "india", "us", "eu", … or `null` for legacy lane |
| `broker_code` | string \| null | yes (nullable) | active broker session | `null` if no broker session yet |
| `venue_code` | string \| null | yes (nullable) | `services.venue_session_service` / order request | "XNSE", "XNYS", "XBOM", … |
| `instrument_id` | string \| null | yes (nullable) | canonical instrument identity (UUID or MIC+symbol) | per ADR 0019 / D-2 |
| `currency` | string \| null | yes (nullable) | account context > venue base_currency > instrument currency | ISO 4217 |
| `provider_code` | string \| null | yes (nullable) | dispatcher (sandbox/options/screener) | `null` for plain order/quote/bar requests |
| `capability_source` | enum | required | computed | `"region"`, `"broker"`, `"account"`, or `"provider"` |
| `legacy_lane` | bool | required | dispatch decision | `true` only on v1 requests; on v2 requests `false` |
| `route` | enum | required | "v1" or "v2" | matches the served route |
| `request_id` | string \| null | yes (nullable) | framework-supplied request id | best-effort; some entry points may not set one |

## Emission sites

* `restx_api/v2/orders.py` — POST `/api/v2/orders` and POST `/api/v2/orders/combo`
* `restx_api/v2/quotes.py` — GET/POST `/api/v2/quotes`
* `restx_api/v2/bars.py` — GET/POST `/api/v2/bars`
* `restx_api/v2/accounts.py` — GET `/api/v2/positions`, GET `/api/v2/balances`
* Dispatcher entry points for sandbox / options / screener providers

The emission is **post-admission**: structured errors raised before
the dispatch decision (e.g., `MISSING_REGION_CONTEXT`) are logged via
the standard error handler, not this helper.

## Stability contract

* Adding a new label key is allowed only via a new ADR (the
  `0030-` ADR is the seed; subsequent ADRs may extend).
* Renaming or removing a label key is **forbidden** outside a major
  version bump.
* `null` is a valid value for any nullable key; downstream consumers
  must accept it without error.

## Test enforcement

* `tests/contracts/test_v5_observability_labels_complete.py` asserts:
  * Every required key is present in a sample emission.
  * `legacy_lane=false` for v2 requests.
  * Helper raises if any required key is omitted.

## Known non-goals (deferred to v6)

* Metrics counters / histograms (Prometheus, OpenTelemetry).
* Sampling controls.
* Per-broker latency SLOs / dashboards.
