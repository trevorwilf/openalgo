# ADR 0026 — Sandbox provider contract

* **Status:** accepted
* **Date:** 2026-04-26
* **Phase:** v4 Phase 8

## Context

OpenAlgo's Sandbox (paper trading / order simulation) hard-codes
Indian semantics today: T+1 settlement, MIS / CNC / NRML products,
₹10,00,000 initial funds, 15:15 IST square-off, no partial fills.
Non-India users have no usable sandbox; the existing region gate
returns `503 sandbox_region_unsupported` for non-India brokers.

Two expert reviews in scope for v4 identified Sandbox as a feature
that other regions need in their own form. The right abstraction is
provider-pluggable.

## Decision

The Sandbox feature becomes provider-pluggable. The
:class:`SandboxProvider` Protocol in
`services/sandbox/providers/base.py` defines the contract:

```python
class SandboxProvider(Protocol):
    region_code: str
    def settlement_date_for_order(self, order, trade_date) -> date: ...
    def squareoff_time_for_product(self, product, venue_code, on_date) -> datetime | None: ...
    def simulate_fill(self, order, market_data) -> list[Fill]: ...
    def supported_products(self) -> set[str]: ...
    def supported_order_types(self) -> set[str]: ...
    def base_currency(self) -> str: ...
    def initial_funds(self) -> Decimal: ...
    def partial_fills_supported(self) -> bool: ...
    def position_lifecycle_rules(self) -> ProviderRules: ...
```

v4 ships two implementations:

* **India** (`services/sandbox/providers/india/`) — preserves the
  current Sandbox semantics. T+1 / MIS-CNC-NRML / ₹10L / 15:15 IST
  square-off / no partial fills.
* **US** (`services/sandbox/providers/us/`) — mock data. T+2 equity,
  T+1 option, USD $100k, partial fills (low-liquidity heuristic),
  XNYS 16:00 ET day-trade close.

The dispatcher in `services/sandbox/dispatcher.py`:

* Auto-registers India + US providers at module load.
* `get_sandbox_provider(region_code)` raises
  `SandboxProviderNotRegistered` (mapped to `503
  sandbox_provider_not_registered`) for unknown regions.
* `get_sandbox_provider_or_none(region_code)` for callers that want
  to render an "unavailable" UI state.
* `clear_sandbox_registry_for_tests()` for hermetic tests.

## What v4 Phase 8 ships (this ADR)

* Contract + India + US provider implementations.
* Dispatcher with auto-registration + fail-closed.
* 13 contract conformance tests (`tests/sandbox/test_provider_contract.py`).

## What is deferred to Phase 8-bis

* Wiring `blueprints/sandbox.py` (1178 lines) to call the dispatcher
  rather than hardcoding the India path. The blueprint continues to
  drive India sandbox behavior directly today; parity-protected.
* Wiring `database/sandbox_db.py` schema additions (region_code,
  currency columns) and the additive migration. Today the sandbox
  database is implicitly India-only.
* Sandbox UI region-aware dispatch (frontend).
* Capability metadata `BrokerCapabilities.supports_sandbox`.
* Parity harness `parity_sandbox_india` (the existing sandbox
  blueprint paths are parity-protected by their direct test surfaces;
  a dedicated harness lands with the dispatcher wiring).

The contract + providers + dispatcher are the load-bearing pieces.
Phase 8-bis can land the wiring incrementally without breaking
parity.

## Consequences

* Real US broker plugins (future Schwab / Webull / Alpaca with full
  sandbox) drop in by registering a US-region provider override.
* Adding EU / UK sandbox providers is a single-file addition.
* India sandbox is bit-identical (parity-protected).
* The `is_india_region_active()` gate in the existing sandbox path
  remains until Phase 8-bis swaps the blueprint to dispatcher dispatch.

## Cross-references

* ADR 0023 — v4 scope.
* `services/sandbox/providers/base.py` — Protocol.
* `services/sandbox/dispatcher.py` — registry + lookup.
* `tests/sandbox/test_provider_contract.py` — conformance.
