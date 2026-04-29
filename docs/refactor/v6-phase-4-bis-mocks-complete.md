# v6 Phase 4-bis mocks — Complete (3 lighter targets)

* **Branch:** `refactor/v6-phase-4-bis-mocks`
* **Branched from:** `dev` @ `<v6 Phase 4-bis helper retirement>`
* **Effort:** medium

## What shipped (3 of 5 Phase 0 targets per Q6 default)

### 1. Combo MULTILEG_OPTIONS dispatch
* `broker/_mock_webull_like/plugin.json` — added `MULTILEG_OPTIONS`
  to `supports_combo_types`.
* `broker/_mock_webull_like/api/order_api.py` — added
  `MULTILEG_OPTIONS` to `NATIVE_ENTRUST_TYPES` (Webull-style direct
  passthrough). Aliased the dict as `NATIVE_STRATEGY_TYPES` for
  contract-test parity with the mock Schwab translator.
* Mock Schwab already had MULTILEG_OPTIONS; this brings Webull to
  parity.

### 2. Position adapter currency propagation
* No code change required — the existing
  `MockSchwabLikePositionAdapter` and `MockWebullLikePositionAdapter`
  already return positions with explicit `currency="USD"`. The new
  contract test asserts they keep doing so (and explicitly NOT
  inheriting INR).

### 3. Account context entitlement declaration
* No code change required — both mocks already declare
  `account_context_supports = [..., "entitlements"]`. The new
  contract test asserts the declaration. **Actual
  `rule_enforcement.check_order` integration that reads entitlements
  is a heavier domain change deferred to v7** (per Q6 default).

### Contract test
`tests/contracts/test_v6_mock_plugin_extensions.py` — 9 tests:
- 2 plugin.json combo declarations
- 2 translator NATIVE_STRATEGY_TYPES mappings for MULTILEG_OPTIONS
- 2 position-adapter currency-propagation tests
- 1 balance-adapter currency-propagation test
- 2 plugin.json entitlements declarations

## What is deferred (2 of 5)

* **Master-contract refresh-policy execution** — invoking the
  mock's instrument sync at a non-IST cutoff and asserting the
  refresh policy is honored. Needs `services/account_context_service`
  cutoff plumbing that doesn't exist yet — domain work.
* **Account context entitlement enforcement** —
  `rule_enforcement.check_order` actually reading `entitlements`
  from the account context and raising `entitlement_required` when
  the broker's required entitlement is missing. Same scope: domain
  change, not just a mock update.

Both deferred to v7 with a Phase 0 follow-up audit.

## Comprehensive test gate (passed)

| Step | Result |
|---|---|
| `uv run pytest tests/ -x --tb=short` | **2642 passed, 7 skipped** in 4:29 (was 2633; +9 contract tests) |
| Closing v4+v5+v6 | 36 passed |
| `uv run python tests/parity/run_parity.py` | **41/41** verify-mode harnesses |
| All audits | exit 0 |
| Frontend | 160 passed / 0 lint:literals |

## Next phase

`v6-phase-8-bis-closing-update` — update the v6 closing-invariants
gate to reflect the new state (translator-count invariant, helper
retirement invariant, mock-extension invariant), refresh
`v6-phase-8-complete.md`, update `v6-overview.md`, update CLAUDE.md.
