# v6 Phase 5-bis — Complete (translator runtime activation + dispatcher MPP)

* **Branch:** `refactor/v6-phase-5-bis-runtime-activation`
* **Branched from:** `dev` @ `e001c660` (HEAD: v6 Phase 7 merge)
* **Effort:** high — closes the most consequential gap (30 translators previously unreachable).

## Goal achieved

The 30 India v2 translators shipped in Phases 5–7 are now **runtime-activatable**
under operator control via the `API_V2_<BROKER>=1` env flag, and the v2
dispatcher applies Market Price Protection (MPP) for the 9 brokers
whose v1 `transform_data` requires it. The wire payload sent to those
brokers from the v2 lane is now bit-identical with the v1 lane.

## What shipped

### `services/india_translator_bootstrap.py`
* `INDIA_TRANSLATORS` table — 30 entries, one per India broker, each
  pointing at its `install_<broker>_translator()` function.
* `install_enabled_india_translators()` — reads `API_V2_<BROKER>` env
  flags, calls install fn for each on broker; never blocks app startup
  on individual broker failures.
* `install_all_india_translators_for_tests()` — bypasses env flags
  for tests that need the full registry.
* `is_translator_flag_on(broker_code)` — convenience helper.

### `services/promoted_mpp_service.py`
* `BROKERS_REQUIRING_MPP_MARKET = {flattrade, motilal, pocketful,
  samco, kotak, ibulls, indmoney, shoonya, zebu}` — 9 brokers whose
  v1 `transform_data` converts MARKET → LIMIT via LTP+slab.
* `BROKERS_REQUIRING_MPP_SLM = {motilal, samco}` — 2 brokers that
  also convert SL-M → SL via trigger+slab.
* `apply_mpp_if_required(order, broker_code, instrument, auth_token)`
  — pre-translator hook. Returns `model_copy` with order_type ∈
  {LIMIT, STOP_LIMIT} and protected price, or the original order
  unchanged. No-ops for:
  * brokers not in the MPP sets
  * non-MARKET / non-STOP order types
  * missing `auth_token` (cannot fetch quote)
  * failed quote fetch / `ltp <= 0`
  * operator override `API_V2_MPP_<BROKER>=0`
* Quote fetching falls back to the broker's existing v1
  `broker.<code>.api.data.BrokerData.get_quotes()` — no new v2 quote
  adapter is required.
* Per Q4 option B (architecturally clean): translators stay pure;
  MPP is dispatcher-level pre-translator transformation.

### Wired into `app.py`
After `load_broker_capabilities()`, `setup_environment()` calls
`install_enabled_india_translators()`. Per-broker activations are
logged at INFO level. App startup never fails due to a broken
broker.

### Wired into `restx_api/v2/orders.py:_dispatch_promoted`
Between `check_order(...)` and `promoted.validate(...)`, the dispatcher
calls `apply_mpp_if_required(...)`. The translator receives the
post-MPP order (which is LIMIT / STOP_LIMIT for affected brokers and
unchanged for everyone else).

### Tests added
* `tests/services/test_v6_india_translator_bootstrap.py` — 9 tests +
  30 parametrized = **39 tests**:
  * 30 install paths resolve to callables
  * Bootstrap is no-op without flags
  * Only flagged brokers activate
  * Falsy values don't activate
  * `install_all_india_translators_for_tests` registers all 30
  * `is_translator_flag_on` honors env truthy values
  * Failed install on one broker doesn't block others
* `tests/services/test_v6_promoted_mpp_service.py` — **27 tests**:
  * 9 brokers parametrized for MPP_MARKET membership
  * 5 non-MPP brokers parametrized for MPP_MARKET non-membership
  * No-op when broker doesn't need MPP / order isn't MARKET-or-STOP
    / auth missing / quote fetch fails / ltp ≤ 0
  * BUY price = LTP * (1 + slab%); SELL = LTP * (1 - slab%)
  * SL-M → SL_LIMIT for motilal (and samco), no-op for flattrade
  * Operator can disable via `API_V2_MPP_<BROKER>=0`
  * Options uses OPT slab table, equity uses EQ slab
* `tests/contracts/test_v6_closing_invariants.py` — 2 new invariants:
  * v6-7: `INDIA_TRANSLATORS` has 30 entries; every broker's
    translator file exists.
  * v6-8: `BROKERS_REQUIRING_MPP_MARKET` has 9 entries;
    `BROKERS_REQUIRING_MPP_SLM` has 2; `apply_mpp_if_required` is
    callable.

### Classification
`scripts/audit/classification_rules.yaml` now classifies
`services/india_translator_bootstrap.py` and
`services/promoted_mpp_service.py` as **PROMOTED_CORE**.
`docs/refactor/file_classification.md` regenerated: **879 files
classified**, no drift (was 877; +2).

## Comprehensive test gate (passed)

| Step | Result |
|---|---|
| `uv run pytest tests/ -x --tb=short` | **2613 passed, 7 skipped, 2 xfailed** in 4:10 (was 2543; +70) |
| `uv run pytest -x tests/contracts/test_v4_closing_invariants.py tests/contracts/test_v5_closing_invariants.py tests/contracts/test_v6_closing_invariants.py` | **35 passed** (was 33; +2 new v6 invariants) |
| `uv run python tests/parity/run_parity.py` | **41/41** verify-mode harnesses |
| `uv run python tests/parity/run_parity.py --lane v1` | **11/11** v1-lane harnesses |
| `uv run python tests/parity/run_parity.py --lane v2` | **41/41** v2-lane harnesses |
| `uv run python scripts/audit/classify_files.py --check` | exit 0 — 879 files / no drift |
| `uv run python scripts/audit/route_fallback_scan.py` | 51 routes |
| `uv run python scripts/audit/symtoken_callers.py` | 0 PROMOTED_LEAK |
| `uv run python scripts/audit/canonical_vs_legacy_parity.py` | 13 pairs |
| `npm test -- --run` (frontend) | **160 passed across 15 files** |
| `npm run lint:literals` | exit 0 — 256 files / 0 violations |

## Operator notes (production cutover)

To put a broker on the v2 lane:

1. Set `API_V2_<BROKER>=1` in the operator's `.env`.
2. Restart the app. Bootstrap log line confirms registration:
   `"v6 Phase 5-bis: 1 India v2 translator(s) activated: zerodha"`.
3. Subsequent `/api/v2/orders` requests for that broker route through
   the new translator; `parity_v2_<broker>_india` harnesses pin the
   wire payload.

To disable MPP for a single broker (allow raw MARKET orders):

* Set `API_V2_MPP_<BROKER>=0` in `.env`. The dispatcher passes MARKET
  orders straight through to the translator unchanged. The translator
  emits a MARKET-typed native payload; the broker may reject it
  (which is the broker's documented behavior).

To roll back v2 for a broker:

* Set `API_V2_<BROKER>=0` (or unset). Restart. The dispatcher falls
  back to the legacy v1 lane; translator stays registered (harmless)
  but is never selected.

## Next phase

`v6-phase-1-bis-frontend-cleanup` — frontend per-component cleanups,
component-test-only verification per Q3 default.
