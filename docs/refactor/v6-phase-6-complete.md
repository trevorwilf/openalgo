# v6 Phase 6 — Complete (alpha batch 1, 12 India brokers)

* **Branch:** `refactor/v6-phase-6-india-v2-alpha-batch1`
* **Branched from:** `dev` @ `7664af23` (HEAD: v6 Phase 5 merge)
* **Effort:** max — full prompt scope delivered.

## Goal achieved

Twelve more India brokers ship v2 translators + parity harnesses,
following the Phase 5 template:

| Broker | Native shape | Notes |
|---|---|---|
| `aliceblue` | exchange + instrumentId + transactionType + product (LONGTERM/INTRADAY/NRML) + orderType (MARKET/LIMIT/SL/SLM) + orderComplexity REGULAR | distinct AliceBlue V2 shape |
| `compositedge` | XTS family (exchangeSegment + exchangeInstrumentID + productType + orderType + orderSide + timeInForce) | XTS-family subclass |
| `definedge` | tradingsymbol + price_type + product_type + order_type (BUY/SELL) | distinct |
| `firstock` | userId + tradingSymbol + transactionType (B/S) + priceType (LMT/MKT/SL-LMT/SL-MKT) + product (C/M/I) | distinct, Noren-shaped |
| `fivepaisa` | OrderType (B/S) + Exchange (N/B/M) + ScripCode + IsIntraday + StopLossPrice | distinct legacy 5paisa |
| `fivepaisaxts` | XTS family | XTS-family subclass |
| `flattrade` | trantype (B/S) + prctyp (LMT/MKT/SL-LMT/SL-MKT) + prd (C/M/I) | Noren / pi-connect |
| `groww` | trading_symbol + segment (CASH/FNO) + product (CNC/MIS/NRML) + order_type (MARKET/LIMIT/STOP_LOSS_LIMIT/STOP_LOSS_MARKET) | distinct |
| `ibulls` | XTS family | XTS-family subclass |
| `iifl` | XTS family | XTS-family subclass |
| `iiflcapital` | instrumentId + transactionType + product (DELIVERY/INTRADAY/NORMAL) + orderType (MARKET/LIMIT/SL/SLM) | distinct (different from IIFL/XTS) |
| `indmoney` | txn_type + segment (EQUITY/DERIVATIVE) + product (CNC/MARGIN/INTRADAY) + order_type (MARKET/LIMIT) + security_id | distinct |

## Architecture: shared XTS-family base class

Four brokers (`compositedge`, `fivepaisaxts`, `ibulls`, `iifl`)
share the Symphony Fintech XTS native shape. Phase 6 introduces
`broker/_xts_family/__init__.py` with
:class:`XTSFamilyOrderTranslator` as a shared base class. Each
per-broker translator subclasses it and overrides `broker_code`
only — keeping the bit-identical-with-v1 invariant while removing
~600 lines of duplication.

When Phase 7 ships `jainamxts` and `wisdom` (also XTS family),
they will use the same base class.

## What shipped

* 12 new translator modules (`broker/<name>/translator.py`).
* 1 new shared XTS-family base (`broker/_xts_family/__init__.py`).
* 12 new parity harness wrappers
  (`tests/parity/baseline/parity_v2_<name>_india.py`) — each ~25
  lines, importing :func:`build_parity_output` from
  `parity_v2_india_common.py` (introduced in Phase 5).
* 12 new parity baseline JSON fixtures.
* `tests/contracts/test_v6_india_v2_translators.py` IMPLEMENTED_BROKERS
  list extended from 5 to 17 brokers (6 × 17 = **102 contract
  assertions** total).
* `tests/parity/run_parity.py` HARNESSES list extended:
  17 v2 broker parity harnesses (5 Phase 5 + 12 Phase 6).
* Firstock translator's `from_native_order_response` now accepts
  `order_id` as a third fallback key (the contract test's generic
  Kite-shaped sample) alongside `orderNumber` and `orderid`.
* `docs/refactor/file_classification.md` regenerated: **864 files
  classified**, no drift (was 851; +13 = 12 translators + 1 XTS base).

## Comprehensive test gate (passed)

| Step | Result |
|---|---|
| `uv run pytest tests/ -x --tb=short` | **2452 passed, 7 skipped, 2 xfailed** in 3:56 (was 2367; +85) |
| `uv run pytest -x tests/contracts/test_v4_closing_invariants.py tests/contracts/test_v5_closing_invariants.py tests/contracts/test_v6_closing_invariants.py` | **33 passed** |
| `uv run python tests/parity/run_parity.py` | **28/28** verify-mode harnesses (was 16; +12) |
| `uv run python tests/parity/run_parity.py --lane v1` | **11/11** v1-lane harnesses |
| `uv run python tests/parity/run_parity.py --lane v2` | **28/28** v2-lane harnesses |
| `uv run python scripts/audit/classify_files.py --check` | exit 0 — 864 files / no drift |
| `uv run python scripts/audit/route_fallback_scan.py` | 51 routes |
| `uv run python scripts/audit/symtoken_callers.py` | 0 PROMOTED_LEAK |
| `uv run python scripts/audit/canonical_vs_legacy_parity.py` | 13 pairs |
| `npm test -- --run` (frontend) | **160 passed across 15 files** |
| `npm run lint:literals` | exit 0 — 256 files / 0 violations |

All v4 / v5 / v6 invariants still hold. India parity bit-identical.

## Aggregate counts after Phase 6

* India v2 translators implemented: **17** of 30 (5 Phase 5 + 12
  Phase 6).
* Per-broker `parity_v2_<broker>_india` harnesses: **17**.
* Contract assertions over translators: **102** (6 × 17).
* Brokers remaining for Phase 7: **13** (jainamxts, kotak, motilal,
  mstock, nubra, paytm, pocketful, rmoney, samco, shoonya,
  tradejini, wisdom, zebu).

## Next phase

**Phase 7 — alpha batch 2** (13 India brokers). Same template; can
ship per-broker per-PR or batch through the same XTS-family base
for jainamxts and wisdom.
