# Future broker onboarding checklist

This checklist is the contract between OpenAlgo's framework and any
new broker plugin (Schwab, Webull, Alpaca, IBKR, an unnamed APAC
broker, etc.). The framework guarantees a stable contract; the
plugin author guarantees these items before the plugin can merge.

The checklist covers **architecture readiness** only. It does not
imply any specific broker's API is supported — that is plugin
implementation work driven by authenticated API documentation,
credentials, and UAT, all of which sit outside this repo.

## Required before opening a PR

### 1. Plugin manifest (`broker/<code>/plugin.json`)

* `Plugin Name`, `Version`, `Author` populated.
* **`supported_regions`** declared as a non-empty list. India brokers
  use `["india"]`; non-India brokers list one or more of `us`, `eu`,
  `uk`, `crypto`. **The loader rejects any non-legacy plugin missing
  this field as of Phase 1 (T-03).**
* **`broker_type`** declared explicitly. India brokers use
  `"IN_stock"`; non-India brokers MUST declare an explicit value
  (no implicit India default — Phase 1 T-04).
* **`market_families`** declared.
* **`default_currency`** and **`base_currency`** declared.
* `requires_v1_compat` set to `true` if the broker plugs into the v1
  India lane (legacy brokers); `false` for v2-only brokers.
* If streaming is supported: **`topic_format`** declared
  (`"venue:symbol"` is the default). Phase 5 (T-21) — the WS router
  consults this capability rather than substring-matching on India
  venue codes.
* If the broker reports prices in minor units (cents, paise, satoshi):
  **`minor_unit_divisor`** declared.
* If the broker requires market-price-protection for MARKET orders:
  **`requires_market_price_protection: true`** (Phase 5 T-22).
* If the broker requires SL-M → SL conversion:
  **`requires_slm_to_sl_conversion: true`** (Phase 5 T-22).

### 2. Authentication module (`broker/<code>/api/auth_api.py`)

* OAuth2, API-key, or refresh-token flow as required by the broker.
* Stores tokens via the standard `database.auth_db` interface — does
  NOT carry its own session table.
* Daily token-expiry handling matches the broker's documented schedule.

### 3. Order-routing module (`broker/<code>/api/order_api.py`)

* `place_order_api(data, auth_token) -> (status, response_data, order_id)`
  signature.
* `modify_order_api`, `cancel_order_api` if supported by the broker.
* Promoted-lane translator at `broker/<code>/translator.py` exposing
  `install_<code>_translator(registry)` — only required for the v2
  lane (`API_V2_<CODE>=1` flips the broker over).

### 4. Account/holdings/positions/orderbook/tradebook adapters

Located under `broker/<code>/api/` with the standard signatures used
by `broker/zerodha/`, `broker/dhan/`, `broker/angel/`. Promoted-lane
brokers register `BrokerAccountAdapter`, `BrokerStreamingAdapter` per
the contracts in `domain/`.

### 5. Mapping module (`broker/<code>/mapping/`)

* OpenAlgo symbol ↔ broker symbol round-trip.
* OpenAlgo venue ↔ broker exchange round-trip.
* OpenAlgo product/price-type ↔ broker product/price-type round-trip.

### 6. Master-contract loader (`broker/<code>/database/master_contract_db.py`)

* Refresh policy declared in plugin.json's
  `master_contract_refresh_policy` — daily, on-login, on-startup, etc.
* Loader writes to `database.instruments_repo` (canonical) and
  optionally to `database.symbol.SymToken` for India v1 brokers.

### 7. README (`broker/<code>/README.md`)

* Which regions the broker covers (India / US / EU / UK / crypto).
* Which venues the broker supports.
* Which products / price-types are supported.
* Authentication style (OAuth2 vs API key vs refresh token).
* Known limitations / unsupported features (PDT enforcement, T+1
  vs T+0 settlement quirks, custom tick-size behavior).
* Any operator-controlled environment variables specific to this
  broker (e.g. paper vs live endpoint URLs).

### 8. Tests

* **Mock fixtures** or **paper-API smoke test** demonstrating
  end-to-end order flow without real credentials. The mock plugins at
  `broker/_mock_schwab_like/` and `broker/_mock_webull_like/` are the
  reference style.
* **Parity harness** under `tests/parity/baseline/parity_v2_<code>_<region>.py`
  if the broker plugs into the v2 lane.
* **Capability conformance** — `tests/contracts/test_v6_region_plugin_contract_complete.py`
  exercises the manifest; the broker plugin should not require new
  test code there.
* **Lane-isolation literal scan** — broker `api/data.py` files that
  declare a non-India `supported_regions` are auto-included in the
  literal scan; they MUST NOT carry `Asia/Kolkata` / `IST` literals
  (Phase 2 T-10 enforced).

## Non-requirements (explicitly out of scope)

* No claim about real Schwab, Webull, Alpaca, or IBKR API
  compatibility. The mock plugins prove the contract surface, not
  API compatibility.
* No multi-broker-per-instance support. One broker per OpenAlgo
  deployment (per ADR 0001).
* No re-architecture of `domain/orders.NormalizedOrderRequest`,
  `domain/instrument_ref.py`, `domain/account_context.py` — these
  are the stable surface every broker plugin programs against.

## Reference plugins

| Plugin | Type | Use as a model for |
|--------|------|--------------------|
| `broker/zerodha/` | India v1 + v2 | Indian discount broker with mature v2 translator |
| `broker/dhan/` | India v1 + v2 | Order routing + WebSocket streaming reference |
| `broker/angel/` | India v1 + v2 | OAuth2 + multi-stream feed pattern |
| `broker/_mock_schwab_like/` | mock | Non-India plugin contract surface |
| `broker/_mock_webull_like/` | mock | Non-India + crypto-style streaming |

## Where to look when something fails

* `tests/contracts/test_lane_isolation.py` — promoted-lane import +
  literal scan rules.
* `tests/contracts/test_v6_closing_invariants.py` — the single
  release-gate test that re-runs every v4/v5/v6 invariant.
* `docs/refactor/release-gate-dashboard.md` — one-page "is OpenAlgo
  ready for X" status doc.
* `scripts/audit/classify_files.py --check` — file-classification
  drift detector.
