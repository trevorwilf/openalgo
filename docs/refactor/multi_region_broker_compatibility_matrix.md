# Multi-region broker compatibility matrix

Phase 8 T-29. Restructures the historical
`audit/BROKER_API_COMPATIBILITY.md` (29 India brokers × 38 endpoints)
into a multi-region matrix. Adds columns for
the mock-Schwab and mock-Webull plugins as **architecture-readiness**
entries (clearly labeled — they prove the contract surface, NOT
API compatibility).

Legend:

* ✅ — supported (plugin implements the endpoint and parity-tests it)
* ❌ — not supported (no current implementation; would need broker-API support)
* 🟡 — partial / with-caveats (see notes)
* N/A — not applicable to this region (e.g. Indian-only NRML product
  on a US broker)
* 🧪 — mock plugin: contract-surface ready, NOT API-compatible with
  the named real broker

## India brokers (30)

All India brokers cover NSE / BSE / NFO / BFO / CDS / MCX
(plus indices and some BCD / NCDEX). Specific endpoint coverage is
tracked in `audit/BROKER_API_COMPATIBILITY.md` — that file remains
the authoritative per-endpoint matrix for India brokers. Repeated
here in summary form by region capability:

| Broker | India v1 | India v2 translator | India v2 parity |
|--------|----------|---------------------|-----------------|
| zerodha | ✅ | ✅ | 🟡 (Phase 6 not run) |
| angel | ✅ | ✅ | 🟡 |
| dhan | ✅ | ✅ | 🟡 |
| upstox | ✅ | ✅ | 🟡 |
| fyers | ✅ | ✅ | 🟡 |
| aliceblue | ✅ | ✅ | 🟡 |
| compositedge | ✅ | ✅ | 🟡 |
| definedge | ✅ | ✅ | 🟡 |
| firstock | ✅ | ✅ | 🟡 |
| fivepaisa | ✅ | ✅ | 🟡 |
| fivepaisaxts | ✅ | ✅ | 🟡 |
| flattrade | ✅ | ✅ | 🟡 (MPP-MARKET enabled per Phase 5 T-22) |
| groww | ✅ | ✅ | 🟡 |
| ibulls | ✅ | ✅ | 🟡 (MPP-MARKET) |
| iifl | ✅ | ✅ | 🟡 |
| iiflcapital | ✅ | ✅ | 🟡 |
| indmoney | ✅ | ✅ | 🟡 (MPP-MARKET) |
| jainamxts | ✅ | ✅ | 🟡 |
| kotak | ✅ | ✅ | 🟡 (MPP-MARKET) |
| motilal | ✅ | ✅ | 🟡 (MPP-MARKET + MPP-SLM) |
| mstock | ✅ | ✅ | 🟡 |
| nubra | ✅ | ✅ | 🟡 |
| paytm | ✅ | ✅ | 🟡 |
| pocketful | ✅ | ✅ | 🟡 (MPP-MARKET) |
| rmoney | ✅ | ✅ | 🟡 |
| samco | ✅ | ✅ | 🟡 (MPP-MARKET + MPP-SLM) |
| shoonya | ✅ | ✅ | 🟡 (MPP-MARKET) |
| tradejini | ✅ | ✅ | 🟡 |
| wisdom | ✅ | ✅ | 🟡 |
| zebu | ✅ | ✅ | 🟡 (MPP-MARKET) |

The "Phase 6 not run" caveat is global — the 30-broker per-broker v1+v2
parity loop has not been executed in this engagement. Each broker has
a parity harness (`tests/parity/baseline/parity_v2_<code>_india.py`)
and `services/india_translator_bootstrap.py` lists all 30. Phase 6
exists to verify each row goes from 🟡 → ✅ via per-broker fixture
runs.

## Crypto brokers

| Broker | Crypto venues | India v1 | Notes |
|--------|---------------|----------|-------|
| deltaexchange | ✅ (CRYPTO + USDT perps) | ✅ | Static-IP gating per SEBI April 2026 mandate |

## Non-India regions — current state

| Broker | India | US | EU | UK | Crypto | Notes |
|--------|-------|----|----|----|--------|-------|
| _mock_schwab_like 🧪 | N/A | 🟡 (mock) | N/A | N/A | N/A | Architecture-readiness only — exercises the v2 promoted contract surface for a US-style broker. NOT a real Schwab integration. |
| _mock_webull_like 🧪 | N/A | 🟡 (mock) | N/A | N/A | 🟡 (mock) | Architecture-readiness only — exercises the v2 + streaming + crypto contract surfaces. NOT a real Webull integration. |
| (real US broker) | — | ❌ (not in repo) | — | — | — | Future work — see future-broker-onboarding-checklist.md |
| (real EU broker) | — | — | ❌ | — | — | Future work |
| (real UK broker) | — | — | — | ❌ | — | Future work |

## Why "🧪" is not "✅" for the mock plugins

The Phase 6 mocks (`broker/_mock_schwab_like/`, `broker/_mock_webull_like/`)
satisfy the OpenAlgo contract surface: auth, order placement,
quote fetch, bar fetch, instrument sync, streaming, account context,
combo orders, MPP, capability flags, plugin schema. They are the
canonical examples of "how a non-India broker plugin is structured."

They do NOT speak the real Schwab or Webull HTTP/WS protocols. Their
fixtures are deterministic in-memory. The underscore-prefix in the
directory name is intentional — the broker loader skips them in
production unless an operator explicitly opts in.

A real Schwab or Webull plugin would copy these mocks' file
structure, replace the in-memory fixtures with real HTTP/WS
clients to the broker's documented endpoints, supply credentials
through the standard auth_db interface, and add a parity harness
under `tests/parity/baseline/parity_v2_<code>_us.py`. Real plugins
require authenticated API documentation, credentials, UAT, and
human approval — none of which sit in this repo.

## Endpoints covered

OpenAlgo's stable surface — the contract every plugin programs
against:

* `place_order`, `modify_order`, `cancel_order`
* `place_smart_order` (auto-detects long/short with position sizing)
* `place_basket_order`, `place_split_order`, `cancel_all`
* `quote`, `quotes`, `depth`, `history`, `intervals`
* `funds`, `holdings`, `positions`, `position_book`
* `orderbook`, `tradebook`
* `analyzer` (sandbox / paper-trading)
* `option_chain`, `option_symbol`, `place_options_order`,
  `place_options_multiorder`
* `expiry`, `iv_chart`, `gex`, `option_greeks`,
  `synthetic_future`, `straddle_chart`, `vol_surface`,
  `flow_executor`
* `python_strategy`, `chartink`, `flow_strategy`
* `ticker`, `subscribe_ltp`, `subscribe_quote`, `subscribe_depth`
* `master_contract` (refresh)

Per-region availability of each endpoint depends on the active
broker's capabilities (per ADR 0005); the v1 lane locks
India-shaped endpoints (option_chain, expiry, etc.) behind
`is_india_region_active()` (Phase 4 v3 — ADR 0020).

## Status of the historical India compatibility audit

`audit/BROKER_API_COMPATIBILITY.md` — covers 29 India brokers × 38
endpoints in detail. **That document is still the authoritative
per-endpoint matrix for India brokers.** This file is the
multi-region structure that Phase 8 T-29 introduces; the merge of
the two (folding the India per-endpoint detail into a multi-region
single matrix) is a future doc-engagement task.
