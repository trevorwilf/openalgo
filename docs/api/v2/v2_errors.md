# /api/v2 structured error taxonomy (v5 Phase 1, ADR 0029)

Every promoted (v2) error response carries a stable `code` (from
`domain.errors.ErrorCode`) plus context fields that scope the failure.
Clients should branch on `code`; the HTTP status is informational and
may change between versions.

## Response shape

```json
{
  "status": "error",
  "code": "<error_code>",
  "message": "<human-readable summary>",
  "...": "code-specific context fields"
}
```

The exact response builder lives at the route level (e.g.,
`restx_api/v2/orders.py`); this document fixes the contract clients
can rely on.

## v5 net-new error codes

### `unsupported_region` (HTTP 422)

The active region is known but is not supported by the operation,
provider, or translator for this request.

```json
{
  "status": "error",
  "code": "unsupported_region",
  "message": "region 'eu' is not supported",
  "region_code": "eu"
}
```

Client action: surface "this feature is not supported in your
region"; do not retry.

### `missing_region_context` (HTTP 422)

The promoted lane needs an active region but none could be resolved
from the broker capability, the stored default, or the request body.

```json
{
  "status": "error",
  "code": "missing_region_context",
  "message": "missing region context for promoted request",
  "attempted_sources": ["broker_capability", "stored_default"]
}
```

Client action: prompt the user to set a default region
(`/api/v2/regions`) or re-authenticate the broker.

### `unsupported_venue` (HTTP 422)

The supplied venue code (e.g., `XNSE`, `XNYS`) is not registered or
not allowed for the active broker.

```json
{
  "status": "error",
  "code": "unsupported_venue",
  "message": "venue 'XHKG' is not supported",
  "venue_code": "XHKG"
}
```

### `missing_venue_context` (HTTP 422)

A promoted request requires a venue but none was supplied or
resolvable from instrument metadata.

```json
{
  "status": "error",
  "code": "missing_venue_context",
  "message": "missing venue context for promoted request"
}
```

### `unsupported_capability` (HTTP 422)

The active broker does not support a specific dimension of the
requested operation.

```json
{
  "status": "error",
  "code": "unsupported_capability",
  "message": "broker does not support tif=GTC",
  "broker_code": "_mock_schwab_like",
  "capability_name": "tif",
  "dimension": "tif",
  "details": null
}
```

`dimension` ∈ `{"order_type", "tif", "session", "quantity_unit",
"currency", "asset_class", "product_intent", "combo_type",
"stream_transport"}`.

Client action: mark the offending control on the order ticket
disabled.

### `missing_currency_context` (HTTP 422)

Promoted code MUST NOT default to INR. If no currency can be derived
from account context, venue base_currency, instrument currency, or
explicit request fields, this code is returned.

```json
{
  "status": "error",
  "code": "missing_currency_context",
  "message": "missing currency context for promoted request"
}
```

### `missing_instrument_identity` (HTTP 422)

An instrument lookup failed because no identifier was supplied
(internal UUID, MIC+symbol, or external IDs FIGI/ISIN/CUSIP/SEDOL/OSI
per D-2).

```json
{
  "status": "error",
  "code": "missing_instrument_identity",
  "message": "missing instrument identity for promoted request"
}
```

### `missing_translator` (HTTP 422)

No `BrokerTranslator` is registered for the active broker on the v2
lane. Equivalent to `translator_not_registered` (still valid for
backward compatibility); v2 admission emits the new code.

```json
{
  "status": "error",
  "code": "missing_translator",
  "message": "no translator registered for broker '_mock_xyz'",
  "broker_code": "_mock_xyz"
}
```

### `unsupported_provider` (HTTP 422)

No provider for the requested feature is registered for the active
region. Umbrella over the per-feature `*_provider_not_registered`
codes; carries a `feature` field for UI dispatch.

```json
{
  "status": "error",
  "code": "unsupported_provider",
  "message": "no sandbox provider registered for region 'eu'",
  "feature": "sandbox",
  "region_code": "eu"
}
```

`feature` ∈ `{"sandbox", "options", "screener", "analyzer", "flow",
"iv", "gex", "straddle", "synthetic_future", "oi"}`.

### `legacy_lane_blocked` (HTTP 410 / 422)

A non-India request reached an India-only legacy surface. v1 routes
emit `v1_unavailable_for_non_india_broker` from the entry guard;
deeper components (services, dispatchers) emit this code when they
detect the misroute.

```json
{
  "status": "error",
  "code": "legacy_lane_blocked",
  "message": "legacy lane 'place_order_service' blocked for broker '_mock_schwab_like'",
  "surface": "place_order_service",
  "broker_code": "_mock_schwab_like"
}
```

### `entitlement_required` (HTTP 422)

Account context lacks an entitlement the request requires. Used by
v2 promoted-order admission to gate options access, fractional/
notional, shorting, extended-hours, etc.

```json
{
  "status": "error",
  "code": "entitlement_required",
  "message": "entitlement 'options_level_2' required",
  "entitlement": "options_level_2",
  "account_id": "abc-123"
}
```

## Existing v3/v4 codes (still valid)

The earlier per-feature codes remain valid; the v5 codes layer on top
without breaking existing clients:

* `region_resolution_error`
* `configuration_error`
* `v1_unavailable_for_non_india_broker`
* `legacy_fallback_blocked_for_non_india`
* `instrument_ambiguous`, `instrument_not_resolvable`
* `promoted_capability_unavailable`
* `quote_adapter_not_registered`, `bar_adapter_not_registered`,
  `position_adapter_not_registered`,
  `balance_adapter_not_registered`
* `sandbox_provider_not_registered`,
  `options_provider_not_registered`,
  `screener_provider_not_registered`
* `unsupported_capability` (the `dimension` field is new in v5;
  existing emitters that omit it still validate)

## Test enforcement

`tests/contracts/test_v5_structured_errors_emitted.py` exercises every
new code via fixture-driven calls and asserts the response shape.
