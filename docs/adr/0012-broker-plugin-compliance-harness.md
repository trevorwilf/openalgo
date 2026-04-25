# ADR 0012 — Broker plugin compliance harness

Status: accepted (Phase 7, market-agnostic v2)
Date: 2026-04-25

## Context

OpenAlgo ships 24+ legacy India broker plugins plus the Alpaca
promoted-lane plugin from Phase 6. As we plan Schwab, Webull, and
other non-India broker plugins, we need a reusable contract every
broker plugin must clear before it can be promoted. Without a single
harness, each new broker would discover the contract by reading prior
plugins — slow, error-prone, and easy to skip.

## Decision

### `tests/compliance/broker_plugin_compliance.BrokerComplianceMixin`

A pytest-friendly mixin. Subclass it with a `BROKER_CODE` and a
`STRICT` boolean. Each test method asserts one contract surface:

| Test | Contract | Strict-mode behavior | Non-strict-mode behavior |
|---|---|---|---|
| `test_a_metadata_plugin_json_validates` | metadata | required | required |
| `test_b_auth_module_exposes_authenticate` | auth | required (`authenticate` or `authenticate_broker`) | optional |
| `test_c_account_snapshot_uses_normalized_shape` | account | optional (skipped if no `get_account_snapshot`); fails when present but returns a non-`NormalizedAccountSnapshot` shape | same |
| `test_d_translator_module_exists` | translator | required (`<X>OrderTranslator` with `validate`/`to_native`/`from_native_order_response`) | optional |
| `test_e_market_data_adapters_optional` | market_data | optional | optional |
| `test_f_instrument_sync_optional` | instrument_sync | optional | optional |
| `test_g_rule_matrix_optional` | rules | optional (runtime rule loading is exercised in dispatcher tests) | optional |
| `test_h_lane_isolation_imports_and_literals` | lane_isolation | required for promoted brokers (sentinel file or non-india `supported_regions`) | optional |
| `test_i_fail_closed_capability_metadata` | fail_closed | required for non-India plugins (Phase 1 + Phase 3 completeness checks) | optional |

Subclasses for shipped brokers:

* `tests/compliance/test_alpaca_compliance.py` — `STRICT = True`.
  Alpaca passes every required contract today.
* `tests/compliance/test_indian_brokers_baseline.py` — `STRICT = False`
  for zerodha, dhan, deltaexchange. Records the baseline so the matrix
  reflects current state without failing the build on intentional gaps.

### `domain.account.NormalizedAccountSnapshot`

Promoted from `broker.alpaca.api.account_api.AccountSnapshot` to
`domain/account.py`. The legacy name `AccountSnapshot` remains as an
alias in the Alpaca module for backward-compatible imports. Future
brokers MUST return this type from `get_account_snapshot`.

### Compliance matrix

`docs/refactor/broker_compliance_matrix.md` — the operator-readable
matrix. Each row is one broker; each cell is one contract. ✅ = pass,
❌ = fail, `skip` = not applicable.

`tests/compliance/render_matrix.py` regenerates the markdown from the
in-process `COMPLIANCE_RESULTS` dict (populated as the harness runs).

### `/api/v2/admin/broker_compliance` endpoint

`restx_api/v2/broker_compliance.py` parses the markdown matrix and
serves it as JSON. Future admin Settings panel reads this to render a
green/red matrix without re-running the harness on every page load.

## Consequences

* **Schwab and Webull (and any future broker)** gain a documented
  contract: drop a `tests/compliance/test_<broker>_compliance.py`
  with `STRICT = True`, run it, ship when every cell is ✅.
* **Existing Indian brokers** are baseline-recorded but not blocked.
  The matrix shows their gaps without failing the build.
* **CI gate**: future work adds a workflow step that runs the strict
  compliance tests and blocks merge on any ❌. The framework is in
  place; the gate is a single-line CI addition.
* **Frontend admin page** (Phase 7 follow-up) reads the JSON endpoint
  and renders the matrix.

## Alternatives considered

* **Pytest parametrize over every broker.** Rejected — each broker
  needs its own `STRICT` knob and its own deviation comments. A
  subclass per broker file is more readable and allows per-broker
  documentation.
* **Generate the matrix from the test report.** Rejected — pytest
  doesn't expose per-class outcomes in a portable format. The
  in-process `COMPLIANCE_RESULTS` dict is a 30-line solution that
  keeps the renderer simple.

## References

* ADR 0005 — Two lanes
* ADR 0006 — Literal scanner and fail-closed capabilities
* ADR 0008 — Promoted dispatch fail-closed and AccountContext
* `tests/compliance/broker_plugin_compliance.py`
* `docs/refactor/broker_compliance_matrix.md`
* `restx_api/v2/broker_compliance.py`
