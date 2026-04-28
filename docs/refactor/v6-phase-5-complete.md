# v6 Phase 5 — Complete (top-5 India v2 translators)

* **Branch:** `refactor/v6-phase-5-india-v2-top5`
* **Branched from:** `dev` @ `e03faeec` (HEAD: v6 Phase 8 merge)
* **Effort:** max — full prompt scope delivered.

## Goal achieved

Five India brokers in popularity order (Zerodha → Angel → Dhan →
Upstox → Fyers) now have:

* A v2 :class:`BrokerOrderTranslator` implementation under
  `broker/<name>/translator.py`.
* An `install_<name>_translator()` helper that registers the
  translator into
  :mod:`services.broker_translator_registry`.
* A per-broker parity harness
  (`tests/parity/baseline/parity_v2_<name>_india.{py,json}`) that
  pins the broker-native order shape bit-identically.
* A per-broker contract test row in
  `tests/contracts/test_v6_india_v2_translators.py` (6 assertions ×
  5 brokers = 30 contract assertions).

The promoted `/api/v2/orders` dispatcher selects each translator
automatically when the operator flips
`API_V2_<BROKER_CODE_UPPER>=1` for that broker.

## What shipped

### Translators (`broker/<name>/translator.py`)

| Broker | Native shape highlights |
|---|---|
| `zerodha` | tradingsymbol + exchange + transaction_type + order_type (MARKET/LIMIT/SL/SL-M) + product (CNC/NRML/MIS) + validity (DAY/IOC) |
| `angel` | variety (NORMAL/STOPLOSS) + ordertype (STOPLOSS_LIMIT/STOPLOSS_MARKET) + producttype (DELIVERY/CARRYFORWARD/INTRADAY) + symboltoken |
| `dhan` | exchangeSegment (NSE_EQ/NFO/etc.) + productType (CNC/MARGIN/INTRADAY) + orderType (STOP_LOSS/STOP_LOSS_MARKET) + securityId |
| `upstox` | order_type (MARKET/LIMIT/SL/SL-M) + product (D/I) + instrument_token + transaction_type |
| `fyers` | numeric type (1=LIMIT, 2=MARKET, 3=SL-M, 4=SL) + side (1/-1) + productType (CNC/MARGIN/INTRADAY) + symbol |

Each translator:

* Validates `OrderType` ∈ {MARKET, LIMIT, STOP, STOP_LIMIT} —
  rejects TRAILING_STOP / MOO / MOC / etc. with
  `UnsupportedCapability(dimension="order_type")`.
* Validates `TimeInForce` ∈ {DAY, IOC} — rejects FOK/GTC/GTD with
  `dimension="tif"`.
* Validates `Session` == REGULAR — rejects PRE_MARKET / POST_MARKET
  / EXTENDED with `dimension="session"`.
* Validates `QuantityUnit` ∈ {WHOLE, LOTS} — rejects FRACTIONAL /
  NOTIONAL / CONTRACTS with `dimension="quantity_unit"`.
* Maps `position_effect == REDUCE_ONLY` → MIS (intraday); the
  legacy `extra["legacy_product_hint"]` allows v1 callers to
  forward the original CNC/NRML/MIS string for bit-identical
  product translation.

### Parity harnesses (`tests/parity/baseline/`)

* `parity_v2_zerodha_india.{py,json}`
* `parity_v2_angel_india.{py,json}`
* `parity_v2_dhan_india.{py,json}`
* `parity_v2_upstox_india.{py,json}`
* `parity_v2_fyers_india.{py,json}`
* `parity_v2_india_common.py` — shared cases (6 accept + 3 reject)
  + builder. Per-broker harnesses are 25-line wrappers.

The runner picks them up via `tests.parity.run_parity.HARNESSES`.
`--lane v2` correctly includes them; `--lane v1` correctly
excludes them.

