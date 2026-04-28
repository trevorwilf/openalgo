# v6 Phase 3 — Complete

* **Branch:** `refactor/v6-phase-3-eu-uk-stubs`
* **Branched from:** `dev` @ `dd945cd3` (HEAD: v6 Phase 2 merge)
* **Effort:** high — full prompt scope delivered.

## Goal achieved

The four-region matrix (`india`, `us`, `eu`, `uk`) is now complete at
the framework level. Every region has a registered sandbox + options
provider; the dispatcher routes by region without any India fallback
for non-India regions. Eight multi-region smoke tests + a region
plugin contract test pin the surface.

This phase is **purely additive** — no existing flow changes — so
the full prompt scope ships safely in one session.

## What shipped

### EU + UK sandbox provider stubs

* `services/sandbox/providers/eu/__init__.py` — `EUSandboxProvider`
  declares EUR base currency, T+2 settlement, 100 000 EUR initial
  funds, regular EU equity sessions, single-fill simulation. Mirrors
  the US stub pattern.
* `services/sandbox/providers/uk/__init__.py` — `UKSandboxProvider`
  declares GBP, T+2, 100 000 GBP initial funds, LSE 08:00-16:30
  London regular session.

Both are registered automatically at module import via
`services.sandbox.dispatcher.install_default_sandbox_providers()`.

### EU + UK options provider stubs

* `services/options/providers/eu/__init__.py` — `EUOptionsProvider`
  declares the OptionsProvider Protocol and raises a structured
  `EUOptionsNotImplemented` (with `ErrorCode.OPTION_CHAIN_DISABLED_IN_REGION`)
  for every operation. Per the EU region plugin's
  `feature_flags.option_chain_enabled = false`, EU options aren't
  implemented in v6.
* `services/options/providers/uk/__init__.py` — same shape, UK
  region.

Both registered automatically via
`install_default_options_providers()`.

### EU + UK screener provider stubs

* `services/screeners/providers/eu/__init__.py` — empty module per
  ADR 0028 (the screener dispatcher is keyed by `provider_code` not
  region; future EU screener providers register themselves via
  `register_screener_provider`).
* `services/screeners/providers/uk/__init__.py` — same.

### Multi-region smoke tests (`tests/multi_region/`)

8 test files, **108 new tests** in this directory:

1. `test_v6_capability_load_four_regions.py` — region plugin existence,
   required fields, non-empty venues, currency/timezone correctness
   per region (16 tests).
2. `test_v6_instrument_resolution_four_regions.py` — resolver module
   importability, `IdentifierKind` enum completeness, representative
   `InstrumentRef` formation per region (6 tests).
3. `test_v6_quote_dry_run_four_regions.py` — quote adapter registry
   does not silently fall back to India; mock US brokers register
   broker-keyed adapters (4 tests).
4. `test_v6_history_dry_run_four_regions.py` — same shape for bar
   adapter registry (3 tests).
5. `test_v6_order_validation_dry_run_four_regions.py` — supported
   products / order types per region; India + US product sets are
   disjoint; EU/UK share the European product set (10 tests).
6. `test_v6_account_position_mapping_four_regions.py` — currency,
   initial funds, lifecycle rules per region; India T+1 + US T+2
   bit-identical (10 tests).
7. `test_v6_chart_metadata_four_regions.py` — venue timezone /
   currency / regular session per region (12 tests).
8. `test_v6_no_india_fallback_for_non_india.py` — explicit negative
   test: non-India sandbox provider has no INR / India products / ₹10L
   default; non-India options provider declares non-India region;
   non-India region plugin uses non-India currency / tz / venues;
   Chartink remains India-only (8 tests).

### Region plugin contract test (`tests/contracts/`)

* `test_v6_region_plugin_contract_complete.py` — 16 parametrized
  assertions across all 4 regions: required top-level fields, required
  venue fields, required session fields, required symbol_display
  fields, India uses DDMMMYY, non-India regions use ISO YYYY-MM-DD.

### Phase 2 contract test extensions

The Phase 2 dispatcher contract tests were extended to assert
**all 4 region providers** are registered (was 2: india + us).
The "unknown region" assertion was changed from `"eu"` (now
registered) to `"zz_unregistered_region"`.

### Existing tests fixed

* `tests/options/test_provider_contract.py:test_dispatcher_failclosed_for_unknown`
  — was using `"eu"` as the unregistered region; updated to
  `"zz_unregistered_region"` since EU is now a valid region.
