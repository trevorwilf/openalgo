# ADR 0022 — Mock Schwab/Webull broker plugins for framework readiness

Status: accepted (v3 Phase 6)
Date: 2026-04-25

## Context

Phases 0-5 closed every framework leak the v3 prompt's expert reviews
called out:

* Boundary classification + literal scanner (Phase 0/1).
* v2 quotes/bars fail-closed for non-India brokers (Phase 2).
* Resolver hardening + identifier helpers (Phase 3).
* Service-layer region gates (Phase 4).
* Region API completeness (Phase 5).

The remaining question is: *is the framework actually ready for a
real Schwab or Webull plugin to plug in?* The only honest way to
answer that is to drive a fully-mocked Schwab-like and Webull-like
plugin through the entire promoted lane end-to-end and measure
which contracts pass and which break.

**Non-negotiable**: no real Schwab API code, no real Webull API
code, no real network calls, no real OAuth flows. Everything is
deterministic in-memory fixtures + mock translators / adapters /
streams. The output is the operator's evidence package — "yes the
framework is ready, here's where to plug in real broker code."

## Decision

Two new broker plugins are added under `broker/` with the
underscore-prefixed names that mark them as
framework-test-only:

* `broker/_mock_schwab_like/`
* `broker/_mock_webull_like/`

Each contains:

```
plugin.json
PROMOTED                 (sentinel; content "MOCK_FRAMEWORK_TEST_ONLY")
__init__.py
api/__init__.py
api/auth_api.py          → load_credentials, authenticate → AccountContext
api/account_api.py       → get_account, get_positions
api/order_api.py         → BrokerOrderTranslator (validate / to_native /
                           to_native_combo / send_native /
                           from_native_order_response) +
                           SENT_NATIVE_PAYLOADS spy list
api/quote_api.py         → BrokerQuoteAdapter
api/bar_api.py           → BrokerBarAdapter
api/stream_api.py        → BrokerMarketDataStream + BrokerOrderEventStream
sync/__init__.py
sync/instrument_sync.py  → run_sync() seeds 5 instruments + broker map
```

### Schwab-like plugin shape

* `broker_type: "US_stock"`, `supported_regions: ["us"]`
* venues: XNYS, XNAS, ARCX, BATS, IEXG
* asset classes: EQUITY, ETF, OPTION
* order types: MARKET, LIMIT, STOP, STOP_LIMIT, TRAILING_STOP
* TIF: DAY, GTC, GTD, FOK, IOC
* sessions: REGULAR, PRE_MARKET, POST_MARKET
* quantity units: WHOLE, FRACTIONAL, NOTIONAL
* combo types: SINGLE, OTO, OCO, OTOCO, COMBO, MULTILEG_OPTIONS
* auth_modes: OAUTH
* account_context_supports: account_hash, entitlements
* streaming: order_events + market_data both via WebSocket

The native-shape translator emits `orderStrategyType` /
`orderLegCollection` mapping the Schwab combo vocabulary
(`OTOCO → TRIGGER_AND_OCO`, `COMBO → MULTI_LEG`, etc.).

### Webull-like plugin shape

* venues: XNYS, XNAS
* asset classes: EQUITY, OPTION, SPOT
* combo types: SINGLE, OCO, OTO, OTOCO
* auth_modes: SIGNATURE, OAUTH
* account_context_supports: subaccount_id, entitlements
* streaming: market_data via MQTT, order_events via gRPC

The native shape uses `combo_type` + `entrust_type` + `orders[]` with
the Webull subaccount id passed through.

### New endpoint

`POST /api/v2/orders/combo` accepts `NormalizedComboOrderRequest`,
applies the same fail-closed contract as v2 orders (translator
required, combo_type must be in the broker's
`supports_combo_types` capability list), and dispatches via the
translator's `to_native_combo`. Tests cover the dispatch matrix and
the per-broker native shape.

### Compliance harness extensions