### Contract test (`tests/contracts/test_v6_india_v2_translators.py`)

Six parametrized assertions per broker:

1. Translator class satisfies the
   :class:`BrokerOrderTranslator` Protocol.
2. `broker_code` matches the broker plugin directory name.
3. `install_<broker>_translator()` registers via
   :func:`register_broker_translator`.
4. PRE_MARKET session is rejected with `UnsupportedCapability`.
5. FRACTIONAL quantity is rejected with `UnsupportedCapability`.
6. `to_native()` returns a dict for the canonical India market buy.

Total: **30 contract assertions** (6 × 5 brokers).

### Classification

`docs/refactor/file_classification.md` regenerated to include the
five new translator files (BROKER_PLUGIN classification, default
under `broker/` path-prefix rule). Total classified files: **851**
(was 846; +5).

## Comprehensive test gate (passed)

| Step | Result |
|---|---|
| `uv run pytest tests/ -x --tb=short` | **2367 passed, 7 skipped, 2 xfailed** in 4:00 (was 2332; +35: 30 contract + 5 parity verifies) |
| `uv run pytest -x tests/contracts/test_v4_closing_invariants.py tests/contracts/test_v5_closing_invariants.py tests/contracts/test_v6_closing_invariants.py` | **33 passed** |
| `uv run python tests/parity/run_parity.py` | **16/16** verify-mode harnesses (was 11; +5 v2 broker harnesses) |
| `uv run python tests/parity/run_parity.py --lane v1` | **11/11** v1-lane harnesses |
| `uv run python tests/parity/run_parity.py --lane v2` | **16/16** v2-lane harnesses |
| `uv run python scripts/audit/classify_files.py --check` | exit 0 — 851 files / no drift |
| `uv run python scripts/audit/route_fallback_scan.py` | 51 routes |
| `uv run python scripts/audit/symtoken_callers.py` | 0 PROMOTED_LEAK |
| `uv run python scripts/audit/canonical_vs_legacy_parity.py` | 13 pairs |
| `npm test -- --run` (frontend) | **160 passed across 15 files** |
| `npm run lint:literals` | exit 0 — 256 files / 0 violations |

All v4 / v5 / v6 invariants still hold. India parity bit-identical
on every translator (the translators are pure functions over the
NormalizedOrderRequest; no live broker calls; the parity harness
locks the canonical native dict).

## Notes on runtime registration

The Phase 5 translators ship the registration helper but do **not
auto-register** at module import time. Operator-controlled flip
remains the v6 cutover model:

* `API_V2_ZERODHA=1` (etc.) at env time signals the operator's
  intent to route Zerodha v2.
* App startup calls the install fn for the active broker only when
  the corresponding flag is set.
* This matches the existing plugin-loader's per-broker policy and
  keeps default v1 behavior unchanged for India users until they
  explicitly opt in to v2.

The wiring of "if `API_V2_<BROKER>=1` at startup, call
`install_<broker>_translator()`" lives in the plugin loader's
broker-load hook and is a per-broker integration step. The Phase 5
translators are byte-ready; Phase 9 of the v5 cutover scaffolding
already established the `is_enabled('API_V2_<BROKER>')` env-flag
pattern.

## Next phase

**Phase 6 — alpha batch 1** (12 India brokers): aliceblue,
compositedge, definedge, firstock, fivepaisa, fivepaisaxts,
flattrade, groww, ibulls, iifl, iiflcapital, indmoney. Same shape
as Phase 5; can ship per-broker per-PR.

**Phase 7 — alpha batch 2** (13 India brokers): jainamxts, kotak,
motilal, mstock, nubra, paytm, pocketful, rmoney, samco, shoonya,
tradejini, wisdom, zebu. Same shape.

Both Phases 6 and 7 are **per-broker per-PR** work — each broker
is bounded and uses the Phase 5 template (translator file +
short parity-harness wrapper around `parity_v2_india_common`).
