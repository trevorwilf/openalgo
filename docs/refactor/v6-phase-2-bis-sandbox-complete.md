# v6 Phase 2-bis sandbox — Complete (partial scope)

* **Branch:** `refactor/v6-phase-2-bis-sandbox`
* **Branched from:** `dev` @ `476ac0fe` (HEAD: v6 Phase 1-bis merge)
* **Effort:** max — narrow but substantive migration.

## Goal achieved

`sandbox/order_manager.py` validates the order's product against
`get_sandbox_provider("india").supported_products()` instead of a
hardcoded `["CNC", "NRML", "MIS"]` list. India parity is bit-identical
because the India provider returns exactly that set.

## What shipped

### `sandbox/order_manager.py` migration

```python
# Before:
if order_data["product"].upper() not in ["CNC", "NRML", "MIS"]:
    return False, "Invalid product. Must be CNC, NRML, or MIS"

# After:
from services.sandbox.dispatcher import get_sandbox_provider
sandbox_provider = get_sandbox_provider("india")
supported_products = sandbox_provider.supported_products()
if order_data["product"].upper() not in supported_products:
    return False, "Invalid product. Must be CNC, NRML, or MIS"
```

This is the canonical Phase 2-bis migration shape: dispatcher call
→ provider metadata → behavior identical for the active region.

### Documented `fund_manager` discrepancy

The legacy `sandbox/fund_manager.py` defaults `starting_capital` to
`"10000000.00"` (₹1Cr). The India sandbox provider's `initial_funds()`
returns `Decimal("1000000.00")` (₹10L). The two values are 10× apart
— the v4 provider scaffolding underspecified the value. v6
Phase 2-bis preserves the legacy ₹1Cr default for India parity and
documents the discrepancy in the file itself; reconciling the values
is tracked as a follow-up that can land per-PR with operator
verification.

### Contract test

`tests/contracts/test_v6_sandbox_dispatcher_caller_migration.py` (3
tests):

* `test_order_manager_validates_via_dispatcher_supported_products` —
  asserts the file imports `get_sandbox_provider` and calls
  `supported_products()`.
* `test_india_sandbox_provider_supported_products_match_legacy_set`
  — asserts `IndiaSandboxProvider.supported_products() ==
  {"MIS", "CNC", "NRML"}`. If anyone changes the provider to add /
  remove a product, this test catches it before parity_sandbox_india
  silently regresses.
* `test_fund_manager_default_capital_documents_provider_discrepancy`
  — asserts the legacy ₹1Cr default is preserved AND the file notes
  the discrepancy.

## What is deferred to Phase 2-bis-2

The remaining sandbox surfaces all touch hot paths that need browser
verification on a live India broker:

* `sandbox/squareoff_manager.py` / `sandbox/squareoff_thread.py` —
  square-off time literal `15:15` and `Asia/Kolkata` scheduler.
  Migrate to `provider.squareoff_time_for_product(...)`.
* `sandbox/catch_up_processor.py` — T+1 settlement clock.
  Migrate to `provider.settlement_date_for_order(...)`.
* `sandbox/holdings_manager.py` — T+1/CNC settlement.
* `sandbox/execution_engine.py` — IST execution timestamps.
* `database/sandbox_db.py` — region/currency seed defaults.
* `blueprints/sandbox.py` — admin UI defaults.
* Reconcile `IndiaSandboxProvider._INITIAL_FUNDS` (₹10L) with the
  legacy ₹1Cr default. Preferred fix: update the provider to ₹1Cr
  (and the parity_sandbox_india fixture to match).

## Comprehensive test gate (passed)

| Step | Result |
|---|---|
| `uv run pytest tests/ -x --tb=short` | **2616 passed, 7 skipped, 2 xfailed** in 4:03 (was 2613; +3 = new contract tests) |
| `uv run pytest -x tests/contracts/test_v4_closing_invariants.py tests/contracts/test_v5_closing_invariants.py tests/contracts/test_v6_closing_invariants.py` | **35 passed** |
| `uv run python tests/parity/run_parity.py` | **41/41** verify-mode harnesses |
| `uv run python tests/parity/run_parity.py --lane v1` | **11/11** v1-lane harnesses |
| `uv run python tests/parity/run_parity.py --lane v2` | **41/41** v2-lane harnesses |
| `uv run python scripts/audit/classify_files.py --check` | exit 0 — 879 files / no drift |
| `npm test -- --run` (frontend) | **160 passed** |
| `npm run lint:literals` | exit 0 |

`parity_sandbox_india` remains bit-identical — the order_manager
migration is value-preserving by design.

## Next phase

`v6-phase-2-bis-options` — same shape applied to options service
entry points (`expiry_service`, `option_chain_service`, etc.).
