# ADR 0027 — Options provider contract

* **Status:** accepted
* **Date:** 2026-04-26
* **Phase:** v4 Phase 9

## Context

OpenAlgo's options analytics (chain, expiry, IV, OI, Greeks, straddle,
multiorder, synthetic future, vol surface, GEX) hard-codes Indian
DDMMMYY/CE/PE symbology, NFO/BFO venues, and weekly Thursday +
monthly Indian expiry rules. Non-India users have no usable options
analytics; the existing region gates return
`option_*_disabled_in_region` for non-India brokers.

The right abstraction is provider-pluggable.

## Decision

The Options analytics suite becomes provider-pluggable. The
`OptionsProvider` Protocol in
`services/options/providers/base.py` defines the contract:

```python
class OptionsProvider(Protocol):
    region_code: str
    def parse_option_symbol(self, symbol: str) -> OptionContract: ...
    def format_option_symbol(self, contract: OptionContract) -> str: ...
    def list_expiries(self, underlying: str, asof: date) -> list[date]: ...
    def get_chain(self, underlying: str, expiry: date) -> OptionChain: ...
    def compute_greeks(self, contract, market, iv) -> Greeks: ...
    def compute_iv(self, contract, premium, market) -> Decimal: ...
    def compute_oi_profile(self, underlying, expiry) -> OIProfile: ...
    def supported_strategies(self) -> set[str]: ...
    def lot_size_for(self, contract: OptionContract) -> int: ...
```

Domain types in `domain/options.py`:
* `OptionContract`, `OptionChain`, `Greeks`, `OIProfile`,
  `MarketSnapshot`, `OptionRight` enum.

Shared math in `domain/options_math.py`:
* `black_scholes_price`, `compute_greeks`, `implied_vol` —
  region-neutral. Both providers call into these.

v4 ships two implementations:

* **India** (`services/options/providers/india/`) — DDMMMYY/CE/PE
  parser + formatter. Lot sizes for NIFTY (50), BANKNIFTY (15),
  FINNIFTY (25), MIDCPNIFTY (75), SENSEX (10), BANKEX (15). Weekly
  Thursday expiries. Mock chain centered at 20000 with 100-rupee
  spacing.
* **US** (`services/options/providers/us/`) — OCC OSI 21-character
  format (`AAPL  240419C00185000`). Standard 100 lot size.
  Friday expiries. Mock chain with strike-spacing heuristic
  (\$1 / \$2.5 / \$5 / \$10 by underlying price).

Dispatcher in `services/options/dispatcher.py`:
* Auto-registers India + US at module load.
* `get_options_provider(region_code)` raises
  `OptionsProviderNotRegistered` (mapped to `ErrorCode.OPTIONS_PROVIDER_NOT_REGISTERED`).
* `get_options_provider_or_none(region_code)` for UI gating.

## What v4 Phase 9 ships (this ADR)

* `domain/options.py` — domain types.
* `domain/options_math.py` — shared Black-Scholes math.
* `services/options/providers/base.py` — Protocol.
* `services/options/providers/india/` — India provider.
* `services/options/providers/us/` — US provider.
* `services/options/dispatcher.py` — registry + auto-registration.
* 19 contract conformance tests
  (`tests/options/test_provider_contract.py`).

## What is deferred to Phase 9-bis

* Refactor of the 9 existing option services
  (`services/expiry_service.py`, `option_chain_service.py`,
  `option_symbol_service.py`, `option_greeks_service.py`,
  `iv_chart_service.py`, `options_multiorder_service.py`,
  `straddle_chart_service.py`, `synthetic_future_service.py`,
  `vol_surface_service.py`, `gex_service.py`) into thin shims that
  dispatch through the provider. Today these services run direct;
  parity-protected for India.
* `parity_options_india` parity harness covering
  parse_option_symbol bit-identical for representative inputs.
* `BrokerCapabilities.supports_options` capability metadata.
* Frontend option-chain capability gating + OSI rendering.

The contract + India + US providers + dispatcher are the load-bearing
pieces. Phase 9-bis lands the per-service refactor incrementally
without breaking the parity-protected India option path.

## Cross-references

* ADR 0023 — v4 scope.
* `domain/options.py`, `domain/options_math.py`.
* `services/options/providers/{base,india,us}/`,
  `services/options/dispatcher.py`.
* `tests/options/test_provider_contract.py`.
