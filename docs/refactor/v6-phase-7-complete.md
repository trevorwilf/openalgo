# v6 Phase 7 — Complete (alpha batch 2 — 30/30 India brokers)

* **Branch:** `refactor/v6-phase-7-india-v2-alpha-batch2`
* **Branched from:** `dev` @ `14750aa1` (HEAD: v6 Phase 6 merge)
* **Effort:** max — full prompt scope delivered.

## Goal achieved — all 30 India brokers have v2 translators

Thirteen more India brokers ship v2 translators + parity harnesses,
closing the 30-broker matrix introduced in the v5 readiness
inventory:

* **XTS-family subclasses (3 more)**: `jainamxts`, `rmoney`,
  `wisdom`. Each is ~22 lines, subclassing
  `XTSFamilyOrderTranslator` and overriding `broker_code` only.
* **Distinct shapes (10)**:

  | Broker | Native shape highlights |
  |---|---|
  | `kotak` | tk + es (nse_cm) + ts + qt + tt (B/S) + pc (CNC/NRML/MIS) + pt (MKT/L/SL/SL-M) |
  | `motilal` | exchange + symboltoken + ordertype (LIMIT/MARKET/STOPLOSS) + producttype (DELIVERY/NORMAL/VALUEPLUS) |
  | `mstock` | tradingsymbol + transaction_type + order_type (MARKET/LIMIT/STOP_LOSS/STOPLOSS_MARKET) + product (DELIVERY/CARRYFORWARD/INTRADAY) |
  | `nubra` | side (ORDER_SIDE_BUY) + order_type (ORDER_TYPE_REGULAR/STOPLOSS) + delivery_type (ORDER_DELIVERY_TYPE_*) |
  | `paytm` | txn_type (B/S) + segment (E/D) + product (C/M/I) + order_type (MARKET/LIMIT/STOP_LOSS/STOP_LOSS_MARKET) |
  | `pocketful` | client_id + transaction_type + order_type (MARKET/LIMIT/SL/SLM) + product (CNC/NRML/MIS) |
  | `samco` | tradingSymbol + transactionType + orderType (MKT/L/SL/SL-M) + productType (CNC/NRML/MIS) |
  | `shoonya` | Noren-shaped: trantype (B/S) + prctyp (LMT/MKT/SL-LMT/SL-MKT) + prd (C/M/I) |
  | `tradejini` | exchange (lowercase) + side + qty + orderType (market/limit/stoplimit/stopmarket) + product (delivery/normal/intraday) |
  | `zebu` | Noren-shaped (same as Shoonya): trantype + prctyp + prd |

## Aggregate counts after Phase 7 — v6 broker work complete

* **30 of 30 India brokers** have v2 translators (5 Phase 5 + 12
  Phase 6 + 13 Phase 7).
* **30 parity harnesses** `parity_v2_<broker>_india.{py,json}` —
  every translator is bit-identical-with-v1 by construction.
* **180 contract assertions** (6 × 30 brokers) all green.
* **30/30 brokers in v2 lane** under `run_parity.py --lane v2`.
* **`broker/_xts_family/`** shared base now powers 7 brokers
  (compositedge, fivepaisaxts, ibulls, iifl from Phase 6;
  jainamxts, rmoney, wisdom from Phase 7).

## Comprehensive test gate (passed)

| Step | Result |
|---|---|
| `uv run pytest tests/ -x --tb=short` | **2543 passed, 7 skipped, 2 xfailed** in 3:53 (was 2452; +91) |
| `uv run pytest -x tests/contracts/test_v4_closing_invariants.py tests/contracts/test_v5_closing_invariants.py tests/contracts/test_v6_closing_invariants.py` | **33 passed** |
| `uv run python tests/parity/run_parity.py` | **41/41** verify-mode harnesses (was 28; +13) |
| `uv run python tests/parity/run_parity.py --lane v1` | **11/11** v1-lane harnesses |
| `uv run python tests/parity/run_parity.py --lane v2` | **41/41** v2-lane harnesses |
| `uv run python scripts/audit/classify_files.py --check` | exit 0 — 877 files / no drift |
| `uv run python scripts/audit/route_fallback_scan.py` | 51 routes |
| `uv run python scripts/audit/symtoken_callers.py` | 0 PROMOTED_LEAK |
| `uv run python scripts/audit/canonical_vs_legacy_parity.py` | 13 pairs |
| `npm test -- --run` (frontend) | **160 passed across 15 files** |
| `npm run lint:literals` | exit 0 — 256 files / 0 violations |

## What remains for v6 Phase 8 (closing audit) and beyond

The 30-broker translator + parity work is done. Remaining v6 follow-ups:

1. **Phase 8 closing audit** (already shipped in this v6 cycle — see
   `docs/refactor/v6-phase-8-complete.md`). The closing-invariants
   gate
   (`tests/contracts/test_v6_closing_invariants.py`) was authored
   before Phases 5/6/7 shipped; it doesn't yet count translators.
   A future Phase 8-bis-update can add an invariant that asserts
   "every India broker plugin has a registered v2 translator" using
   the IMPLEMENTED_BROKERS list as the source of truth.
2. **Operator-controlled `API_V2_<BROKER>=1` flip**: each translator
   is byte-ready; flipping the env flag wires the install fn at app
   startup. Default v1 behavior is unchanged for India users.
3. **Phase 1-bis / 2-bis / 4-bis** (frontend cleanup, dispatcher
   migration, helper retirement) remain per their respective phase
   docs.

## Next phase

The v6 prompt's nine-phase plan is now substantively complete. Real
non-India broker plugins (Schwab, Webull, Alpaca, EU, UK) and per-
surface bis-phase work remain for v7.
