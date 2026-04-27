# Webull Readiness Package

> **The mock plugin proves OpenAlgo's framework is ready. It does NOT
> prove API compatibility with real Webull. Real plugin implementation
> requires authenticated docs review, credentials, UAT/paper validation,
> and human approval.**

Status: framework-only (Phase 8 v2 + Phase 6 v3 + Phase 11 v4).
Plugin implementation deliberately out of scope per the v2/v3/v4
prompts.

## v5 framework-readiness extension (Phase 10)

v5 closes the v4 deferred bis-phases and adds the structured-error
+ observability surface a real Webull plugin will emit. Webull-
specific findings:

* **Subaccount model** — `AccountContext.subaccount_id` already
  models Webull's parent/sub split; the mock declares
  `account_context_supports.subaccount_id=true`. A real Webull
  plugin reads `parentId`/`subAccountId` from Webull's API and
  populates the field.
* **Streaming transport** — the mock declares the websocket-style
  handle/lifecycle; real Webull also uses websocket. The Phase 10
  closing audit verifies the lifecycle test passes for the mock
  ahead of real-plugin work.
* **Region restrictions** — Webull plugins declare
  `supported_regions: ["us"]`; v5's `unsupported_region` /
  `missing_region_context` errors fire correctly when an account
  context lacks the resolved region.
* **Combo types** — v5 Phase 7 made `supports_combo_types`
  top-level on `BrokerCapabilities`; the mock Webull declares
  `["SINGLE", "OCO", "OTO", "OTOCO"]` at top level. The combo
  dispatcher's gate now fires on this list.

v5 verification surface (mirrors the Schwab readiness extension):

| Surface | Status | Test |
|---|---|---|
| Structured market-context error taxonomy (ADR 0029) | ✅ pass | `tests/contracts/test_v5_structured_errors_emitted.py` |
| Promoted-request observability label set (ADR 0030) | ✅ pass | `tests/contracts/test_v5_observability_labels_complete.py` |
| Combo single source of truth | ✅ pass | `tests/contracts/test_v5_combo_capability_single_source.py` |
| Account context entitlement contract | ✅ pass | `tests/domain/test_v5_account_context_entitlements.py` |

A real Webull plugin will additionally need:

* `unsupported_capability` + `dimension="quantity_unit"` for
  fractional/notional unsupported on certain account types.
* `entitlement_required` for Webull options levels (especially
  the unique 0DTE / multi-leg gates Webull applies per account).

## v4 framework-readiness extension (Phase 11, ADR 0023)

v4 adds the following surfaces. Each maps to a contract test in
`tests/contracts/` or `tests/<surface>/test_*.py`:

| Surface | Status | Test |
|---|---|---|
| Strict promoted plugin schema (ADR 0025) | ✅ pass | `tests/plugin_loader/test_strict_promoted_schema.py::test_mock_webull_passes_strict_mode` |
| BrokerPositionAdapter | ✅ scaffolded | `broker/_mock_webull_like/api/position_balance_adapters.py:MockWebullLikePositionAdapter` |
| BrokerBalanceAdapter | ✅ scaffolded | `broker/_mock_webull_like/api/position_balance_adapters.py:MockWebullLikeBalanceAdapter` |
| `/api/v2/positions` adapter dispatch | ✅ pass | `tests/api_v2/test_positions_failclosed_non_india.py` |
| `/api/v2/balances` adapter dispatch | ✅ pass | `tests/api_v2/test_balances_failclosed_non_india.py::test_non_india_with_adapter_returns_normalized_balance` |
| Sandbox provider (US, mock data) | ✅ in framework | `tests/sandbox/test_provider_contract.py` |
| Options provider (US, OCC OSI) | ✅ in framework | `tests/options/test_provider_contract.py` |
| Screener provider | ✅ India only (US out of v4) | `tests/screeners/test_provider_contract.py` |
| Plugin diagnostics endpoint | ✅ pass | `tests/plugin_loader/test_diagnostics_endpoint.py` |
| v1 hard-block for non-India | ✅ pass | `tests/contracts/test_v1_lane_blocks_non_india.py` |
| Framework readiness gate | ✅ pass | `tests/contracts/test_framework_ready_for_real_brokers.py` |

Webull-specific carryovers from v3: SIGNATURE auth alongside OAUTH,
sub-account semantics (subaccount_id in AccountContext), MQTT market-
data + gRPC order-event streams. All preserved through v4.

**Real Webull plugin implementation remains the next-step work
blocked on official API validation.**

## Framework readiness verification (Phase 6 v3, ADR 0022)

