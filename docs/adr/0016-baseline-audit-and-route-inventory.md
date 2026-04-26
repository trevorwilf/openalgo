# ADR 0016 — Baseline audit, route fallback inventory, file classification

Status: accepted (v3 Phase 0)
Date: 2026-04-25

## Context

Two prior prompts (`market-agnostic-phases_Claude_code.md` and
`openalgo_market_agnostic_v2_claude_code_prompt.md`) landed substantial
v2-lane scaffolding, region-plugin schema v2, fail-closed promoted
order dispatch, capability-driven UI, and the broker compliance
harness. Two independent expert reviews after that work converged on
the same conclusion: the boundary is *almost* sealed but several
specific leaks remain — most importantly, v2 quotes/bars still fall
back to the legacy India market-data services, the canonical resolver
isn't enforced for non-India brokers, several India-shaped service-layer
defaults aren't gated, and there is no operator-readable inventory of
which routes route through which lane.

The operator cannot reason about safe-to-change without three artifacts
that don't exist today:

1. A **route fallback inventory** that maps every `/api/v1/*` and
   `/api/v2/*` route to its lane disposition, legacy-fallback calls,
   capability check status, instrument resolution mode, and the v3
   phase that closes the open behavior.
2. A **file classification document** that assigns every Python source
   file to exactly one of `PROMOTED_CORE`, `LEGACY_INDIA`,
   `REGION_PLUGIN`, `BROKER_PLUGIN`, `COMPATIBILITY_SHIM`. This is the
   contract the literal scanner and import-lock tests run against.
3. A **baseline audit** that cross-checks v1/v2 deliverables against
   the current repo and lists every confirmed gap with the v3 phase
   that closes it.

## Decision

Phase 0 of v3 produces these three artifacts and the supporting
machinery.

### Route fallback inventory

`scripts/audit/route_fallback_scan.py` walks `restx_api/__init__.py`
and `restx_api/v2/__init__.py` to discover every registered Namespace,
then AST-scans each route module to detect:

* legacy service imports (the leak surface),
* legacy DB imports (`utils.constants`, `database.token_db`,
  `database.token_db_enhanced`, `database.symbol`,
  `database.market_calendar_db`),
* capability-check sentinels and fail-closed sentinels,
* canonical-resolver hints (`services.instrument_resolution`,
  `database.instruments_repo`).

Output: `docs/refactor/route_fallback_inventory.md`.
`tests/contracts/test_route_fallback_inventory.py` enforces that every
promoted route is either fail-closed for non-India OR declares an
owning v3 phase, and that no legacy v1 route mistakenly carries
`fail_closed_non_india=yes`.

### File classification

`scripts/audit/classify_files.py` reads
`scripts/audit/classification_rules.yaml` — a path-prefix match-first
rule list — and assigns every classifiable Python file to a bucket.
The classifier exposes a `--check` mode (and an in-process equivalent)
that exits non-zero on drift. Drift means a file moved or got renamed
without a corresponding rules update.

Output: `docs/refactor/file_classification.md`.
`tests/contracts/test_classification_invariants.py` enforces that
every classified file exists, no file is in two buckets, and the
classifier reports zero drift.

### Literal scanner hardening

`tests/contracts/test_lane_isolation.py` is extended:

* `INDIA_LITERALS` adds `BCD`, `NSE_INDEX`, `BSE_INDEX`, `lakh`,
  `crore`, `Cr`, `L`. The word-boundary regex is tightened to also
  exclude a leading `.` so attribute access like `Currency.INR` does
  not trip the scanner.
* `_string_constants_in_module` now skips enum-self-assign patterns
  (`NAME = "NAME"`).
* `_literal_violations_in_file` now skips multi-line docstring spans
  in the regex pass, and the same enum-self-assign lines.
* New test
  `test_no_india_literals_in_classified_promoted_files` reads the
  classification report and runs the scanner across every
  `PROMOTED_CORE` file (a stricter check than the existing scanner
  which only walks `restx_api/v2/` and PROMOTED-sentinel broker dirs).
* New test
  `test_classified_promoted_files_have_no_forbidden_imports` enforces
  a HARD ban on imports of `utils.constants`, `database.token_db*`,
  `database.symbol`, `database.market_calendar_db`,
  `services.quotes_service`, `services.history_service`,
  `services.place_order_service`, `services.basket_order_service`,
  `services.split_order_service`, `domain.translators` from any
  classified `PROMOTED_CORE` file. The named compatibility shims
  live in `COMPATIBILITY_SHIM` and are exempt by classification.

### Baseline audit document

`docs/refactor/v3_baseline_audit.md` cross-references each prior-prompt
deliverable against the current repo, lists every gap with a
`CONFIRMED` / `PARTIAL` / `FIXED-SINCE` status and the owning v3 phase.
This is the operator's reference for the rest of the v3 prompt.

## Consequences

* Boundary enforcement now keys off the file classification, not
  ad-hoc directory globs. New files get classified explicitly; the
  drift check ensures the classification can't silently rot.
* The route inventory makes the lane disposition of every endpoint
  visible. Future phases that close a leak update the inventory
  automatically (the scanner is rerun) and the
  `owning_phase_to_fix` column shrinks accordingly.
* The literal scanner is now safe to run over genuinely region-neutral
  domain models (e.g. `domain/currency.py`'s `Currency` enum, which
  legitimately includes `INR`). Pre-existing false positives on enum
  self-assigns and docstring content are eliminated.
* No production behavior changes in this phase. Parity must remain
  bit-identical.

## Alternatives considered

* **Skip classification, walk hardcoded directory roots.** Rejected —
  the existing approach (PROMOTED_PATH_ROOTS = `restx_api/v2/`) misses
  domain primitives and forces the literal scanner to lag behind code
  movement. Classification makes drift detectable.
* **Generate the route inventory at runtime via Flask's `app.url_map`.**
  Rejected — runtime discovery requires booting the app with all
  blueprints, which couples the audit to the full import graph. The
  AST scan is independent and fast.
* **Use a lint plugin instead of pytest contracts.** Rejected —
  pytest is the existing contract surface; adding a separate linter
  would fragment the operator's "is the boundary still sealed?"
  question across two tools.

## References

* `docs/refactor/v3_baseline_audit.md`
* `docs/refactor/route_fallback_inventory.md`
* `docs/refactor/file_classification.md`
* `scripts/audit/classify_files.py`
* `scripts/audit/route_fallback_scan.py`
* `scripts/audit/classification_rules.yaml`
* `tests/contracts/test_lane_isolation.py`
* `tests/contracts/test_classification_invariants.py`
* `tests/contracts/test_route_fallback_inventory.py`
* ADR 0005 (two lanes), ADR 0006 (literal scanner)
