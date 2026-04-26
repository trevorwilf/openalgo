# ADR 0028 — Screener provider contract

* **Status:** accepted
* **Date:** 2026-04-26
* **Phase:** v4 Phase 10

## Context

OpenAlgo's screener integration is hardcoded to Chartink today
(`blueprints/chartink.py`, `database/chartink_db.py`). Chartink is
an India-shaped third-party screener whose webhook payload speaks
NSE/BSE symbols and India product types. Other regions need their
own screener integrations (TradingView screener for US, future EU
broker-native screeners, etc.).

The right abstraction is provider-pluggable.

## Decision

The Screener feature becomes provider-pluggable. The
`ScreenerProvider` Protocol in
`services/screeners/providers/base.py` defines the contract:

```python
class ScreenerProvider(Protocol):
    provider_code: str       # e.g., "chartink"
    region_code: str         # e.g., "india"
    supported_venues: list[str]
    def validate_webhook_payload(self, payload: dict) -> ScreenerSignal: ...
    def supported_signal_types(self) -> set[str]: ...
    def map_signal_to_orders(self, signal, config) -> list[NormalizedOrderRequest]: ...
```

`ScreenerSignal` and `ScreenerConfig` companion dataclasses live in
the same module.

v4 ships one implementation:

* **Chartink** (`services/screeners/providers/india/chartink.py`) —
  parses Chartink's webhook payload (`{stocks, trigger_prices,
  scan_name, alert_name, ...}`), infers signal_type from
  scan_name/alert_name keywords (sell / bearish / short → "sell";
  exit / square off → "exit"; default "buy"), maps to
  NormalizedOrderRequest with `extra["product"]` carrying the
  India product type.

US screener provider is **out of v4 scope per user clarification**.
A stub directory `services/screeners/providers/us/` exists with a
README explaining how a future TradingView screener provider would
register.

Dispatcher in `services/screeners/dispatcher.py`:

* Auto-registers Chartink at module load.
* `get_screener_provider(provider_code)` raises
  `ScreenerProviderNotRegistered` (mapped to
  `ErrorCode.SCREENER_PROVIDER_NOT_REGISTERED`).
* `get_screener_provider_or_none(provider_code)` for UI gating.

## What v4 Phase 10 ships (this ADR)

* `services/screeners/providers/base.py` — Protocol + companion types.
* `services/screeners/providers/india/chartink.py` — Chartink provider.
* `services/screeners/providers/us/__init__.py` — stub.
* `services/screeners/dispatcher.py` — registry + auto-registration.
* 12 contract conformance tests
  (`tests/screeners/test_provider_contract.py`).

## What is deferred to Phase 10-bis

* Refactor `blueprints/chartink.py` (944 lines) to a thin shim that
  calls `services/screeners/dispatcher.dispatch_webhook`. Today the
  blueprint drives Chartink's flow directly; parity-protected.
* Refactor `database/chartink_db.py` to add nullable `provider_code`
  + `region_code` columns + backfill migration script
  (`upgrade/migrate_chartink_provider_columns.py`).
* `parity_chartink_india` parity harness covering bit-identical
  webhook → orders behavior.
* `BrokerCapabilities.supports_screener_providers` capability metadata.
* Frontend Chartink UI hidden when broker doesn't list the provider.

The contract + India provider + dispatcher are the load-bearing
pieces. Phase 10-bis lands the wiring incrementally without breaking
the parity-protected India Chartink path.

## Cross-references

* ADR 0023 — v4 scope.
* `services/screeners/providers/{base,india,us}/`,
  `services/screeners/dispatcher.py`.
* `tests/screeners/test_provider_contract.py`.
