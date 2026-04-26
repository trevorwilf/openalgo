# v4 Phase 5 — Complete

* **Branch:** `refactor/v4-phase-5-v2-fail-closed`
* **Merged:** to `dev` with `--no-ff`
* **Effort:** high

## Goal

Ensure non-India brokers cannot fall back to legacy quote/history/
position/balance services under any condition. Wire promoted v2
positions/balances through new adapter Protocols.

## Gaps closed (from `v3_baseline_audit.md`)

* **Gap 1** — v2 quotes legacy fallback. Re-verified: ADR 0018
  guard is in place; new contract test
  `test_promoted_quote_bar_uses_canonical_resolver.py` enforces no
  module-level legacy resolver imports in `restx_api/v2/quotes.py`.
* **Gap 2** — v2 bars legacy fallback. Same — re-verified +
  contract test added.
* **Gap 10** — promoted v2 quote/bar paths use canonical resolver.
  New contract test enforces it.

## What shipped

### `domain/broker_market_data.py` — new Protocols + dataclasses

* `NormalizedPosition` — broker-agnostic open position snapshot
  (`instrument_id`, `venue_code`, `canonical_symbol`, `quantity`,
  `average_price`, `market_value`, `realized_pnl`, `unrealized_pnl`,
  `currency`).
* `NormalizedBalance` — `cash`, `equity`, `buying_power`,
  `margin_used`, `currency`.
* `BrokerPositionAdapter` (Protocol) — `get_positions(account_ctx)
  -> list[NormalizedPosition]`.
* `BrokerBalanceAdapter` (Protocol) — `get_balance(account_ctx) ->
  NormalizedBalance`.

### `services/broker_market_data_registry.py` — extended

* `register_broker_position_adapter`,
  `register_broker_balance_adapter`,
  `get_broker_position_adapter`, `get_broker_balance_adapter`.
* `clear_market_data_registries_for_tests` extended to clear all
  four registries.

### `restx_api/v2/accounts.py` — fail-closed dispatch matrix

For both `/api/v2/positions` and `/api/v2/balances`:

1. Adapter registered → use it; return normalized payload.
2. Else if non-India broker → return HTTP 503
   `promoted_capability_unavailable` with sub-code
   `position_adapter_not_registered` /
   `balance_adapter_not_registered`. Bumps
   `broker_adapter_missing_total{feature=...}` counter.
3. Else (India broker) → proxy to legacy
   `services.positionbook_service.get_positionbook_with_auth` /
   `services.funds_service.get_funds_with_auth`.

  Bonus fix: the v3-era v2 skeleton imported a non-existent
  `services.positions_service` (always returned 501 for India). v4
  Phase 5 wires the correct `positionbook_service` so India
  positions actually work through v2.

### Mock plugin adapter scaffolding

* `broker/_mock_schwab_like/api/position_balance_adapters.py` —
  `MockSchwabLikePositionAdapter` (AAPL, MSFT positions),
  `MockSchwabLikeBalanceAdapter` ($100k cash, $103.9k equity),
  `install_mock_schwab_like_account_adapters()`.
* `broker/_mock_webull_like/api/position_balance_adapters.py` —
  `MockWebullLikePositionAdapter`, `MockWebullLikeBalanceAdapter`,
  `install_mock_webull_like_account_adapters()`.

## New tests added

| File | Tests |
|---|---|
| `tests/api_v2/test_positions_failclosed_non_india.py` | 3 (no adapter → 503; with adapter → normalized; India → legacy proxy) |
| `tests/api_v2/test_balances_failclosed_non_india.py` | 3 (same shape) |
| `tests/contracts/test_promoted_quote_bar_uses_canonical_resolver.py` | 2 (no legacy resolver imports; canonical resolver referenced) |
| **Total new** | **8** |

## Comprehensive testing (gate 2.6)

| Step | Result |
|---|---|
| `pytest -x tests/contracts/ tests/parity/ tests/compliance/` | passed |
| `python tests/parity/run_parity.py` | 7/7 passed |
| `pytest tests/` | 1914 passed, 7 skipped, 3 xfailed — 159s |
| `npm run lint:literals` | 253 files / 0 violations |
| `python scripts/audit/classify_files.py --check` | 816 files / no drift |
| `python scripts/audit/route_fallback_scan.py` | 51 routes |
| `python scripts/audit/symtoken_callers.py` | 0 PROMOTED_LEAK rows |
| `python scripts/audit/canonical_vs_legacy_parity.py` | 13 pairs |

All gates pass.

## Files touched

* Modified: `domain/broker_market_data.py`,
  `services/broker_market_data_registry.py`,
  `restx_api/v2/accounts.py`,
  `docs/refactor/file_classification.md` (regen),
  `docs/refactor/route_fallback_inventory.md` (regen).
* Created: `broker/_mock_schwab_like/api/position_balance_adapters.py`,
  `broker/_mock_webull_like/api/position_balance_adapters.py`,
  3 new test files, this completion doc.

## Deferred follow-ups

* Fully-validated v2 error taxonomy module (`restx_api/v2/_errors.py`)
  — current state: `restx_api/v2/_auth.py:error()` plus
  `domain.errors.ErrorCode` cover the codes used by the v2 routes
  today. A dedicated `_errors.py` would centralize the (status_code,
  code, sub_code) mapping; left for Phase 11 alongside the e2e
  expansion that exercises every code.
* Mock plugin auto-registration on app startup — currently each
  test/integration has to call `install_mock_*_account_adapters()`
  explicitly. Phase 11 wires this into the mock plugins'
  `__init__.py` so loading the plugin auto-registers all adapters.