A fully-mocked Webull-LIKE plugin under
`broker/_mock_webull_like/` exercises every promoted-lane contract
end-to-end with deterministic in-memory fixtures including the
Webull-specific surfaces (SIGNATURE auth alongside OAUTH,
sub-account semantics, MQTT market-data + gRPC order-event streams).

| Contract | Test |
|---|---|
| A. Metadata (plugin.json schema) | `tests/compliance/test_mock_webull_like_compliance.py::test_a_metadata_plugin_json_validates` |
| B. Auth — `authenticate()` returns `AccountContext` with `subaccount_id` | `test_b_auth_module_exposes_authenticate` |
| C. Account snapshot uses `NormalizedAccountSnapshot` shape | `test_c_account_snapshot_uses_normalized_shape` |
| D. Translator implements `validate` / `to_native` / `from_native_order_response` | `test_d_translator_module_exists` |
| E. Quote + bar adapters | `test_e_market_data_adapters_optional` |
| F. Instrument sync seeds `instruments` + `broker_instrument_map` | `test_f_instrument_sync_optional` |
| G. Rule matrix optional | `test_g_rule_matrix_optional` |
| H. Lane isolation (no India literals, no legacy imports) | `test_h_lane_isolation_imports_and_literals` |
| I. Fail-closed capability metadata | `test_i_fail_closed_capability_metadata` |
| J. NEW Combo orders — OCO dispatch with native `combo_type` + `entrust_type` | `tests/api_v2/test_orders_combo.py::test_combo_oco_dispatch_to_webull_like` |
| K. NEW Streaming subscribe → 3 events → unsubscribe lifecycle (MQTT market data + gRPC order events) | `tests/e2e/test_mock_webull_like_e2e.py::test_e2e_mock_webull_streaming_handle_lifecycle` |
| L. NEW End-to-end LIMIT order through `/api/v2/orders` with `subaccount_id` populated and no legacy fallback | `tests/e2e/test_mock_webull_like_e2e.py::test_e2e_mock_webull_single_equity_order` |
| M. NEW Account context carries `subaccount_id` + `entitlements` from authenticate() | covered by E2E above + `test_b_auth_module_exposes_authenticate` |

All tests pass; the framework is provably ready for a real Webull
plugin implementation. The next operator step is authenticated review
of the real Webull API surface against this readiness package, then
approval to scope the real plugin.


## Architecture mapping

| Webull feature | OpenAlgo contract | Readiness | Notes |
|---|---|---|---|
| Direct OpenAPI signature auth | `BrokerCapabilities.auth_modes = [AuthMode.SIGNATURE]` | ✅ ready | Plugin's authenticate() builds the HMAC and stores it in AccountContext.extra |
| Connect API OAuth (third-party) | `BrokerCapabilities.auth_modes = [AuthMode.OAUTH]` | ✅ ready | Two plugins can ship for the two auth flavors, or one plugin with both modes declared |
| `market` parameter (US / HK / etc.) | `supported_regions` and `supported_venue_codes` | ✅ ready | Maps to a region per market |
| `instrument_type` STK/OPT/FUT/CRYPTO/EVENT | `AssetClass.EQUITY/OPTION/FUTURE/PERPETUAL/...` (Phase 1a) | ✅ ready | Webull "EVENT" maps to AssetClass.OTHER for now; revisit after first contract |
| `combo_type` (combo orders) | `ComboType` enum + `NormalizedComboOrderRequest` (Phase 8) | ✅ ready | Webull's documented combo families fit |
| `entrust_type` LMT/MKT/STP_LMT/STP_MKT | `OrderType.LIMIT/MARKET/STOP_LIMIT/STOP` (Phase 1a) | ✅ ready | |
| Quantity entrust_type QTY / AMOUNT | `QuantityUnit.WHOLE / NOTIONAL` (Phase 1a) | ✅ ready | |
| Sessions CORE / ALL / NIGHT | `Session.REGULAR` / `Session.EXTENDED` / `Session.POST_MARKET` (Phase 1a) | ✅ ready | "ALL" maps to a leg-level session selector |
| Options legs CALL / PUT | `OptionRight.CALL/PUT` + region symbol_display (Phase 2) | ✅ ready | US region's `symbol_display.option_right_codes = ["CALL","PUT"]` |
| Options expiry YYYY-MM-DD | US region's `symbol_display.date_format = "YYYY-MM-DD"` | ✅ ready | |
| MQTT market data feed | `BrokerMarketDataStream` Protocol with `transport=StreamTransport.MQTT` | ✅ ready | Concrete adapter class would wrap paho-mqtt or similar |
| gRPC trade events | `BrokerOrderEventStream` Protocol with `transport=StreamTransport.GRPC` | ✅ ready | Concrete adapter would wrap grpcio + the Webull proto |
| Per-product capability differences | `ProductCapabilities` (Phase 8) | ✅ ready | Equity supports fractional, futures don't — declared per-product |
| Sandbox / paper environment | per-environment plugin or env-flag | ✅ ready | Same pattern as Schwab paper |
| HK / SG markets | `MarketFamily` does not yet have HK/SG entries | ⏸ extend enum | Add `HK_STOCK`, `SG_STOCK` to `MarketFamily` when Webull HK plugin lands; non-blocking for US-only Webull |
| Event contracts | not modeled | ⏸ deferred | New `AssetClass.EVENT` could be added when needed |

