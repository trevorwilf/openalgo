# Phase 6 — Per-broker India translator parity status

STATUS: ALL_GREEN

Phase 6 (T-25) verifies that all 30 India broker translators produce
bit-identical output on both `--lane v1` and `--lane v2`. This file
is the gate Phase 9 (`refactor/market-agnostic-phase-9-v1-sunset`)
reads — its presence with `STATUS: ALL_GREEN` is the precondition
for the v1-lane physical move and sunset machinery.

Last verified: **2026-05-01**.

## Verification command

```bash
# India parity, both lanes
uv run python tests/parity/run_parity.py --lane v1
uv run python tests/parity/run_parity.py --lane v2

# Plus every API_V2_<BROKER>=1 flipped on for the v2 lane
env API_V2_ZERODHA=1 API_V2_ANGEL=1 API_V2_DHAN=1 API_V2_UPSTOX=1 \
    API_V2_FYERS=1 API_V2_ALICEBLUE=1 API_V2_COMPOSITEDGE=1 \
    API_V2_DEFINEDGE=1 API_V2_FIRSTOCK=1 API_V2_FIVEPAISA=1 \
    API_V2_FIVEPAISAXTS=1 API_V2_FLATTRADE=1 API_V2_GROWW=1 \
    API_V2_IBULLS=1 API_V2_IIFL=1 API_V2_IIFLCAPITAL=1 \
    API_V2_INDMONEY=1 API_V2_JAINAMXTS=1 API_V2_KOTAK=1 \
    API_V2_MOTILAL=1 API_V2_MSTOCK=1 API_V2_NUBRA=1 \
    API_V2_PAYTM=1 API_V2_POCKETFUL=1 API_V2_RMONEY=1 \
    API_V2_SAMCO=1 API_V2_SHOONYA=1 API_V2_TRADEJINI=1 \
    API_V2_WISDOM=1 API_V2_ZEBU=1 \
    uv run python tests/parity/run_parity.py --lane v2
```

All three commands return `41/41 passed, 0 failed` (or `11/11` for
the lane=v1 filter — only the lane-shared harnesses are eligible
under v1; per-broker `parity_v2_*_india` harnesses are v2-only).

## Per-broker status

The 30 India brokers from
`services/india_translator_bootstrap.py:27-58`. All harnesses are at
`tests/parity/baseline/parity_v2_<broker>_india.py` and each carries a
checked-in `.json` fixture that the translator output must match
byte-for-byte. v6 Phase 5 ("popularity order"), Phase 6 (alpha batch
1), and Phase 7 (alpha batch 2) shipped these harnesses; Phase 6 of
the market-agnostic refactor (this file) gates the parity verification.

### Top 5 (v6 Phase 5 — popularity order)

| Broker | v1 | v2 | API_V2_<CODE>=1 v2 | MPP capability |
|--------|----|----|--------------------|----------------|
| zerodha | ✅ | ✅ | ✅ | — |
| angel | ✅ | ✅ | ✅ | — |
| dhan | ✅ | ✅ | ✅ | — |
| upstox | ✅ | ✅ | ✅ | — |
| fyers | ✅ | ✅ | ✅ | — |

### Alpha batch 1 (v6 Phase 6)

| Broker | v1 | v2 | API_V2_<CODE>=1 v2 | MPP capability |
|--------|----|----|--------------------|----------------|
| aliceblue | ✅ | ✅ | ✅ | — |
| compositedge | ✅ | ✅ | ✅ | — |
| definedge | ✅ | ✅ | ✅ | — |
| firstock | ✅ | ✅ | ✅ | — |
| fivepaisa | ✅ | ✅ | ✅ | — |
| fivepaisaxts | ✅ | ✅ | ✅ | — |
| flattrade | ✅ | ✅ | ✅ | MPP-MARKET |
| groww | ✅ | ✅ | ✅ | — |
| ibulls | ✅ | ✅ | ✅ | MPP-MARKET |
| iifl | ✅ | ✅ | ✅ | — |
| iiflcapital | ✅ | ✅ | ✅ | — |
| indmoney | ✅ | ✅ | ✅ | MPP-MARKET |

### Alpha batch 2 (v6 Phase 7)

| Broker | v1 | v2 | API_V2_<CODE>=1 v2 | MPP capability |
|--------|----|----|--------------------|----------------|
| jainamxts | ✅ | ✅ | ✅ | — |
| kotak | ✅ | ✅ | ✅ | MPP-MARKET |
| motilal | ✅ | ✅ | ✅ | MPP-MARKET + MPP-SLM |
| mstock | ✅ | ✅ | ✅ | — |
| nubra | ✅ | ✅ | ✅ | — |
| paytm | ✅ | ✅ | ✅ | — |
| pocketful | ✅ | ✅ | ✅ | MPP-MARKET |
| rmoney | ✅ | ✅ | ✅ | — |
| samco | ✅ | ✅ | ✅ | MPP-MARKET + MPP-SLM |
| shoonya | ✅ | ✅ | ✅ | MPP-MARKET |
| tradejini | ✅ | ✅ | ✅ | — |
| wisdom | ✅ | ✅ | ✅ | — |
| zebu | ✅ | ✅ | ✅ | MPP-MARKET |

## What Phase 6 proves

* Each broker has a registered v2 `BrokerOrderTranslator` at
  `broker/<code>/translator.py`.
* `services/india_translator_bootstrap.py` lists all 30; on import,
  the bootstrap reads `API_V2_<BROKER>=1` env flags and registers
  the corresponding translator in the registry.
* For every order shape covered by the parity fixture (every
  combination of order_type / TIF / product / exchange the broker
  supports), the v2 translator's wire payload is bit-identical to
  the v1 `transform_data` output — except for documented intentional
  normalizations (e.g. `trigger_price="0"` vs `"0.0"`, both lanes
  normalized to `"0"`).
* MPP-eligible brokers (Phase 5 T-22) continue to apply MARKET → LIMIT
  / SL-M → SL conversion at the dispatcher level. Their parity
  harnesses include the MPP path; the result is bit-identical with
  the v1 lane.

## Operator default

Per ADR 0005, every `API_V2_<BROKER>` flag defaults to **OFF**. Each
broker's flip-over is operator-controlled. This file's `ALL_GREEN`
state means the framework is **ready** for any operator to flip
their broker's flag; it does NOT change the default.

## How to re-verify

If the parity status drifts, re-run the verification command at the
top of this file. Any broker that fails should be reverted (per the
prompt's parity rule: revert, do not fix forward) and investigated.

If a translator legitimately needs to change (e.g. broker API change),
update both the v1 `transform_data` AND the v2 translator AND the
parity fixture in one commit. The fixture is the contract; both lanes
must agree on its content.
