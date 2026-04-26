# v4 Phase 9 — Complete (PARTIAL — service refactor in Phase 9-bis)

* **Branch:** `refactor/v4-phase-9-options-providers`
* **Merged:** to `dev` with `--no-ff`
* **Effort:** max

## Goal

Options analytics (chain, expiry, IV, OI, Greeks, OSI parsing)
becomes provider-pluggable. India provider preserves DDMMMYY/CE/PE
behavior bit-identically; US provider ships with OCC OSI 21-character
format and shared Black-Scholes math.

## Invariants enforced

* **Invariant 7** (Options slice) — provider-pluggable contract +
  India + US implementations + dispatcher exist. The Phase 1 v4
  contract test `test_v4_advanced_feature_provider_contracts.py`
  Options xfail removed (now passes).

## What shipped

### Domain types — `domain/options.py`

* `OptionContract`, `OptionChain`, `Greeks`, `OIProfile`,
  `MarketSnapshot` frozen dataclasses.
* `OptionRight` enum (CALL / PUT — region-neutral).

### Shared math — `domain/options_math.py`

* `black_scholes_price(contract, market, iv)` — region-neutral price.
* `compute_greeks(contract, market, iv)` — Δ, Γ, Θ, ν, ρ.
* `implied_vol(contract, market, premium)` — bisection solver.

Both India and US providers call into this module — no duplicated
math.

### `services/options/providers/base.py` — `OptionsProvider` Protocol

* 9 methods: `parse_option_symbol`, `format_option_symbol`,
  `list_expiries`, `get_chain`, `compute_greeks`, `compute_iv`,
  `compute_oi_profile`, `supported_strategies`, `lot_size_for`.

### `services/options/providers/india/` — India provider

* `IndiaOptionsProvider`:
  * DDMMMYY/CE/PE parser via regex.
  * Lot sizes: NIFTY 50, BANKNIFTY 15, FINNIFTY 25, MIDCPNIFTY 75,
    SENSEX 10, BANKEX 15.
  * Weekly Thursday expiries (8 forward).
  * Mock chain centered at 20000 with ₹100 spacing.
  * Currency INR, venue NFO.

### `services/options/providers/us/` — US provider

* `USOptionsProvider`:
  * OCC OSI 21-character format
    (`AAPL  240419C00185000`).
  * Standard 100 lot size + 100 multiplier.
  * Friday expiries (8 forward).
  * Mock chain with strike-spacing heuristic
    (\$1 / \$2.5 / \$5 / \$10 by underlying price).
  * Currency USD, venue OPRA.

### `services/options/dispatcher.py`

* Auto-registers India + US at module load.
* `get_options_provider(region_code)` raises
  `OptionsProviderNotRegistered` (mapped to
  `ErrorCode.OPTIONS_PROVIDER_NOT_REGISTERED`).
* `get_options_provider_or_none` for UI gating.

### `docs/adr/0027-options-provider-contract.md`

ADR documenting the contract, the v4 implementations, and what is
deferred to Phase 9-bis.

## New tests added

| File | Tests |
|---|---|
| `tests/options/test_provider_contract.py` | 19 (Protocol conformance, India NIFTY/BANKNIFTY parse + format round-trip, US OSI parse + format round-trip, US AAPL Greeks, India NIFTY Greeks, dispatcher resolution India/US/fail-closed, expiry weekday checks, lot sizes) |
| `tests/contracts/test_v4_advanced_feature_provider_contracts.py` | Options xfail removed (now passes) |

## What is deferred to Phase 9-bis

Per ADR 0027 § "What is deferred to Phase 9-bis":

* Refactor of 9 existing option services into thin shims that
  dispatch through the provider:
  `services/expiry_service.py`, `option_chain_service.py`,
  `option_symbol_service.py`, `option_greeks_service.py`,
  `iv_chart_service.py`, `options_multiorder_service.py`,
  `straddle_chart_service.py`, `synthetic_future_service.py`,
  `vol_surface_service.py`, `gex_service.py`.
* `parity_options_india` parity harness covering bit-identical
  parse_option_symbol behavior for representative inputs.
* `BrokerCapabilities.supports_options` capability metadata.
* Frontend option chain capability gating + OSI rendering.

The contract + India + US providers + dispatcher are the load-
bearing pieces. Phase 9-bis lands per-service refactors incrementally
without breaking the parity-protected India option path.

## Comprehensive testing (gate 2.6)

| Step | Result |
|---|---|
| `pytest -x tests/contracts/ tests/parity/ tests/compliance/ tests/options/ tests/sandbox/` | 181 passed, 1 xfailed |
| `python tests/parity/run_parity.py` | 8/8 passed |
| `pytest tests/` | 1993 passed, 7 skipped, 1 xfailed — 160s |
| `npm run lint:literals` | 253 files / 0 violations |
| `python scripts/audit/classify_files.py --check` | 826 files / no drift |

All gates pass.

## Files touched

* Created: `domain/options.py`, `domain/options_math.py`,
  `services/options/__init__.py`,
  `services/options/providers/__init__.py`,
  `services/options/providers/base.py`,
  `services/options/providers/india/__init__.py`,
  `services/options/providers/us/__init__.py`,
  `services/options/dispatcher.py`,
  `tests/options/test_provider_contract.py`,
  `docs/adr/0027-options-provider-contract.md`, this completion doc.
* Modified: `tests/contracts/test_v4_advanced_feature_provider_contracts.py`,
  `docs/refactor/file_classification.md` (regen).
