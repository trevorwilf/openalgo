# ADR 0011 — Region-gating for option, flow, sandbox, and analytics

Status: accepted (Phase 6, market-agnostic v2)
Date: 2026-04-25

## Context

Several India-specific products and surfaces ship as if they were
generic platform features:

* `services/option_symbol_service.get_option_symbol` — assumes NSE/NFO
  underlyings, DDMMMYY expiries, CE/PE option rights.
* `services/expiry_service` — DDMMMYY parser hardcoded.
* `services/flow_executor_service` — defaults flows to NSE/MIS/NIFTY.
* `services/iv_chart_service`, `option_greeks_service`, `gex_service` —
  India-only formula assumptions and underlyings.
* `sandbox/order_manager` and `sandbox/position_manager` — encode
  MIS/CNC/NRML, T+1 holdings, IST square-off.
* `blueprints/analyzer` — was guarded only by
  `@requires_capability("supports_analyzer")`, but the Alpaca plugin
  declares `supports_analyzer: true`, so the existing gate did not
  enforce ADR 0004's "analyzer is India-only" decision.

Phase 6 wraps these surfaces in explicit region gates so non-India
deployments either see an empty / disabled state or a structured
`FeatureNotAvailableInRegion` reject.

## Decision

### `services/feature_gate_service`

A new helper:

```python
def active_region_code() -> str: ...
def is_india_region_active() -> bool: ...
def is_feature_enabled_for_active_region(flag: str, default: bool = False) -> bool: ...
```

Resolution order:

1. `MARKET_REGION_FOR_TESTS` env var (test-only short-circuit).
2. The active broker's `BrokerCapabilities.supported_regions[0]` from
   the Flask session.
3. The user's stored `settings.default_market_region`.
4. `"india"` as the final fallback (legacy installs unchanged).

`is_feature_enabled_for_active_region` reads the region plugin's
`feature_flags` block (Phase 2 schema v2). India returns the flags
declared in `market_regions/india/plugin.json` —
`option_chain_enabled=true`, `sandbox_enabled=true`,
`flow_templates_enabled=true`, etc. Other regions ship with these
all-false unless explicitly opted in.

### Service-level gates applied in Phase 6

| Surface | Gate location | Active region != india behavior |
|---|---|---|
| `services.option_symbol_service.get_option_symbol` | top of function | `(False, {"code":"option_chain_disabled", ...}, 422)` |
| `sandbox.order_manager.OrderManager.__init__` | constructor | raises `SandboxNotAvailableInRegion` |
| `blueprints.analyzer.analyzer` (route `/`) | new `@india_region_only()` decorator | HTTP 404 with `code: "analyzer_india_region_only"` |

### `utils.capability_guards.india_region_only`

A new Flask route decorator that mirrors `@requires_capability`'s
shape but checks `is_india_region_active()` directly. Returns 404
with the stable error code `analyzer_india_region_only`.

The other India-specific surfaces (expiry parsing, IV chart, GEX,
flow executor, the rest of the analyzer routes) are intentionally
left for follow-up. The decorator and helper provide the framework;
the per-surface application can land incrementally without changing
the contract. The capability_guards' `requires_capability` decorator
remains the per-broker-feature gate; the new `india_region_only`
adds the per-region gate. Routes that need both apply both decorators.

### Errors

`domain/errors.py`:

* `FeatureNotAvailableInRegion(active_region, code)` — generic.
* `SandboxNotAvailableInRegion(active_region)` — specialization for
  sandbox paths, code = `sandbox_region_unsupported`.
* `ErrorCode` namespace exposes the stable codes:
  `option_chain_disabled`, `expiry_grammar_not_supported_in_region`,
  `option_grammar_not_supported_in_region`, `sandbox_region_unsupported`,
  `analyzer_india_region_only`, `flow_template_region_unsupported`.

## Consequences

* **India-region installs are unchanged** — the gates default to India.
  Parity harness still passes bit-identical.
* **Non-India installs cannot accidentally use sandbox** — the
  constructor raises before any T+1 / IST / MIS code path is hit.
* **Non-India installs cannot accidentally use the option chain** —
  the entry point returns a structured 422 with a stable code that
  the frontend can render as "this feature is only available for
  India region today."
* **The Alpaca analyzer leak is closed** — `supports_analyzer: true`
  on the plugin no longer is sufficient to enter the analyzer; the
  `@india_region_only()` decorator on the dashboard route is.
* **Future incremental application** is just adding the same
  `is_feature_enabled_for_active_region(...)` call to other entry
  points (expiry/iv/gex/flow_executor), or layering the
  `@india_region_only()` decorator on the rest of the analyzer
  routes. The framework is in place; the work is per-surface.

## Alternatives considered

* **Drop ``supports_analyzer: true`` from the Alpaca plugin.**
  Rejected — that hides the issue but doesn't enforce the policy
  for future plugins.
* **Region-pivot the entire option service.** Rejected — would
  require porting expiry grammar, option-right codes, futures
  grammar all at once. The schema v2 + region gates lay the
  foundation; the deep refactor is its own multi-phase effort.

## References

* ADR 0004 — Analyzer stays India-limited
* ADR 0007 — Region plugin schema v2 (feature_flags)
* `services/feature_gate_service.py`
* `utils/capability_guards.py` — `india_region_only`
* `domain/errors.py` — `FeatureNotAvailableInRegion`,
  `SandboxNotAvailableInRegion`, `ErrorCode`