`tests/compliance/broker_plugin_compliance.py` already covered
contracts A-I. Phase 6 adds two helper assertions (callable from
broker-specific compliance tests):

* `assert_quote_adapter_compliance(adapter)` — verifies
  `broker_code` matches and `get_quote` is callable.
* `assert_bar_adapter_compliance(adapter)` — verifies
  `broker_code` matches and `get_bars` is callable.

The mock plugins drive every contract A-I via
`tests/compliance/test_mock_schwab_like_compliance.py` and
`tests/compliance/test_mock_webull_like_compliance.py`.

### End-to-end test coverage

* `tests/e2e/test_mock_schwab_like_e2e.py` — single-leg AAPL BUY
  through `/api/v2/orders` and an OTOCO combo through
  `/api/v2/orders/combo`. Asserts the legacy
  `services.place_order_service.place_order_with_auth` is never
  called.
* `tests/e2e/test_mock_webull_like_e2e.py` — single-leg MSFT LIMIT
  via `/api/v2/orders` (with the Webull-specific account resolver
  registered so the AccountContext carries `subaccount_id`) plus a
  streaming subscribe → 3 events → unsubscribe lifecycle test for
  both MQTT (market data) and gRPC (order events).

### Updated readiness docs

`docs/refactor/schwab_readiness.md` and
`docs/refactor/webull_readiness.md` open with the explicit
disclaimer:

> The mock plugin proves OpenAlgo's framework is ready. It does NOT
> prove API compatibility with real Schwab/Webull. Real plugin
> implementation requires authenticated docs review, credentials,
> UAT/paper validation, and human approval.

A new "Framework readiness verification" section in each doc lists
the verified contracts (A-I from the harness, plus combo dispatch
and streaming lifecycle) and links to the corresponding test files.

## Consequences

* Operators have an evidence package: 18 compliance tests + 4 combo
  dispatch tests + 4 e2e tests pass against the two mock plugins,
  proving every promoted-lane surface (auth → instrument resolve →
  capability check → translator → native send → response normalize)
  works end-to-end for non-India brokers.
* The mock plugins serve as canonical examples for non-India broker
  authors — they show every required file shape and contract
  surface.
* The lane-isolation contract holds: both mock plugins live under
  `broker/` with PROMOTED sentinels, so the literal scanner and
  import lock auto-discover them as promoted territory.
* No real broker integration. The disclaimer in the readiness docs
  is firm.

## Alternatives considered

* **Build a real Schwab plugin alongside the mock.** Rejected per
  operator instructions — out of scope. Real implementation needs
  authenticated doc review, credentials, and human approval.
* **Drop the streaming protocol from the mock plugins.** Rejected —
  the streaming handle / lifecycle / disconnect surface is part of
  the framework readiness story; without it the e2e test misses the
  market-data and order-event paths.
* **Run mock e2e tests against the production app.py boot.**
  Rejected — the minimal Flask app shell from
  `tests/api_v2/conftest.py` is faster and exercises the same
  blueprint code path. The full app boot is covered by other
  smoke tests.

## References

* `broker/_mock_schwab_like/` and `broker/_mock_webull_like/` —
  plugin scaffolding
* `restx_api/v2/orders_combo.py` — `/api/v2/orders/combo` endpoint
* `tests/compliance/test_mock_schwab_like_compliance.py` and
  `test_mock_webull_like_compliance.py` — harness invocations
* `tests/api_v2/test_orders_combo.py` — combo dispatch tests
* `tests/e2e/test_mock_schwab_like_e2e.py` and
  `test_mock_webull_like_e2e.py` — end-to-end flow tests
* `docs/refactor/schwab_readiness.md`,
  `docs/refactor/webull_readiness.md` — readiness docs (updated)
* `docs/refactor/broker_compliance_matrix.md` — updated matrix
* ADR 0012 (compliance harness), ADR 0013 (combo orders), ADR 0014
  (streaming), ADR 0015 (product capabilities), ADR 0017–0021
