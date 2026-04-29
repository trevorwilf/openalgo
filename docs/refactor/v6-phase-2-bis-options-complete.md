# v6 Phase 2-bis options — Complete (4 of 10 services migrated)

* **Branch:** `refactor/v6-phase-2-bis-options`
* **Branched from:** `dev` @ `c9d79a04` (HEAD: v6 Phase 2-bis sandbox)
* **Effort:** max — 4 of the 10 options services migrated.

## Goal achieved

Four options service entry points now resolve the India options
provider through `services.options.dispatcher.get_options_provider`
after their region gate passes. India parity is bit-identical (the
provider's region matches the service's pre-existing assumption);
the dispatcher integration:

* Surfaces a structured `OPTIONS_PROVIDER_NOT_REGISTERED` 503 when
  the provider is missing (defensive — should never fire in
  production).
* Establishes the insertion point where Phase 2-bis-2 will migrate
  the legacy SymToken / option-symbol parsing into provider methods.
* Catches at runtime any future scaffolding regression that
  unregisters the India provider.

## What shipped

Four services migrated:

* `services/expiry_service.py` — Already had the `is_india_region_active()`
  gate (returning `expiry_grammar_not_supported_in_region` 422 for
  non-India). After the gate, calls `get_options_provider("india")`.
* `services/iv_chart_service.py` — Same pattern after the
  `iv_chart_disabled_in_region` 422 gate.
* `services/option_greeks_service.py` — Same pattern after the
  `option_greeks_disabled_in_region` 422 gate.
* `services/options_multiorder_service.py` — Same pattern after the
  `multi_option_disabled_in_region` 422 gate.

Contract test: `tests/contracts/test_v6_options_dispatcher_caller_migration.py`
— 9 assertions across the 4 migrated services + 1 sanity test that
the India provider is registered.

## What is deferred to Phase 2-bis-2

Six options surfaces still hold direct India-shaped logic:

* `services/option_chain_service.py`
* `services/option_symbol_service.py`
* `services/straddle_chart_service.py`
* `services/oi_profile_service.py`
* `services/gex_service.py`
* `services/iv_smile_service.py`

These can be migrated using the same pattern (gate → dispatcher call
→ legacy fall-through). They were left in this phase because each
adds another contract row and the gate is symbolic until Phase
2-bis-2 actually moves the legacy SymToken queries into provider
methods.

## Comprehensive test gate (passed)

| Step | Result |
|---|---|
| `uv run pytest tests/ -x --tb=short` | **2625 passed, 7 skipped, 2 xfailed** in 4:33 (was 2616; +9 contract tests) |
| `uv run pytest -x tests/contracts/test_v4_closing_invariants.py tests/contracts/test_v5_closing_invariants.py tests/contracts/test_v6_closing_invariants.py` | 35 passed |
| `uv run python tests/parity/run_parity.py` | **41/41** verify-mode harnesses |
| `uv run python tests/parity/run_parity.py --lane v1` | **11/11** v1-lane harnesses |
| `uv run python tests/parity/run_parity.py --lane v2` | **41/41** v2-lane harnesses |
| `uv run python scripts/audit/classify_files.py --check` | exit 0 — 879 files / no drift |
| `npm test -- --run` (frontend) | **160 passed** |
| `npm run lint:literals` | exit 0 |

`parity_options_india` remains bit-identical.

## Next phase

`v6-phase-2-bis-screener` — Chartink blueprint dispatcher migration.
