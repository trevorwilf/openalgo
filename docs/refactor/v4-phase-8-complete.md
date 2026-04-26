# v4 Phase 8 — Complete (PARTIAL — blueprint wiring in Phase 8-bis)

* **Branch:** `refactor/v4-phase-8-sandbox-providers`
* **Merged:** to `dev` with `--no-ff`
* **Effort:** max

## Goal

Sandbox (paper trading / order simulation) becomes provider-pluggable.
India provider preserves current behavior bit-identically; US provider
ships with mock data. Framework can host EU / UK / future providers
without core changes.

## Invariants enforced

* **Invariant 7** (Sandbox slice) — provider-pluggable contract +
  India + US implementations + dispatcher exist. The Phase 1 v4
  contract test `test_v4_advanced_feature_provider_contracts.py`
  Sandbox xfail removed (now passes).

## What shipped

### `services/sandbox/providers/base.py` — `SandboxProvider` Protocol

* `Fill`, `MarketDataSnapshot`, `ProviderRules` companion dataclasses.
* `SandboxProvider` Protocol with 9 methods covering settlement
  date, square-off, fill simulation, supported products /
  order-types, base currency, initial funds, partial fills,
  position lifecycle rules.

### `services/sandbox/providers/india/` — India provider

* `IndiaSandboxProvider` — preserves bit-identical India semantics:
  T+1 / MIS-CNC-NRML / ₹10,00,000 / 15:15 IST MIS square-off / no
  partial fills.

### `services/sandbox/providers/us/` — US provider (mock data)

* `USSandboxProvider`:
  * T+2 settlement equity (with weekend skip), T+1 options.
  * DAY_TRADE / OVERNIGHT / MARGIN products.
  * USD $100,000 initial funds.
  * Partial-fill simulation: low-liquidity orders (volume < 100,
    quantity > volume/2) split into two fills.
  * XNYS 16:00 ET DAY_TRADE close.

### `services/sandbox/dispatcher.py` — registry + fail-closed

* `register_sandbox_provider`, `get_sandbox_provider` (raises
  `SandboxProviderNotRegistered`), `get_sandbox_provider_or_none`,
  `clear_sandbox_registry_for_tests`,
  `install_default_sandbox_providers`.
* Auto-installs India + US providers at module load.
* `SandboxProviderNotRegistered` carries `ErrorCode.SANDBOX_PROVIDER_NOT_REGISTERED`
  for v2 API mapping.

### `docs/adr/0026-sandbox-provider-contract.md`

ADR documenting the contract, the v4 implementations, and what is
deferred to Phase 8-bis (blueprint wiring + DB schema additions +
sandbox UI).

## New tests added

| File | Tests |
|---|---|
| `tests/sandbox/test_provider_contract.py` | 13 (India + US contract conformance, settlement date semantics, square-off semantics, dispatcher resolution, fail-closed for unknown region) |
| `tests/contracts/test_v4_advanced_feature_provider_contracts.py` | Sandbox xfail removed (1 test now passes) |

## What is deferred to Phase 8-bis

Per ADR 0026 § "What is deferred to Phase 8-bis":

* `blueprints/sandbox.py` (1178 lines) — wire to dispatcher rather
  than hardcoded India path.
* `database/sandbox_db.py` — additive `region_code` + `currency`
  columns + migration script.
* Sandbox UI region-aware dispatch (frontend).
* `BrokerCapabilities.supports_sandbox` capability metadata.
* `parity_sandbox_india` parity harness.

The contract + providers + dispatcher are the load-bearing pieces.
Phase 8-bis lands the wiring incrementally without breaking the
parity-protected India sandbox path.

## Comprehensive testing (gate 2.6)

| Step | Result |
|---|---|
| `pytest -x tests/contracts/ tests/parity/ tests/compliance/ tests/sandbox/` | 158 passed, 2 xfailed |
| `python tests/parity/run_parity.py` | 8/8 passed |
| `pytest tests/` | 1963 passed, 7 skipped, 2 xfailed — 161s |
| `npm run lint:literals` | 253 files / 0 violations |
| `python scripts/audit/classify_files.py --check` | 821 files / no drift |

All gates pass.

## Files touched

* Created: `services/sandbox/__init__.py`,
  `services/sandbox/providers/__init__.py`,
  `services/sandbox/providers/base.py`,
  `services/sandbox/providers/india/__init__.py`,
  `services/sandbox/providers/us/__init__.py`,
  `services/sandbox/dispatcher.py`,
  `tests/sandbox/test_provider_contract.py`,
  `docs/adr/0026-sandbox-provider-contract.md`,
  this completion doc.
* Modified: `tests/contracts/test_v4_advanced_feature_provider_contracts.py`,
  `docs/refactor/file_classification.md` (regen).
