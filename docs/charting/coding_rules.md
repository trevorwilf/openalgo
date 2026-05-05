# Charting coding rules

Forbidden patterns inside `frontend/src/charts/*` and the matching
backend `services/charts/*`. The lint pass at
`frontend/scripts/literal_scan.mjs` enforces frontend literals; the
lane-isolation contract test enforces the import bans on the Python
side.

## Frontend (`frontend/src/charts/*`)

Forbidden:

| Pattern | Why |
|---|---|
| `5.5 * 60 * 60 * 1000` | Hardcoded IST offset. The chart workspace is region-agnostic; tz comes from `useVenueTimezone` / `useRegionCapabilities`. |
| `'Asia/Kolkata'` / `'IST'` | Same — venue-aware tz, not a literal. |
| `'NSE'` / `'BSE'` / `'NFO'` / `'BFO'` / `'MCX'` / `'CDS'` / `'BCD'` | Hardcoded India venue codes. Use `BrokerCapabilities.supported_venue_codes`. |
| `'NIFTY'` / `'BANKNIFTY'` / `'SENSEX'` | Default-symbol literal. Pull from `BrokerCapabilities`. |
| Lot-size maps | Use `SymToken.lotsize` (legacy) or the broker's instrument metadata (new). |
| `import … from '@/india_legacy/…'` | Cross-tree leak. The new chart code is region-agnostic and the legacy lane is frozen. |
| `import … from '@/charts/engine/lightweight/…'` from outside `loader.ts` / `base.ts` | P-02 — components mount engines via the loader. |
| `import … from '@/charts/engine/klinechart/…'` from outside the loader | Same. |
| `import … from '@/charts/engine/tradingview/…'` from outside the loader | Same. |
| Static `import 'lightweight-charts'` from outside `LightweightAdapter.ts` | The static bundle stays clean even when only one engine is used. |

Allowed alternatives:

* Venue / timezone: `useRegionCapabilities()` + `useVenueTimezone()`.
* Default symbol: `BrokerCapabilities.default_symbol` (Phase 7 will
  thread it through the workspace store seed).
* Engine selection: `loader.loadEngine(engineId)` from `frontend/src/charts/engine/loader.ts`.
* Drawing primitives: the engine-agnostic `DrawingShape` from
  `frontend/src/charts/engine/drawings_translator.ts`.

## Backend (`services/charts/*`, `restx_api/v2/chart*`)

The promoted-lane import allowlist + India-literal scanner from the
v3 refactor (CLAUDE.md "Promoted lane") still applies. Specific to
the chart workspace:

| Pattern | Why |
|---|---|
| `Asia/Kolkata` / `IST` literal | Same as frontend — venue-aware tz. |
| `import services.history_service.get_history_with_auth` | Legacy India history path; new code uses `services/charts/bar_resampler.py` + `restx_api.v2.bars`. |
| `import services.quotes_service.get_quotes_with_auth` | Same — use `restx_api.v2.quotes`. |
| `import database.token_db.get_token` | Promoted code reads instruments via `database/instruments_repo.py`. |
| `from utils.constants import VALID_EXCHANGES / VALID_PRODUCT_TYPES / VALID_PRICE_TYPES` | Legacy India constants. New code uses domain enums from Phase 1a. |

## Two-tree separation (Phase 6 P-04)

* `frontend/src/charts/display/*` (read-only path — orders, positions,
  fills, strategy markers) and `frontend/src/charts/execution/*`
  (write-mediated path — order entry, modify, cancel) share **no**
  mutable state. They communicate only via domain events and order ID.
* The contract test `tests/contracts/test_display_execution_separation.py`
  asserts neither tree imports from the other (static-source check).

## Two-step order entry (Phase 6 P-10)

Every chart-originated order intent goes through the safety harness:

* Two-step confirmation modal (panel → confirm). Enter does NOT
  auto-confirm. ESC cancels.
* Idempotency token issued at panel-open, reused through confirm.
* Pre-trade validator (`services/charts/pre_trade_validator.py`) runs
  client-side AND server-side (defense in depth).
* Audit row appended to `audit_log_chart_orders` for every intent
  (placed / cancelled / rejected-by-validator / rejected-by-broker /
  executed). DELETE blocked at the DB level.

There is no "skip confirmation" mode for place/cancel. Modify-confirm
is opt-in and OFF by default.

## When introducing a new file under `frontend/src/charts/*` or `services/charts/*`

1. Run `npm run lint:literals` (frontend) — the scanner walks
   `frontend/src/charts/*` and rejects any India literal.
2. Run `uv run python scripts/audit/classify_files.py --check`
   (backend) — the classifier asserts every `services/charts/*` and
   `restx_api/v2/chart/*` file is `PROMOTED_CORE`.
3. Run `python tests/parity/run_parity.py` — the legacy India parity
   baseline must remain green at every phase boundary.
