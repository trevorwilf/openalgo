# ADR 0025 — Strict-mode schema for promoted broker plugins

* **Status:** accepted
* **Date:** 2026-04-26
* **Phase:** v4 Phase 4

## Context

Phase 1b of v1 introduced the `BrokerCapabilities` model and a JSON
Schema validator at `docs/plugin-schema/plugin.schema.json`. The
schema was set to `additionalProperties: true` to keep legacy India
plugins booting cleanly while the model evolved.

By v4 the gap is real: a promoted plugin can ship with a typo'd
capability key (`account_context_supports_typo: true`) and the
loader silently ignores it. The dispatcher then looks up the
correctly-spelled key, sees nothing, and silently fails. Operators
have no breadcrumb.

## Decision

Promoted plugins are validated in **strict mode**:

1. **Required fields** — every promoted plugin MUST declare:
   `broker_code`, `broker_display_name`, `broker_type`,
   `supported_regions`, `market_families`, `supported_venue_codes`,
   `supported_asset_classes`, `supported_order_types`,
   `supported_time_in_force`, `supported_sessions`,
   `supported_quantity_units`, `trading_currencies`,
   `default_currency`, `base_currency`, `auth_modes`,
   `account_context_supports`, `master_contract_refresh_policy`.

2. **Unknown fields are errors** — strict mode is the
   `additionalProperties: false` equivalent. The list of allowed keys
   is `_strict_known_fields()` in `utils/plugin_loader.py` (the
   union of v4 required fields, WordPress header fields, and
   explicitly-accepted operational metadata).

3. **Legacy India plugins keep non-strict mode** — plugins whose
   `supported_regions` includes `"india"` (or whose
   `supported_regions` is unset) are loaded with the existing
   permissive mode for back-compat.

4. **Explicit `promoted: true` opts in** — a plugin can force strict
   mode regardless of `supported_regions` by setting `promoted: true`.
   Useful for multi-region plugins (e.g., `supported_regions: ["india", "us"]`)
   that want strict-mode enforcement.

5. **Diagnostics endpoint** — `GET /api/v2/plugins/diagnostics`
   returns the per-broker plugin loader state (loaded /
   loaded_with_warnings / skipped) plus reason codes and missing /
   unknown field details.

## Consequences

* Adding a new operational capability requires updating
  `_OPTIONAL_PROMOTED_FIELDS` in `utils/plugin_loader.py` (or the
  `_V4_PROMOTED_REQUIRED_FIELDS` tuple if it's mandatory). Forces
  the addition to be a deliberate, reviewable change.
* Mock Schwab / Webull / Alpaca all pass strict mode (verified by
  the new strict-mode tests). Adding Alpaca's missing v4 required
  fields (`broker_code`, `account_context_supports`) was a one-line
  plugin.json edit.
* The `STRICT_CAPABILITY_INFERENCE` env flag can downgrade strict
  errors to warnings — same escape hatch as the Phase 1b
  completeness check. Off by default; on in production.

## Alternatives considered

* **Switch the JSON Schema to `additionalProperties: false` for all
  plugins.** Rejected: would break existing India plugins immediately;
  parity-breaking change.
* **Add a separate strict JSON Schema for promoted plugins.**
  Considered, but the strict-mode validator in `plugin_loader.py` is
  simpler to maintain (one source of truth for the allowed-keys set)
  and the JSON Schema validator is still used for type-shape checks.
* **Keep the current permissive mode and just add a runtime warning
  for unknown keys.** Rejected: warnings are lost; the silent-fail
  scenario this ADR addresses needs an active gate.

## Cross-references

* ADR 0008 — promoted-failclosed and account context (introduced the
  Phase 3 completeness check this ADR generalizes).
* ADR 0017 — runtime import lock + v1 schema legacy stamp.
* ADR 0023 — v4 scope.
