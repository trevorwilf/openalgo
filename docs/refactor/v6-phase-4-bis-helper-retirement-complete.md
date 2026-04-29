# v6 Phase 4-bis helper retirement — Complete

* **Branch:** `refactor/v6-phase-4-bis-helper-retirement`
* **Branched from:** `dev` @ `<v6 Phase 2-bis strategy>`
* **Effort:** high

## Goal achieved

`_legacy_india_region_for_compat()` is **removed** from
`services/feature_gate_service.py`. The `legacy_india_fallback`
parameter is **removed** from `active_region_code()`. Both gate
functions (`is_india_region_active`, `is_feature_enabled_for_active_region`)
are now capability-driven — they catch `RegionResolutionError` and
return `False` / the caller's `default` instead of silently falling
back to India.

ADR 0031 invariant **v6-9** is now enforced.

## What shipped

### `services/feature_gate_service.py`

* Removed the `legacy_india_fallback` parameter from
  `active_region_code()`. The function now always raises
  `RegionResolutionError` when neither broker capabilities nor
  settings yield a region.
* Removed `_legacy_india_region_for_compat()` from the module.
* Rewrote `is_india_region_active()` to call `active_region_code()`
  in a try/except — returning `False` on `RegionResolutionError`.
  This makes the gate capability-driven (no broker → not India).
* Rewrote `is_feature_enabled_for_active_region()` similarly — falls
  through to caller's `default` on `RegionResolutionError`.
* Updated `require_region_feature()` to handle the
  `RegionResolutionError` case explicitly (uses `"unknown"` as the
  region label in the error envelope).
* Updated module docstring to document the v6 Phase 4-bis state.

### `services/market_region_service.py` — retained

The market_region_service has its own private
`_legacy_india_region_for_compat()` that is the multi-region catalog
tie-breaker (when an install has multiple region plugins available,
prefer India in the catalog default). That function is **not** a
region gate; it is allowed to remain. The
`test_v6_helper_retired.test_market_region_service_helper_retained`
asserts it stays callable.

### Test changes

* `tests/contracts/test_v6_helper_retired.py` rewritten:
  Phase 4 deferred-state markers (`xfail(strict=True)`) inverted to
  Phase 4-bis retired-state assertions. 4 tests:
  * Helper not importable from feature_gate_service.
  * `legacy_india_fallback` no longer in `active_region_code`'s
    signature.
  * `is_india_region_active()` returns False for the no-broker case
    (capability-driven).
  * market_region_service's helper IS retained (different concern).
* `tests/services/test_feature_gate_service.py` —
  `test_default_active_region_legacy_fallback_returns_india` →
  `test_default_active_region_raises_when_no_broker_no_settings`.
* `tests/services/test_feature_gate_no_silent_fallback.py` —
  `test_active_region_code_legacy_fallback_returns_india` removed;
  `test_is_india_region_active_never_raises` →
  `test_is_india_region_active_returns_false_when_no_broker`;
  `test_is_feature_enabled_passes_default_to_region_lookup` updated
  to use a resolvable region; new
  `test_is_feature_enabled_returns_default_when_no_region_resolves`
  asserts the no-region short-circuit doesn't even call the lookup.

### `tests/contracts/test_v6_closing_invariants.py`

Added new `test_v6_invariant_v6_9_legacy_helper_retired` that
asserts `_legacy_india_region_for_compat` is gone and the parameter
is removed.

## Behavior change

The only visible behavior change is in the **no-broker, no-settings
default region** case. Previously `is_india_region_active()` returned
True; now it returns False. This affects:

* Fresh installs that have not yet logged into a broker AND have not
  configured `default_market_region` in settings. Sandbox / options
  / screener services would 422 / 503 those requests instead of
  silently treating them as India. The user must connect a broker
  or set the default region.

For all India users with a connected India broker, behavior is
**bit-identical**: the broker capabilities resolve to `india` and
the gate returns True exactly as before.

## Comprehensive test gate (passed)

| Step | Result |
|---|---|
| `uv run pytest tests/ -x --tb=short` | **2633 passed, 7 skipped** in 4:22 (was 2630 / 7 / 2xfailed; the 2 xfails are retired) |
| `uv run pytest -x tests/contracts/test_v4_closing_invariants.py tests/contracts/test_v5_closing_invariants.py tests/contracts/test_v6_closing_invariants.py` | **36 passed** (was 35; +1 = v6-9 invariant) |
| `uv run python tests/parity/run_parity.py` | **41/41** verify-mode harnesses |
| All audits | exit 0 |
| Frontend | 160 passed / 0 lint:literals |

`parity_sandbox_india`, `parity_options_india`, `parity_chartink_india`
all bit-identical — the gate functions return True for India users
with a connected broker, exactly as before.

## Next phase

`v6-phase-4-bis-mocks` — extend mock Schwab/Webull plugins per Q6
default (3 lighter mock-extension targets).