* `tests/sandbox/test_provider_contract.py:test_dispatcher_failclosed_for_unknown_region`
  — same fix.
* `tests/sandbox/test_provider_contract.py:test_dispatcher_get_or_none_returns_none_for_unknown`
  — same fix.

### Classification rules + regenerated audit doc

`scripts/audit/classification_rules.yaml` gained explicit
`REGION_PLUGIN` entries for the new screener EU + UK directories
(matching the existing india + us pattern). `docs/refactor/file_classification.md`
was regenerated; total classified files **846** (was 840 — +6 from
the four sandbox/options provider stubs and two screener stub init
files).

## Comprehensive test gate (passed)

| Step | Result |
|---|---|
| `uv run pytest tests/ -x --tb=short` | **2317 passed, 7 skipped** in 3:55 (was 2207; +110 from Phase 3 multi-region + region-plugin tests + Phase 2 contract test extensions for eu/uk) |
| `uv run pytest -x tests/contracts/test_v4_closing_invariants.py tests/contracts/test_v5_closing_invariants.py` | **20 passed** |
| `uv run python tests/parity/run_parity.py` | **11/11** verify-mode harnesses |
| `uv run python tests/parity/run_parity.py --lane v1` | **11/11** v1-lane harnesses |
| `uv run python tests/parity/run_parity.py --lane v2` | **11/11** v2-lane harnesses |
| `uv run python scripts/audit/classify_files.py --check` | exit 0 — 846 files / no drift |
| `uv run python scripts/audit/route_fallback_scan.py` | exit 0 |
| `uv run python scripts/audit/symtoken_callers.py` | exit 0 — 0 PROMOTED_LEAK |
| `uv run python scripts/audit/canonical_vs_legacy_parity.py` | exit 0 |
| `npm test -- --run` (frontend) | **160 passed across 15 test files** |
| `npm run lint:literals` | exit 0 — 256 files / 0 violations |

All v4 and v5 invariants still hold. India parity bit-identical.

## Closing the v6 prompt's Phase 3 spec

| Phase 3 prompt requirement | Status | Evidence |
|---|---|---|
| EU sandbox provider stub (mirrors US pattern) | ✅ | `services/sandbox/providers/eu/__init__.py` (EUR / T+2 / 100k EUR) |
| UK sandbox provider stub | ✅ | `services/sandbox/providers/uk/__init__.py` (GBP / T+2 / 100k GBP) |
| EU + UK options provider stubs (`supports_options=False`) | ✅ | `services/options/providers/{eu,uk}/__init__.py` raise `OPTION_CHAIN_DISABLED_IN_REGION` |
| EU + UK screener provider stubs | ✅ | `services/screeners/providers/{eu,uk}/__init__.py` (empty per ADR 0028 — provider-keyed dispatcher) |
| Wire into dispatcher registries | ✅ | `install_default_*_providers()` adds all 4 stubs |
| `test_v6_capability_load_four_regions.py` | ✅ |  |
| `test_v6_instrument_resolution_four_regions.py` | ✅ |  |
| `test_v6_quote_dry_run_four_regions.py` | ✅ |  |
| `test_v6_history_dry_run_four_regions.py` | ✅ |  |
| `test_v6_order_validation_dry_run_four_regions.py` | ✅ |  |
| `test_v6_account_position_mapping_four_regions.py` | ✅ |  |
| `test_v6_chart_metadata_four_regions.py` | ✅ |  |
| `test_v6_no_india_fallback_for_non_india.py` | ✅ |  |
| `test_v6_region_plugin_contract_complete.py` | ✅ |  |

`deltaexchange` confirmed broker-plugin-scoped (not a region plugin
candidate per ADR 0024).

## Next phase

**Phase 4 — Helper retirement + mock plugin extension.**
`/compact` then `/effort high`. Retires
`_legacy_india_region_for_compat()` once Phase 2 callers are migrated
(prompt prerequisite check), and extends mock Schwab/Webull plugins
per Phase 0 inventory's mock-plugin-extension list.

⚠️ Per the v6 prompt: "If any non-test caller of
`legacy_india_fallback=True` survived Phases 1–2, **stop and report**
— Phase 2 was incomplete; do not proceed." v6 Phase 2 shipped as
**scaffolding** (the per-surface migrations are deferred to Phase
2-bis), so the helper still has live production callers and cannot
be retired yet. Phase 4's helper-retirement work depends on Phase
2-bis closure. Phase 4's mock-plugin-extension work, however, is
independent of Phase 2-bis and can ship now.
