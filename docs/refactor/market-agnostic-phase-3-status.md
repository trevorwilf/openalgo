# Phase 3 — Migrate the 8 critical service entry points

Status: **shipped**.

This is Phase 3 of the market-agnostic refactor described in
`openalgo_market_agnostic_refactor_claude_code_prompt.md`. The 8 v1
service validators stop importing
`utils.constants.VALID_EXCHANGES` / `VALID_PRODUCT_TYPES` /
`VALID_PRICE_TYPES` / `VALID_ACTIONS` and consume the active region's
`product_vocabulary` / `price_type_vocabulary` / venue catalog
instead. India brokers continue to see bit-identical wire behavior
because the relocated India vocabulary is a perfect snapshot of the
legacy `VALID_*` lists.

## What landed

### Service migrations (T-20)

All eight v1 service entry points listed in the prompt:

| File | Migration |
|------|-----------|
| `services/place_order_service.py` | VALID_* → region helpers; OrderSchema lazy-imported |
| `services/place_smart_order_service.py` | VALID_* → region helpers |
| `services/quotes_service.py` | VALID_EXCHANGES → region helper; `get_token` lazy |
| `services/history_service.py` | VALID_EXCHANGES → region helper; `get_token` lazy |
| `services/depth_service.py` | VALID_EXCHANGES → region helper; `get_token` lazy |
| `services/margin_service.py` | VALID_* → region helpers |
| `services/basket_order_service.py` | VALID_* → region helpers |
| `services/split_order_service.py` | dead VALID_* imports removed; REQUIRED_ORDER_FIELDS inlined |

For each service, the validator now calls
`services.market_region_service.get_allowed_*_for_active_region()`
which:

1. Resolves the active region via
   `services.feature_gate_service.active_region_code()` (broker
   session → settings default → fail-closed).
2. Reads the region's manifest:
   * `venues[]` + `legacy_compat_shim.valid_exchanges` for venues.
   * `product_vocabulary["ALL"]` for products.
   * `price_type_vocabulary["ALL"]` for price types.
   * `legacy_compat_shim.valid_actions` for actions.
3. Returns the list to the validator, which produces the same
   `"Invalid exchange. Must be one of: ..."` error format as before.

### India plugin manifest (`market_regions/india/plugin.json`)

Added 4 venues to round out the legacy `VALID_EXCHANGES` set:
`BCD` (BSE Currency Derivatives), `NCDEX`, `NSE_INDEX`, `BSE_INDEX`.
Added `product_vocabulary` (CNC/NRML/MIS), `price_type_vocabulary`
(MARKET/LIMIT/SL/SL-M), and `legacy_compat_shim.valid_exchanges` (the
11-element legacy `VALID_EXCHANGES` list including `CRYPTO`).

`docs/region-plugin-schema/plugin.v2.schema.json` extended to accept
the new optional fields (Phase 0 schema additions stayed in the
pydantic model; the JSON schema rejected them until this phase
populated them).

### Helpers added to `services/market_region_service.py`

* `get_allowed_venue_codes_for_active_region()`
* `get_allowed_product_codes_for_active_region()`
* `get_allowed_price_type_codes_for_active_region()`
* `get_allowed_action_codes_for_active_region()`
* `_resolve_active_market_region()` — internal; lazy-loads region
  catalog if cache cold; raises `MissingRegionContext` when nothing
  resolvable is available (no silent India default).

### Classification rules

`scripts/audit/classification_rules.yaml` promotes the 8 services
from LEGACY_INDIA → PROMOTED_CORE.
`docs/refactor/file_classification.md` regenerated.

The runtime + static import locks
(`tests/contracts/test_promoted_imports_runtime.py` /
`test_lane_isolation.py`) stripped these 3 services from the
`FORBIDDEN_RUNTIME_MODULES` / `CLASSIFIED_FORBIDDEN_MODULES` lists
because they no longer import legacy at module-load time:

* `services.quotes_service`
* `services.history_service`
* `services.place_order_service`

(The other 5 services were never on that list — they're newly
promoted but have no other PROMOTED_CORE callers today.)

## Tests added

`tests/services/test_v3_phase3_region_aware_validators.py` — 21
parametrized tests covering all 8 services:

* India active → India venue accepted, foreign venue (XNYS)
  rejected with the legacy-format error message that lists the 11
  India venues in legacy order.
* No region resolvable → `MissingRegionContext`-shaped error message
  per service (`"Cannot validate ..."`).
* `services.market_region_service` helpers return lists exactly
  equal to `VALID_EXCHANGES` / `VALID_PRODUCT_TYPES` / `VALID_PRICE_TYPES`
  / `VALID_ACTIONS` for the India region — proving the relocation
  is byte-identical.
* `services.split_order_service` no longer carries the dead VALID_*
  imports.

## Tests adjusted

* `tests/region_loader/test_schema_v2.py::test_shipped_india_plugin_validates_v2`
  — venue snapshot expanded from 6 to 10 venues; new asserts pin
  `product_vocabulary`, `price_type_vocabulary`, and
  `legacy_compat_shim.valid_exchanges`.
* `tests/parity/baseline/parity_quote.py` and `parity_history.py` —
  patch `database.token_db.get_token` (the source) instead of the
  service module attribute, since Phase 3 moved that import to
  function-local. The fixtures (.json files) are unchanged.

## Verification

* `uv run python tests/parity/run_parity.py` — 41/41 parity
  harnesses green.
* `uv run pytest tests/contracts/ tests/services/test_v3_phase3_region_aware_validators.py tests/region_loader/ tests/multi_region/ tests/sandbox/ tests/sessions/ tests/audit/ -q` — 634 tests pass.
* `uv run python scripts/audit/classify_files.py --check` — no
  drift; 8 services now classified PROMOTED_CORE.

## Acceptance status

| Criterion | Status |
|-----------|--------|
| 8 services no longer import from `utils.constants` | ✅ |
| Each migrated service file PROMOTED_CORE; lane-isolation green | ✅ |
| Classifier shows the 8 files moved LEGACY_INDIA → PROMOTED_CORE | ✅ |
| Parity harnesses green on both lanes | ✅ (41/41) |
