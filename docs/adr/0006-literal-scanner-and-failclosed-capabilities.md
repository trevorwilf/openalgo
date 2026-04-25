# ADR 0006 — Literal scanner and fail-closed capability inference

Status: accepted (Phase 1, market-agnostic v2)
Date: 2026-04-25

## Context

Two independent expert reviews of the prior market-agnostic refactor
(`market-agnostic-phases_Claude_code.md`) flagged two boundary leaks
that the import-only lane-isolation contract did not catch:

1. **India-specific string literals** continued to enter promoted-lane
   Python source as bare strings — `"Asia/Kolkata"`, `"NSE"`, `"MIS"`,
   `"₹"`, etc. The AST-only import scanner in
   `tests/contracts/test_lane_isolation.py` does not see these.

2. **`domain/capabilities.py` silently inferred `broker_type="IN_stock"`**
   (and INR/MIS/CNC defaults) for any broker that omitted the field.
   For a plugin that declares `supported_regions=["us"]` but forgets a
   `broker_type`, the resulting `BrokerCapabilities` would carry the
   Indian defaults — a silent data bug that will surface only at order
   placement time.

Both leaks must be closed *before* any new feature work in the
market-agnostic v2 series; otherwise every later phase risks
re-introducing the pattern they were meant to remove.

## Decision

### Literal scanner

`tests/contracts/test_lane_isolation.py` gains a second contract:
`test_no_india_specific_literals_in_promoted_paths`. The scanner walks
every promoted-path Python file (the same set the import scanner uses)
and rejects any of:

```
"Asia/Kolkata", "IST", "NSE", "NFO", "BSE", "BFO", "MCX", "CDS",
"MIS", "CNC", "NRML", "DDMMMYY", "CE", "PE", "₹", "INR"
```

Detection runs in two passes:

* **AST pass** — `ast.Constant` nodes whose value is a `str`. Module,
  class, and function docstrings are exempt.
* **Regex pass** — line-by-line over the source, comments stripped,
  with word-boundary anchoring so identifiers like `MISC` do not
  trip on `MIS`.

A phase-scoped `LITERAL_ALLOWLIST` mirrors the existing import
`ALLOWLIST`. Entries must include a TODO referencing the phase that
removes them. Empty for Phase 1.

A second, **warning-only** scanner runs over `services/`, `domain/`,
and `utils/` (with a small exclusion list for files that are
pre-existing legacy / Indian — `services/quotes_service.py`,
`services/option_*.py`, `utils/auth_utils.py`, etc.). It prints
findings but does not fail. Phases 4–6 narrow the exclusion list as
they own the migration of each file.

### Fail-closed capability inference

`infer_capabilities_from_legacy(plugin_data, broker_code)` now branches
on whether the plugin is **legacy India** or **non-India**:

* A plugin is **legacy India** if `supported_regions` is omitted, is
  empty, or equals `["india"]`. The pre-existing inference (IN_stock /
  crypto / skeleton) runs unchanged.
* A plugin is **non-India** otherwise. It must declare *all four*
  required explicit fields:
  * `broker_type`
  * `market_families`
  * `default_currency`
  * `base_currency`

  Missing any of these raises `domain.errors.BrokerCapabilityError`,
  which carries `broker_code` and `missing_fields`. The legacy
  IN_stock branch is **never** silently entered for a non-India plugin.

The behavior is gated by the env flag `STRICT_CAPABILITY_INFERENCE`
(default on). Setting `STRICT_CAPABILITY_INFERENCE=0` downgrades the
raise to a logged warning so an operator can roll back without a
plugin edit.

### New error types

`domain/errors.py` gains:

* `BrokerCapabilityError(broker_code, missing_fields)` — the fail-closed
  capability check above.
* `FeatureNotAvailableInRegion(active_region, code)` — used by Phase 6
  for region-gated features. Declared here so the import surface stays
  centralized.
* `ErrorCode` namespace — stable string codes returned in JSON error
  bodies (`capability_incomplete`, `translator_not_registered`,
  `unsupported_capability`, `rule_violation`,
  `promoted_lane_required_for_non_india_broker`,
  `option_chain_disabled`, `sandbox_region_unsupported`,
  `analyzer_india_region_only`, etc.).

## Consequences

* **Legacy India brokers (24+) are unaffected.** Their plugin.json
  files have no `supported_regions`, so they continue down the legacy
  inference path with identical results. The parity harness
  (`tests/parity/run_parity.py`) confirms this.
* **The Alpaca plugin** declares all required fields (the
  `default_currency` field was added in this phase). The plugin
  validates under the new fail-closed path.
* **Promoted-lane authors** can no longer accidentally hardcode
  `"NSE"` or `"₹"` in v2 service code. The literal scanner is part of
  the lane-isolation contract.
* **Future broker authors** writing a non-India plugin get an
  immediate, structured error if they omit metadata — instead of a
  silent IN_stock leak that surfaces months later in a production
  trade.

## Alternatives considered

* **Hard-fail the warning-only core scanner immediately.** Rejected —
  there are dozens of pre-existing India literals in `services/` that
  later phases will migrate. Failing the build on day one of Phase 1
  would block every phase.
* **Use a runtime check instead of an AST scanner.** Rejected — a
  runtime check only catches code paths actually exercised in tests.
  An AST scan is cheap, deterministic, and sees every line.

## References

* ADR 0005 — Two lanes (legacy and promoted)
* `tests/contracts/test_lane_isolation.py`
* `tests/contracts/test_literal_scanner.py`
* `domain/capabilities.py` — `_check_explicit_fields_for_non_india`
* `domain/errors.py` — `BrokerCapabilityError`, `ErrorCode`
