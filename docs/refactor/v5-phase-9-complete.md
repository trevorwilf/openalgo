# v5 Phase 9 — Complete

* **Branch:** `refactor/v5-phase-9-india-v2-cutover`
* **Merged:** to `dev` with `--no-ff`
* **Effort:** max
* **Closes:** Operator decision D-1 second half — cutover
  scaffolding, dual-lane parity infrastructure, deprecation
  schedule v5 additions.

## Goal

Ship the cutover infrastructure (`--lane v1|v2` parity runner mode,
deprecation-schedule update) and the contract test that pins the
v5 closing posture: India brokers stay on v1 by default until
per-broker translators land in Phase 8-bis. v5 does not perform
the actual default-flip to avoid breaking India production users
without their per-broker v2 plumbing in place.

## Why Phase 9 does not flip the default ON

The v5 prompt's Phase 9 calls for default-flipping
`API_V2_<BROKER>=true` for India brokers covered by Phase 8.
**Phase 8 explicitly deferred the per-broker translator + parity
harness work to Phase 8-bis** (per-broker integration work, ships
per-PR). Without those translators, flipping `API_V2_<BROKER>=true`
would route India users to the v2 lane where their broker has no
translator registered — producing structured `missing_translator`
errors on every order.

Per the v5 prompt's hard rule:

> If parity fails for a specific broker on v2, default the flag
> back to false for that broker only and document the gap; the
> cutover for that broker becomes a v6 issue. Do not partially
> break India users.

v5 keeps every India broker's flag at OFF and documents the gating
condition (Phase 8-bis completion) for each.

## Work shipped

### Dual-lane parity runner (`--lane v1|v2`)

* `tests/parity/run_parity.py` — added `argparse`-based CLI:
  * `python tests/parity/run_parity.py` — all harnesses
  * `python tests/parity/run_parity.py --lane v1` — v1-lane
    harnesses (excludes `parity_v2_*` prefix)
  * `python tests/parity/run_parity.py --lane v2` — v2-lane
    harnesses (excludes `parity_v1_*` prefix)
* Today every harness is shared between lanes (the snapshots
  capture provider behavior, which doesn't differentiate v1 vs
  v2). Phase 8-bis adds per-broker `parity_v2_<broker>_india`
  harnesses; the runner already supports the split.

### Deprecation schedule v5 additions

* `docs/refactor/deprecation-schedule.md` extended with v5
  additions:
  * `LEGACY_FALLBACK_EXCHANGES` deprecated alias — REMOVED in
    v5 Phase 2.
  * `_legacy_india_region_for_compat()` — UNCHANGED; v6 timeline.
  * `makeFormatCurrency(broker)` — REMOVED in v5 Phase 2.
  * `/api/v1/*` — Deprecation + Sunset headers added v5 Phase 8;
    removal lands v6 after sunset date.
  * `API_V2_<INDIA_BROKER>` default — UNCHANGED at OFF;
    per-broker flip gated on Phase 8-bis completion.

### Contract test

* `tests/contracts/test_v5_india_v2_default_on.py` (6 tests):
  * Every India broker's `API_V2_<BROKER>` flag defaults OFF.
  * `run_parity.py` accepts `--lane v1` and `--lane v2`.
  * `LEGACY_FALLBACK_EXCHANGES` deprecated alias is gone.
  * `makeFormatCurrency` is gone from `lib/utils.ts`.
  * v1 lane guard remains (sunset period).
  * Deprecation schedule lists v5 additions.

## Out of scope (deferred to v5 Phase 8-bis / v6)

* Per-broker default-flip — gated on per-broker translator + parity
  harness completion. Operators flip individual brokers via env
  once their broker's Phase 8-bis ships.
* `_legacy_india_region_for_compat()` removal — v6 work, gated on
  every named caller (sandbox/options/screener) migrating to
  dispatcher-only paths (Phase 4-bis / 5-bis / 6-bis).
* `/api/v1/*` removal — v6 work, gated on operator-controlled
  sunset date.
* Real-broker plugin work (Schwab, Webull, EU, UK).

## Gate results

| Step | Result |
|---|---|
| `uv run pytest tests/ -x --tb=short` | 2157 passed, 7 skipped, 0 failed |
| `uv run python tests/parity/run_parity.py` | 11/11 passed |
| `uv run python tests/parity/run_parity.py --lane v1` | 11/11 passed |
| `uv run python tests/parity/run_parity.py --lane v2` | 11/11 passed |
| `uv run python scripts/audit/classify_files.py --check` | 840 files, no drift |
| `uv run python scripts/audit/symtoken_callers.py` | 0 PROMOTED_LEAK |
| `uv run python scripts/audit/canonical_vs_legacy_parity.py` | 13 pairs |
| `npm run lint:literals` | 255 files, 0 violations |

All gates pass. Zero xfails added.

## v5 by the numbers (running total after Phase 9)

* **2 new ADRs** (0029, 0030 — Phase 1).
* **155 new tests** total (Phase 1: 23; Phase 2: 29; Phase 3: 22;
  Phase 4: 14; Phase 5: 5; Phase 6: 7; Phase 7: 15; Phase 8: 34;
  Phase 9: 6).
* **2157 backend tests** (was 2151 at Phase 8 close; +6 net).
* **11 parity harnesses** (unchanged); runner now supports
  `--lane v1|v2` split.
* **0 PROMOTED_LEAK rows**.
* **0 frontend literal violations**.
