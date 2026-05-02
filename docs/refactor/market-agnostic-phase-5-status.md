# Phase 5 — Generalize broker wire quirks

Status: **shipped**.

This is Phase 5 of the market-agnostic refactor. Replaces hardcoded
broker-name lists in promoted code with capability flags consulted
per-broker.

## What landed

### T-22 — MPP slabs are now capability-driven

Pre-Phase-5, `services/promoted_mpp_service.py` carried two hardcoded
broker frozensets:

* `BROKERS_REQUIRING_MPP_MARKET = {flattrade, motilal, pocketful,
  samco, kotak, ibulls, indmoney, shoonya, zebu}`
* `BROKERS_REQUIRING_MPP_SLM = {motilal, samco}`

Post-Phase-5, each of those broker `plugin.json` files declares:

* `requires_market_price_protection: true` (all 9 brokers)
* `requires_slm_to_sl_conversion: true` (motilal, samco)

The MPP helpers (`requires_mpp_market`, `requires_mpp_slm`) consult
`BrokerCapabilities` (Phase 0 T-02 schema field) instead of the
frozenset. The historical inventory remains as
`LEGACY_INDIA_MPP_MARKET_BROKERS` / `LEGACY_INDIA_MPP_SLM_BROKERS`
for documentation but is no longer the source of truth.

A new broker that needs MPP just declares the capability flag in its
`plugin.json`; no Python edit required.

### T-21 — WS topic decoding is now capability-driven

Pre-Phase-5, `websocket_proxy/server.py:1521` hardcoded the
`NSE_INDEX` / `BSE_INDEX` two-segment prefix detection:

```python
if len(remaining) >= 2 and remaining[0] in ("NSE", "BSE") and remaining[1] == "INDEX":
```

Post-Phase-5, the router queries the loaded region plugins for any
`venue_code` containing an underscore and treats those as
multi-segment venues. The new helpers:

* `_multi_segment_venue_codes()` — loads from
  `utils.region_loader.list_market_regions()`, returns codes sorted
  by length descending so longest-prefix-match wins.
* `_split_topic_venue_and_symbol(remaining)` — generic
  ("EXCHANGE_SYMBOL split") replacing the hardcoded India branch.

India venues `NSE_INDEX` / `BSE_INDEX` are declared in
`market_regions/india/plugin.json` (added in Phase 3); they're
discovered automatically. New regions adding their own multi-segment
venues need only declare them in `plugin.json`.

## Tests added

`tests/websocket/test_v3_phase5_topic_format.py` — 10 tests:

* `_multi_segment_venue_codes()` discovers `NSE_INDEX` and `BSE_INDEX`
  from the India region plugin.
* Cache returns codes sorted longest-first.
* Round-trip parsing of common topics: NSE/RELIANCE,
  NSE_INDEX/NIFTY, BSE_INDEX/SENSEX, CRYPTO/SOL_INR (preserves the
  underscore in symbol).
* Source scan confirms the pre-Phase-5 hardcoded `NSE`/`BSE`/`INDEX`
  branch is removed.

`tests/services/test_v6_promoted_mpp_service.py` — already covered
the 9 + 2 broker behavior; updated to import the renamed inventory
frozensets and aliased them so the existing parametrized tests
continue to validate every broker round-trip via the now
capability-driven `requires_mpp_market` / `requires_mpp_slm` helpers.

## Tests adjusted

* `tests/contracts/test_v6_closing_invariants.py::test_v6_invariant_v6_8_promoted_mpp_service_present`
  — references the renamed inventory frozensets.
* `tests/services/test_history_service_resolver_parity.py` and
  `test_quotes_service_resolver_parity.py` — patch
  `database.token_db.get_token` (the source) instead of the lazy
  service-module attribute, and force India region for the validator.
  This was a Phase 3 carry-over fix that surfaced when the broader
  test sweep ran post-T-22.

## Verification

* `uv run python tests/parity/run_parity.py` — 41/41 parity green.
* `uv run pytest tests/contracts/ tests/services/ tests/websocket/test_v3_phase5_topic_format.py tests/region_loader/ tests/multi_region/ tests/sandbox/ tests/sessions/ tests/audit/ -q` — 803 tests pass.
* `uv run python scripts/audit/classify_files.py --check` — no
  drift.
