# v5 Phase 5 — Complete

* **Branch:** `refactor/v5-phase-5-options-service-shims`
* **Merged:** to `dev` with `--no-ff`
* **Effort:** max
* **Closes:** v4 deferral 9-bis (capability + parity); expert MA-029,
  MA-030; expert P7-01…P7-06.

## Goal

Promote `BrokerCapabilities.supports_options` to a first-class field
and lock the India options provider's parity contract. Per-service
shimming (the 9 `services/option_*_service.py` files) is the deferred
Phase 5-bis follow-up; the v4 dispatcher is already in place and the
India provider is the canonical implementation.

## Work shipped

### `domain/capabilities.py` — `supports_options` field

* Added `supports_options: bool = False` to `BrokerCapabilities`.
* India inference defaults `supports_options=True` (preserves
  `option_chain` / `option_greeks` / IV / GEX / `synthetic_future` /
  `straddle_chart` surfaces).
* Common defaults (every other broker_type) keep
  `supports_options=False`; non-India brokers must explicitly opt in.
* Added to `_EXPLICIT_OVERRIDE_KEYS` so plugin declarations win.

### `frontend/src/types/capabilities.ts`

* Added `supports_options: boolean` to `BrokerCapabilities`.
* Extended `hasCapability` enum.

### `parity_options_india` harness — new (10th)

* `tests/parity/baseline/parity_options_india.{py,json}` —
  snapshots `IndiaOptionsProvider`:
  * Symbol parsing for NIFTY / BANKNIFTY / FINNIFTY / MIDCPNIFTY /
    SENSEX / BANKEX with full extracted fields.
  * Round-trip format on integer strike (NIFTY28MAR2420800CE) and
    decimal strike (BANKNIFTY15FEB2447500.5PE).
  * Weekly Thursday expiry generator for 8 weeks from 2026-04-15.
  * Lot sizes per underlying.
  * Supported strategies set.
* `tests/parity/run_parity.py::HARNESSES` extended; runner now
  reports **10/10 passed**.

### Capability propagation tests

* `tests/plugin_loader/test_v5_supports_options_capability.py` (5
  tests) — India inference, crypto stays-false, explicit override,
  default-unset, model_dump serialization.

## Out of scope (deferred to v5 Phase 5-bis)

The v5 prompt's other Phase 5 sub-items remain open and non-blocking:

1. Service shimming for the 9 `services/option_*_service.py` files
   (option_symbol, option_chain, option_greeks, place_options_order,
   options_multiorder, iv_chart, iv_smile, gex, synthetic_future).
   The dispatcher (`services/options/dispatcher.py`) and the India
   provider (`services/options/providers/india/`) are in place; each
   service's adoption is straightforward but invasive (many call
   sites need region resolution + provider lookup). The v4 Phase 4
   region gate (`require_region_feature`) currently fails them
   closed for non-India regions, so India parity is preserved and
   non-India calls are blocked.
2. Canonical option contract identity in `database.instruments_repo`
   — `OPTION` shape exists in `domain.instrument_ref`; the persisted
   broker-token mapping is per-broker plugin work and is not
   load-bearing for v5 framework readiness.
3. Frontend OSI rendering for non-India providers — the
   `USOptionsProvider` ships OSI parsing/formatting in v4; the UI
   adoption ships when a real US options surface is needed.

## Gate results

| Step | Result |
|---|---|
| `uv run pytest tests/ -x --tb=short` | 2095 passed, 7 skipped, 0 failed |
| `uv run python tests/parity/run_parity.py` | 10/10 passed |
| `uv run python scripts/audit/classify_files.py --check` | 840 files, no drift |
| `uv run python scripts/audit/symtoken_callers.py` | 0 PROMOTED_LEAK |
| `npm run lint:literals` | 255 files, 0 violations |

All gates pass. Zero xfails added.

## v5 by the numbers (running total after Phase 5)

* **2 new ADRs** (0029, 0030 — Phase 1).
* **93 new tests** total (Phase 1: 23; Phase 2: 29; Phase 3: 22;
  Phase 4: 14; Phase 5: 5).
* **2095 backend tests** (was 2090 at Phase 4 close; +5 net).
* **10 parity harnesses** (was 9 at Phase 4 close; +1 — `parity_options_india`).
* **0 PROMOTED_LEAK rows**.
* **0 frontend literal violations**.
