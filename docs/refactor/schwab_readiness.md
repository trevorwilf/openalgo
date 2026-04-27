# Schwab Readiness Package

> **The mock plugin proves OpenAlgo's framework is ready. It does NOT
> prove API compatibility with real Schwab. Real plugin implementation
> requires authenticated docs review, credentials, UAT/paper validation,
> and human approval.**

Status: framework-only (Phase 8 v2 + Phase 6 v3 + Phase 11 v4).
Plugin implementation deliberately out of scope per the v2/v3/v4
prompts.

## v5 framework-readiness extension (Phase 10)

v5 closes the v4 deferred bis-phases and adds the structured-error
+ observability surface a real Schwab plugin will emit. Each new
surface is verified by a v5 contract test:

| Surface | Status | Test |
|---|---|---|
| Structured market-context error taxonomy (ADR 0029) | ✅ pass | `tests/contracts/test_v5_structured_errors_emitted.py` |
| Promoted-request observability label set (ADR 0030) | ✅ pass | `tests/contracts/test_v5_observability_labels_complete.py` |
| `BrokerCapabilities.supports_sandbox` declarable | ✅ pass | `tests/plugin_loader/test_v5_supports_sandbox_capability.py` |
| `BrokerCapabilities.supports_options` declarable | ✅ pass | `tests/plugin_loader/test_v5_supports_options_capability.py` |
| `BrokerCapabilities.supports_screener_providers` declarable | ✅ pass | `tests/plugin_loader/test_v5_supports_screener_capability.py` |
| `BrokerCapabilities.supports_combo_types` (top-level, single source) | ✅ pass | `tests/contracts/test_v5_combo_capability_single_source.py` |
| Account context entitlement contract | ✅ pass | `tests/domain/test_v5_account_context_entitlements.py` |
| DST correctness for promoted venues (NY/London/Paris) | ✅ pass | `tests/contracts/test_v5_dst_correctness.py` |
| `/api/v1/*` deprecation headers (Sunset, Deprecation) | ✅ pass | `tests/contracts/test_v5_india_v2_readiness.py::test_v1_route_emits_deprecation_headers` |
| Dual-lane parity runner (`--lane v1\|v2`) | ✅ pass | `tests/contracts/test_v5_india_v2_default_on.py::test_run_parity_supports_lane_filter` |

A real Schwab plugin will emit:

* `unsupported_region`, `missing_region_context` — when an account's
  region cannot be resolved before order admission.
* `missing_translator` — if the SchwabBrokerTranslator is somehow
  not registered (defensive; should never fire in production).
* `unsupported_capability` with `dimension` ∈ `DIMENSIONS` — when
  the order ticket UI sends a TIF / order type / session combination
  Schwab does not support for the requested asset class.
* `entitlement_required` — for Schwab options levels, market-data
  entitlements, extended-hours access.
* `unsupported_provider` with `feature` ∈ `FEATURES` — when the UI
  asks for a feature Schwab does not provide (e.g., Chartink
  screener).

Every promoted Schwab request will emit one structured-log line
with the canonical 10-label set (`region_code`, `broker_code`,
`venue_code`, `instrument_id`, `currency`, `provider_code`,
`capability_source`, `legacy_lane=false`, `route="v2"`,
`request_id`). See `docs/observability/promoted_request_labels.md`.

## v4 framework-readiness extension (Phase 11, ADR 0023)

v4 adds the following surfaces beyond what v3 already proved. Each
maps to a contract test in `tests/contracts/` or
`tests/<surface>/test_*.py`:

| Surface | Status | Test |
|---|---|---|
| Strict promoted plugin schema (ADR 0025) | ✅ pass | `tests/plugin_loader/test_strict_promoted_schema.py::test_mock_schwab_passes_strict_mode` |
| BrokerPositionAdapter | ✅ scaffolded | `broker/_mock_schwab_like/api/position_balance_adapters.py:MockSchwabLikePositionAdapter` |
| BrokerBalanceAdapter | ✅ scaffolded | `broker/_mock_schwab_like/api/position_balance_adapters.py:MockSchwabLikeBalanceAdapter` |
| `/api/v2/positions` adapter dispatch | ✅ pass | `tests/api_v2/test_positions_failclosed_non_india.py::test_non_india_with_adapter_returns_normalized_positions` |
| `/api/v2/balances` adapter dispatch | ✅ pass | `tests/api_v2/test_balances_failclosed_non_india.py::test_non_india_with_adapter_returns_normalized_balance` |
| Sandbox provider (US, mock data) | ✅ in framework | `tests/sandbox/test_provider_contract.py::test_us_provider_t2_equity_settlement` |
| Options provider (US, OCC OSI) | ✅ in framework | `tests/options/test_provider_contract.py::test_us_parse_aapl_call` |
| Screener provider | ✅ India only (US out of v4) | `tests/screeners/test_provider_contract.py::test_chartink_implements_contract` |
| Plugin diagnostics endpoint | ✅ pass | `tests/plugin_loader/test_diagnostics_endpoint.py` |
| v1 hard-block for non-India | ✅ pass | `tests/contracts/test_v1_lane_blocks_non_india.py` |
| Framework readiness gate | ✅ pass | `tests/contracts/test_framework_ready_for_real_brokers.py` |

