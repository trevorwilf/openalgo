# ADR 0029 — Structured market-context error taxonomy (v5 Phase 1)

* **Status:** Accepted (v5 Phase 1)
* **Supersedes / extends:** ADR 0023 (v4 scope), 0019 (instrument
  resolver). Adds the v5 net-new error codes the experts both
  recommended.

## Context

v4 closed the 17 v3 baseline gaps and shipped per-feature provider
contracts. Each feature carries its own `*_NOT_REGISTERED` /
`*_DISABLED_IN_REGION` error code, which is correct for the original
scope (one code per failure site). But two independent expert reviews
flagged the same gap: **no umbrella taxonomy** that a generic v2
client can branch on.

Concretely:

* A frontend that wants to "disable the offending control on the
  order ticket" needs a `dimension` hint on `unsupported_capability`,
  not a free-text message.
* A frontend that wants to "hide the Sandbox tab when the active
  region has no sandbox provider" needs a `feature` field on a
  generic `unsupported_provider` code, not 5 different per-feature
  codes.
* A generic API client (TradingView, Excel) that wants to render
  "feature X is not available in your region" needs a generic
  `unsupported_region` it can map to a single localized string.
* The v1 hard-block (Phase 2 v4) returns
  `v1_unavailable_for_non_india_broker` from the entry guard, but
  deeper services that detect "non-India request reached
  India-only surface" had no code.

## Decision

Add 10 v5 error codes to `domain.errors.ErrorCode`, one Python
exception class per code, and one canonical response shape per code
(documented in `docs/api/v2_errors.md`).

### Added codes

* `unsupported_region` (class `UnsupportedRegion`)
* `missing_region_context` (class `MissingRegionContext`)
* `unsupported_venue` (class `UnsupportedVenue`)
* `missing_venue_context` (class `MissingVenueContext`)
* `unsupported_capability` (extended — existing class
  `UnsupportedCapability` gains `dimension` ∈ `DIMENSIONS`)
* `missing_currency_context` (class `MissingCurrencyContext`)
* `missing_instrument_identity` (class `MissingInstrumentIdentity`)
* `missing_translator` (class `MissingTranslator`)
* `unsupported_provider` (class `UnsupportedProvider` with
  `feature` ∈ `FEATURES`)
* `legacy_lane_blocked` (class `LegacyLaneBlocked`)
* `entitlement_required` (class `EntitlementRequired`)

### Existing codes preserved

The per-feature `*_PROVIDER_NOT_REGISTERED` codes (sandbox/options/
screener/quote/bar/position/balance) remain valid. v5 does not retire
them; they are emitted alongside the umbrella `unsupported_provider`
code at the same site so existing consumers do not break.

### `dimension` constraints

`UnsupportedCapability.dimension` is one of:

```
order_type, tif, session, quantity_unit, currency, asset_class,
product_intent, combo_type, stream_transport
```

Class-level enforcement: the constructor raises `ValueError` for an
unknown dimension. Tests fix the list.

### `feature` constraints

`UnsupportedProvider.feature` is one of:

```
sandbox, options, screener, analyzer, flow, iv, gex, straddle,
synthetic_future, oi
```

## Consequences

* v2 clients can branch on a single canonical code per failure
  category. The frontend can hide the Sandbox tab (`unsupported_
  provider`/`feature=sandbox`) without a per-feature code map.
* The order-ticket UI can disable individual controls when the
  backend returns `unsupported_capability`/`dimension=tif`.
* Existing per-feature codes stay; deprecation is deferred to v6.
* Docs: `docs/api/v2_errors.md` is the single source of truth for
  the response shape per code.

## Implementation notes

* `tests/contracts/test_v5_structured_errors_emitted.py` exercises
  each new code via fixture-driven calls and asserts the JSON shape.
* No breaking changes to existing v2 callers: the new codes are
  additive; no existing code is reshaped.

## Related

* ADR 0030 — promoted-request observability label set.
* ADR 0023 — v4 scope, advanced-feature provider contracts.
* ADR 0017 — v3 promoted import lock.
