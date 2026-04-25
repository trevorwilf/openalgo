# Schwab Readiness Package

Status: framework-only (Phase 8). Plugin implementation deliberately
out of scope per the v2 prompt.

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