The mock plugin now demonstrates the complete promoted lane: strict
plugin schema, order translator, position + balance adapters,
quote / bar adapter contracts, market-data + order-event streaming,
account context (account_hash), instrument sync, combo orders,
fail-closed v1 hard-block. **Real Schwab plugin implementation
remains the next-step work blocked on official API validation.**

## Framework readiness verification (Phase 6 v3, ADR 0022)

A fully-mocked Schwab-LIKE plugin under
`broker/_mock_schwab_like/` exercises every promoted-lane contract
end-to-end with deterministic in-memory fixtures. Verified contracts:

| Contract | Test |
|---|---|
| A. Metadata (plugin.json schema) | `tests/compliance/test_mock_schwab_like_compliance.py::test_a_metadata_plugin_json_validates` |
| B. Auth — `authenticate()` returns `AccountContext` with `account_hash` | `test_b_auth_module_exposes_authenticate` |
| C. Account snapshot uses `NormalizedAccountSnapshot` shape | `test_c_account_snapshot_uses_normalized_shape` |
| D. Translator implements `validate` / `to_native` / `from_native_order_response` | `test_d_translator_module_exists` |
| E. Quote + bar adapters | `test_e_market_data_adapters_optional` |
| F. Instrument sync seeds `instruments` + `broker_instrument_map` | `test_f_instrument_sync_optional` |
| G. Rule matrix optional | `test_g_rule_matrix_optional` |
| H. Lane isolation (no India literals, no legacy imports) | `test_h_lane_isolation_imports_and_literals` |
| I. Fail-closed capability metadata | `test_i_fail_closed_capability_metadata` |
| J. NEW Combo orders — OTOCO / MULTILEG_OPTIONS dispatch | `tests/api_v2/test_orders_combo.py::test_combo_otoco_dispatch_to_schwab_like` |
| K. NEW Streaming subscribe → 3 events → unsubscribe lifecycle | `tests/e2e/test_mock_webull_like_e2e.py::test_e2e_mock_webull_streaming_handle_lifecycle` (Schwab uses identical handle/lifecycle shape) |
| L. NEW End-to-end equity order through `/api/v2/orders` with no legacy fallback | `tests/e2e/test_mock_schwab_like_e2e.py::test_e2e_mock_schwab_single_equity_order` |
| M. NEW End-to-end OTOCO combo order through `/api/v2/orders/combo` | `tests/e2e/test_mock_schwab_like_e2e.py::test_e2e_mock_schwab_otoco_combo_order` |

All tests pass; the framework is provably ready for a real Schwab
plugin implementation. The next operator step is authenticated review
of the real Schwab API surface against this readiness package, then
approval to scope the real plugin.

## Architecture mapping

