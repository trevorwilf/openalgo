# ADR 0017 — Promoted import lock + v1 schema legacy classification + frontend literal containment

Status: accepted (v3 Phase 1)
Date: 2026-04-25

## Context

Phase 0 of v3 produced the file classification (`PROMOTED_CORE` /
`LEGACY_INDIA` / `REGION_PLUGIN` / `BROKER_PLUGIN` /
`COMPATIBILITY_SHIM`) and the literal scanner extensions. That gave
the operator a readable map; this phase turns the map into runtime
gates so the boundary cannot silently rot.

Three concrete leak surfaces remained after Phase 0:

1. The v1 request schemas (`restx_api/schemas.py`,
   `restx_api/data_schemas.py`) and the legacy India vocabularies in
   `utils/constants.py` are used everywhere by the legacy lane but
   were not visibly stamped as legacy. A new contributor reading
   them couldn't tell whether they are "the schemas" or "the *legacy*
   schemas".
2. A PROMOTED_CORE file could pull in a forbidden legacy module
   transitively at import time without the static AST scanner
   noticing — e.g. a lazy module-level conditional or a side-effecting
   parent package.
3. The frontend's `LEGACY_FALLBACK_EXCHANGES = ['NSE','BSE','NFO',
   'BFO','CDS','MCX','CRYPTO']` literal lived in
   `frontend/src/hooks/useSupportedExchanges.ts` — a "promoted" hook
   that is otherwise capability-driven. The literal in promoted code
   is what the v3 prompt called out.

## Decision

### v1 schema legacy stamp

`restx_api/schemas.py`, `restx_api/data_schemas.py`, and
`utils/constants.py` each gain:

* a module docstring stating "LEGACY INDIA COMPATIBILITY" and that
  new code must not import from the module;
* a top-level constant `LEGACY_INDIA_COMPATIBILITY = True` so the
  classifier can detect the stamp programmatically.

`tests/contracts/test_v1_schemas_classification.py` enforces the
stamp and verifies that no PROMOTED_CORE file imports any of the
three modules at module load time. Behavior is unchanged — the legacy
India broker adapters keep working byte-identically.

### Runtime import lock

`tests/contracts/test_promoted_imports_runtime.py` imports each
PROMOTED_CORE module in a clean subprocess and inspects
`sys.modules` to confirm none of `utils.constants`,
`database.token_db`, `database.token_db_enhanced`, `database.symbol`,
`database.market_calendar_db`, `services.quotes_service`,
`services.history_service`, `services.place_order_service` were
pulled in transitively.

Two structural carve-outs are documented in
`RUNTIME_IMPORT_SKIP_PREFIXES`:

* `restx_api.v2.*` — importing any v2 leaf module forces the parent
  package `restx_api` (the v1 init) to load, which eagerly imports
  v1 namespaces and pulls in `utils.constants` etc. The static
  scanner is the meaningful guard for these files.

The runtime probe is a second layer — most leaks are caught by the
static AST scan in `test_lane_isolation.py`, but lazy module-level
imports inside conditionals only show up at runtime.

### Frontend literal containment

`LEGACY_FALLBACK_EXCHANGES` is moved out of the promoted hook into
`frontend/src/lib/india_legacy/legacy_fallback_exchanges.ts`. The
hook now imports it. The downstream behavior is bit-identical; only
the file the literal lives in changes.

A new `frontend/scripts/literal_scan.mjs` walks
`frontend/src/{hooks,components,lib,pages,api}/**/*.{ts,tsx}` and
fails on any India-specific literal listed in the same `INDIA_LITERALS`
set the backend uses (with `L`/`Cr` requiring a leading digit so
`P&L` does not trip). Files in
`frontend/scripts/literal_scan_allowlist.json` are exempt.

Phase 1 establishes the *containment perimeter*: every existing
India-specific UI surface is allowlisted with the reason
"India-specific UI surface (Phase 5 region-gating reduces this)".
Future code that adds an India literal in a non-allowlisted file
fails the scan. Phase 5 will narrow the allowlist as it region-gates
each surface.

The script is wired to `npm run lint:literals`.

### Capability completeness gate strengthening

`utils.plugin_loader._REQUIRED_NON_INDIA_PLUGIN_FIELDS` adds
`master_contract_refresh_policy` and `auth_modes`. A non-India
plugin missing either is now skipped at load time (or warned, when
`STRICT_CAPABILITY_INFERENCE=0`). The Alpaca plugin already
declared both implicitly via the operator-supplied defaults; this
phase makes the declaration mandatory and updates Alpaca's
`plugin.json` to include them explicitly.

## Consequences

* New contributors reading the v1 schemas immediately see "LEGACY
  INDIA COMPATIBILITY" and the contract that no PROMOTED_CORE file
  imports them. The runtime lock is a fail-fast safety net behind
  the static AST scan.
* Frontend authors get an immediate `npm run lint:literals` failure
  if they sneak a new India literal into a promoted/core file. The
  allowlist captures the existing reality and shrinks as Phase 5
  region-gates each India-specific surface.
* Future non-India broker plugins must declare
  `master_contract_refresh_policy` and `auth_modes`; no silent
  inference. The test suite covers the missing-field skip paths and
  the legacy-India exemption.
* `restx_api.v2.*` cannot be runtime-probed today because of the
  v1/v2 package nesting; this is documented and the static scanner
  carries the contract for those files. A future structural cleanup
  (out of scope for v3) could split v2 to its own top-level package
  to remove this caveat.
* No production behavior changes. Parity remains 7/7. Alpaca
  compliance harness still passes.

## Alternatives considered

* **Refactor `restx_api/__init__.py` to lazy-load v1 namespaces.**
  Rejected — would risk subtle parity drift in v1 routes and
  invalidate the existing parity baseline. The static scanner
  already covers the leak surface.
* **Use a JSON Schema "x-legacy-compat" extension instead of a
  Python sentinel constant.** Rejected — the schema validator is
  invoked per plugin.json, not per Python module; a Python sentinel
  is the right surface.
* **Expand the runtime-probe coverage to `restx_api.v2` by adding
  a parent-package shim.** Rejected — would couple the runtime
  probe to the package layout and obscure the structural reality.

## References

* `restx_api/schemas.py`, `restx_api/data_schemas.py`,
  `utils/constants.py` — legacy stamp
* `utils/plugin_loader.py` — strengthened completeness gate
* `frontend/src/lib/india_legacy/legacy_fallback_exchanges.ts` —
  contained literal
* `frontend/scripts/literal_scan.mjs` +
  `frontend/scripts/literal_scan_allowlist.json` — frontend scanner
* `tests/contracts/test_promoted_imports_runtime.py`
* `tests/contracts/test_v1_schemas_classification.py`
* `tests/plugin_loader/test_capability_completeness.py` — extended
* `frontend/src/hooks/useSupportedExchanges.literal.test.ts`
* ADR 0005 (two lanes), ADR 0006 (literal scanner), ADR 0008
  (fail-closed promoted lane), ADR 0016 (baseline + classification)
