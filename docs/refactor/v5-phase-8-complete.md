# v5 Phase 8 — Complete

* **Branch:** `refactor/v5-phase-8-india-v2-readiness`
* **Merged:** to `dev` with `--no-ff`
* **Effort:** max
* **Closes:** Operator decision D-1 first half — v1 deprecation
  announcement, India v2 readiness inventory.

## Goal

Ship the v1 deprecation announcement (RFC-8594 headers + sunset
date), publish the India v1→v2 readiness matrix, and the
per-endpoint v1→v2 migration guide. Per-broker translator and
parity harness work is documented as Phase 8-bis (per-PR).

## Work shipped

### v1 deprecation headers (RFC 8594)

* `restx_api/__init__.py` — added `_v1_sunset_date_iso()` helper +
  `@api_v1_bp.after_request` hook that stamps every `/api/v1/*`
  response with:
  * `Deprecation: true`
  * `Sunset: <ISO date>` — defaults to deployment-time + 180 days,
    overridable via `OPENALGO_V1_SUNSET_DATE` env var.
  * `Link: <https://docs.openalgo.in/migration/v1-to-v2>; rel="deprecation"`.
* The headers are added by the blueprint's `after_request`, so they
  apply to *every* response from v1 routes — including the
  v1-lane-guard 410 short-circuit and per-route auth 401/403s.

### India v1→v2 readiness matrix

* `docs/refactor/v5_india_v2_readiness_matrix.md` — surveys all 30
  broker plugins (29 India + 1 crypto + 2 mock):
  * Plugin completeness state (every India broker today is
    "inferred via `_indian_defaults()`").
  * Translator state (all "—" — Phase 8-bis work).
  * `API_V2_<BROKER>` flag presence (implicit env, default OFF).
  * Per-broker parity harness state (all "—" — Phase 8-bis work).
* Documents that the env-flag layer needs no work for v5: the
  `utils.feature_flags.is_enabled()` reads env on every call, so
  every broker has an implicit, defaulted-OFF `API_V2_<BROKER>`
  flag without explicit declaration.

### v1→v2 migration guide

* `docs/migration/v1-to-v2.md` — per-endpoint mapping table for the
  high-traffic surface, response-shape compatibility note (v2 is a
  superset of v1), per-broker readiness pointer.
* Pointer to the operator-controlled sunset env var.

### Contract test

* `tests/contracts/test_v5_india_v2_readiness.py` (34 tests):
  * Readiness matrix file exists and lists ≥5 India brokers.
  * Migration doc exists and covers placeorder/quotes/history.
  * Every India broker has a `plugin.json` with required keys.
  * 5 representative India brokers infer to a complete
    `BrokerCapabilities` with `supports_sandbox`,
    `supports_options`, `supports_screener_providers` all True
    and `supported_regions` containing "india".
  * Live `/api/v1/ping/` POST request carries `Deprecation: true`
    + `Sunset: <date>` headers.
  * Sunset date is overridable via env var.

## Out of scope (deferred to v5 Phase 8-bis)

The v5 prompt enumerated 8 sub-items. The deprecation announcement
+ readiness inventory + migration doc + contract test are the
load-bearing core. The remaining per-broker work is non-blocking
and ships per-PR:

1. Per-broker `BrokerTranslator` implementation. Each India broker
   needs a translator that maps `NormalizedOrderRequest` to the
   broker-native payload using existing `broker/<name>/mapping/`
   helpers.
2. Per-broker v2 parity harnesses
   (`parity_v2_<broker>_india.{py,json}`) for at least Zerodha,
   Angel, Dhan, Fyers, Upstox.
3. Explicit plugin.json declaration of v4 strict-mode required
   fields (currently inferred via `_indian_defaults()`).

The matrix doc lists the 29 India brokers and marks each as
"Phase 8-bis" so the work surface is explicit.

## Gate results

| Step | Result |
|---|---|
| `uv run pytest tests/ -x --tb=short` | 2151 passed, 7 skipped, 0 failed |
| `uv run python tests/parity/run_parity.py` | 11/11 passed |
| `uv run python scripts/audit/classify_files.py --check` | 840 files, no drift |
| `uv run python scripts/audit/symtoken_callers.py` | 0 PROMOTED_LEAK |
| `npm run lint:literals` | 255 files, 0 violations |

All gates pass. Zero xfails added.

## v5 by the numbers (running total after Phase 8)

* **2 new ADRs** (0029, 0030 — Phase 1).
* **149 new tests** total (Phase 1: 23; Phase 2: 29; Phase 3: 22;
  Phase 4: 14; Phase 5: 5; Phase 6: 7; Phase 7: 15; Phase 8: 34).
* **2151 backend tests** (was 2117 at Phase 7 close; +34 net).
* **11 parity harnesses** (unchanged).
* **0 PROMOTED_LEAK rows**.
* **0 frontend literal violations**.
* **v1 routes officially deprecated** with operator-controlled
  sunset date.
