# v6 Phase 2-bis screener — Complete

* **Branch:** `refactor/v6-phase-2-bis-screener`
* **Branched from:** `dev` @ `88f41d04` (HEAD: v6 Phase 2-bis options)

## Goal achieved

`blueprints/chartink.py:webhook` resolves the Chartink screener
provider through `services.screeners.dispatcher.get_screener_provider`
right after parsing the incoming JSON. India parity is bit-identical
(the legacy webhook handler produces the same orders); the dispatcher
integration surfaces a structured `screener_provider_not_registered`
503 if the registry is broken.

## What shipped

* `blueprints/chartink.py` — webhook handler now calls
  `get_screener_provider("chartink")` after parsing the payload.
  Phase 2-bis-2 will migrate the legacy parser (lines ~810-...) into
  `provider.validate_webhook_payload(...)` calls.
* `tests/contracts/test_v6_screener_dispatcher_caller_migration.py`
  — 3 assertions: blueprint imports the dispatcher, handles
  `ScreenerProviderNotRegistered`, and the Chartink provider is
  auto-registered.

## Comprehensive test gate (passed)

| Step | Result |
|---|---|
| `uv run pytest tests/ -x --tb=short` | **2628 passed, 7 skipped, 2 xfailed** in 4:37 (was 2625; +3 contract tests) |
| `uv run pytest -x tests/contracts/test_v4_closing_invariants.py tests/contracts/test_v5_closing_invariants.py tests/contracts/test_v6_closing_invariants.py` | 35 passed |
| `uv run python tests/parity/run_parity.py` | **41/41** — `parity_chartink_india` bit-identical |
| All audits | exit 0 |
| Frontend | 160 passed / 0 lint:literals |

## Next phase

`v6-phase-2-bis-strategy` — strategy/flow scheduler venue-aware
migration.