| Schwab feature | OpenAlgo contract | Readiness | Notes |
|---|---|---|---|
| Account hash addressing | `AccountContext.account_hash` (Phase 3) | ✅ ready | Tested in `test_account_context_supports_account_hash` |
| Multi-account user | `AccountContext` + per-broker `register_account_resolver` (Phase 3) | ✅ ready | Resolver maps token + accounts payload to one canonical `AccountContext` per request |
| OAuth lifecycle | `BrokerCapabilities.auth_modes = [AuthMode.OAUTH]` + `master_contract_refresh_policy` (Phase 4) | ✅ ready | Refresh-token rotation handled in `services/account_context_service` |
| OrderStrategyType (SINGLE/OCO/OTO/OTOCO/COMBO/MULTILEG) | `NormalizedComboOrderRequest` (Phase 8) | ✅ ready | Per-product `supports_combo_types` declares what each asset class supports |
| Streamer (WebSocket) for quotes/depth | `BrokerMarketDataStream` Protocol (Phase 8) | ✅ ready | Register concrete impl via `register_market_data_stream` |
| Streamer for order events | `BrokerOrderEventStream` Protocol (Phase 8) | ✅ ready | Register concrete impl via `register_order_event_stream` |
| Sandbox / paper trading toggle | per-environment plugin flag in `features` | ✅ ready | Schwab plugin would declare two `BrokerCapabilities` (paper / live) and the operator selects via env |
| Per-instrument fractional / extended-hours | `ProductCapabilities` per asset class | ✅ ready | Equity vs option vs future declared separately |
| US extended hours (PRE/POST) | `Session.PRE_MARKET` / `Session.POST_MARKET` (Phase 1a) + region session templates (Phase 2) | ✅ ready | US region plugin already declares 04:00-09:30 / 16:00-20:00 ET |
| Settlement T+1 | `VenueSeed.settlement_template = "T+1"` in US region plugin (Phase 2) | ✅ ready | |
| Per-account market data entitlements | `AccountContext.entitlements: list[str]` (Phase 3) | ✅ ready | Phase 8 `rule_enforcement.check_order` accepts the field but does not yet read it (deferred to plugin work) |
| Brokerage Activity stream / GET account activity | not modeled | ⏸ deferred | New `BrokerActivityStream` Protocol can be added when the plugin lands |

## OAuth lifecycle mapping

Schwab Trader API uses three-legged OAuth with refresh tokens that
rotate every 7 days. Mapping:

* Initial login → broker plugin's `authenticate()` returns
  `AccountContext` with the access token in `extra["access_token"]`
  and the refresh token in `extra["refresh_token"]`.
* `master_contract_refresh_policy = {"timezone":"America/New_York",
  "cutoff_local":"06:30","frequency":"daily"}` — pre-market refresh
  runs the master-contract download.
* Refresh-token rotation happens in a background task the plugin
  starts at `authenticate_broker()` time. The token is persisted
  back via the existing `database/auth_db.upsert_auth` API.

## Combo orders

Schwab's `OrderStrategyType` values map 1:1 to `ComboType` enum:

| Schwab | ComboType |
|---|---|
| SINGLE | SINGLE |
| OCO | OCO |
| OTO / TRIGGER | OTO |
| TRIGGER (then OCO) | OTOCO |
| COMBO | COMBO |
| MULTILEG (options) | MULTILEG_OPTIONS |
| BRACKET | BRACKET |
| ICEBERG | ICEBERG |

## Streaming

* Quotes / depth: Schwab Streamer over WebSocket. Plugin implements
  `BrokerMarketDataStream` with `transport=StreamTransport.WEBSOCKET`.
* Order events: same Streamer, separate subscription. Plugin
  implements `BrokerOrderEventStream`.
* Disconnect handling: the Protocol's `on_disconnect` callback
  receives the exception (or None on graceful close). The plugin's
  reconnect loop is its own concern; the contract just demands a
  callback the framework can subscribe to.

## Open questions (operator/business — not framework)

These are NOT framework gaps. Plugin implementation is gated on
human review of the authenticated Schwab Trader API docs.

1. **API key / secret distribution.** Schwab Developer Portal apps
   use a per-app API key + secret pair that the operator must
   register. Need an operator-facing onboarding flow (UI) to capture
   these.
2. **Refresh token persistence.** Schwab tokens are sensitive; how
   they're stored at rest needs operator review (currently `auth_db`
   stores them encrypted with the API_KEY_PEPPER).
3. **Rate limits.** Per-account rate limits exist but are not
   documented publicly; the plugin's rate limiter needs empirical
   tuning.
4. **Sandbox endpoint set.** Trader API has separate sandbox URLs;
   plugin must support both via plugin.json.
5. **Account selection UI.** Multi-account users need a UI to pick
   which account a given trade routes to. Can be the existing
   `subaccount_id` field or a new account picker.
6. **Live data subscription.** Real-time market data costs $$ and
   requires per-user attestation; the plugin needs to either
   broker that signing or limit itself to delayed data.

## Conclusion

The framework is sufficient. Plugin implementation requires:

1. Operator captures Schwab Developer Portal credentials.
2. Human reviewer reads authenticated Trader API docs.
3. Plugin author maps the docs to the existing contracts above.
4. `tests/compliance/test_schwab_compliance.py` with `STRICT = True`
   gates the merge.

## References

* ADR 0008 — Promoted dispatch fail-closed and AccountContext model
* ADR 0012 — Broker plugin compliance harness
* ADR 0013 — Combo order model
* ADR 0014 — Broker streaming contracts
* ADR 0015 — Product-specific capability matrix
* Schwab Developer Portal: https://developer.schwab.com/products/trader-api--individual