## Auth modes

Webull ships two auth flavors:

* **Direct OpenAPI** — Per-request HMAC signature using a secret key.
  Plugin's `authenticate()` returns an `AccountContext` whose
  `extra["api_key"]` and `extra["secret_key"]` carry the credentials;
  the order/quote API helpers compute the signature on each call.
  `BrokerCapabilities.auth_modes = [AuthMode.SIGNATURE]`.

* **Connect API (OAuth)** — Three-legged OAuth where Webull is the
  identity provider. Plugin's `authenticate()` runs the OAuth flow
  and stores the access token in `AccountContext.extra["access_token"]`.
  `BrokerCapabilities.auth_modes = [AuthMode.OAUTH]`.

Both can coexist on the same plugin via `auth_modes = [SIGNATURE,
OAUTH]` and a `WEBULL_AUTH_MODE` env var the operator sets per
deployment.

## Combo orders

Webull's `combo_type` field maps onto `ComboType`:

| Webull combo_type | ComboType |
|---|---|
| NORMAL (single) | SINGLE |
| OCO | OCO |
| OTO / TRIGGER | OTO |
| BRACKET | BRACKET |
| CONDITIONAL | OTO (with metadata flag) |
| MULTI_LEG | MULTILEG_OPTIONS |

Note: Webull's docs list more combo flavors than ComboType currently
covers. When the plugin lands, additional values can be added without
breaking the existing Schwab mapping above.

## Streaming

* MQTT market data — the plugin opens an MQTT connection (paho-mqtt
  or aiomqtt) and dispatches each topic to the appropriate callback.
  `transport=StreamTransport.MQTT`. Disconnect handling is per-plugin.
* gRPC trade events — plugin opens a streaming gRPC RPC on the
  Webull trade-event service and dispatches per event. `transport=
  StreamTransport.GRPC`. Reconnect logic is per-plugin.

The streaming registry (`services/broker_streaming_registry.py`)
holds at most one stream per broker per kind. Webull would register
two: market-data MQTT and order-event gRPC.

## Open questions (operator/business — not framework)

These are NOT framework gaps. Plugin implementation is gated on
human review of the authenticated Webull OpenAPI docs.

1. **Sandbox vs live URL set.** Plugin needs both endpoints in the
   same plugin.json or two separate plugins.
2. **HK / SG markets.** Need to add `HK_STOCK`, `SG_STOCK` to the
   `MarketFamily` enum when the plugin starts supporting them.
3. **gRPC stub generation.** Webull ships .proto files; the plugin's
   build pipeline needs `grpcio-tools` or `betterproto2`.
4. **MQTT topic naming.** Webull's documented topic structure is
   straightforward but cents-vs-fractional pricing differs across
   markets — needs verification.
5. **Event contract (Webull EVENT instrument_type).** Not modeled
   today; if the operator needs them, add an `AssetClass.EVENT`
   value.
6. **Rate limits.** Webull publishes per-endpoint rate limits;
   plugin's `Limiter` needs configuration.

## Conclusion

The framework is sufficient. Plugin implementation requires:

1. Operator captures Webull OpenAPI credentials (key + secret OR
   Connect OAuth client).
2. Human reviewer reads authenticated OpenAPI + gRPC + MQTT docs.
3. Plugin author maps the docs to the existing contracts above.
4. `tests/compliance/test_webull_compliance.py` with `STRICT = True`
   gates the merge.

## References

* ADR 0008 — Promoted dispatch fail-closed and AccountContext model
* ADR 0012 — Broker plugin compliance harness
* ADR 0013 — Combo order model
* ADR 0014 — Broker streaming contracts
* ADR 0015 — Product-specific capability matrix
* Webull OpenAPI portal: https://developer.webull.com/
