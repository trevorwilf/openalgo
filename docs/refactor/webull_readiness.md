# Webull Readiness Package

Status: framework-only (Phase 8). Plugin implementation deliberately
out of scope per the v2 prompt.

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
