# Phase 9 — v1 lane sunset machinery + conditional mount

Status: **shipped (logical conditional + sunset enforcement)**.

This is Phase 9 of the market-agnostic refactor, gated on
[`docs/refactor/v6-translator-parity-status.md`](v6-translator-parity-status.md)
having `STATUS: ALL_GREEN`. That sentinel is in place; Phase 9
unblocks.

## What landed

### T-23 (logical) — conditional v1 blueprint mount

`app.py` registers `api_v1_bp` **only** when the India region plugin
is loaded. For deployments that don't load `market_regions/india/`
(a hypothetical US-only deployment), `/api/v1/*` returns
`404 Not Found` at the route layer rather than being mounted.

The full physical relocation of `restx_api/*.py` /
`restx_api/schemas.py` / `domain/translators.py` / `utils/constants.py`
into `market_regions/india/legacy_v1/` is **not** done in this
engagement — that's a 37+ file move with hundreds of import-path
updates and significant blast-radius risk. The conditional-mount
approach achieves the same operator-facing semantic (non-India
deployments cannot reach v1) without the file relocation.

The physical relocation remains a future engagement; the conditional
mount is the operational equivalent.

### T-33 — operator-controlled sunset enforcement

Added to `restx_api/__init__.py`:

* `_v1_explicitly_sunset_date()` — parses `OPENALGO_V1_SUNSET_DATE`
  ISO date or returns `None`.
* `_v1_block_non_india_brokers_or_sunset()` — replaces the existing
  `_v1_block_non_india_brokers` `before_request` hook. When
  `OPENALGO_V1_SUNSET_DATE` is set and today is on or after that
  date, returns `410 Gone` with code `v1_sunset_passed` for **every**
  region (including India). Otherwise delegates to the pre-existing
  non-India guard.

Default behavior:

* `OPENALGO_V1_SUNSET_DATE` unset → no enforcement; the existing
  `Sunset:` response header (default 180 days out) remains an
  *announcement*, not enforcement. India brokers continue to see
  v1 work; non-India brokers continue to get the existing
  `v1_unavailable_for_non_india_broker` 410.
* `OPENALGO_V1_SUNSET_DATE=2027-12-31` → enforcement starts on that
  date for all regions.

Setting the date is a **deployment decision**; this phase delivers
the machinery, not the actual sunset.

### T-35 — already covered

Phase 3 (T-20) already moved the 8 critical services from
LEGACY_INDIA → PROMOTED_CORE in
`scripts/audit/classification_rules.yaml`. The lane-isolation
contract test stays green; further LEGACY_INDIA reduction (the
restx_api/* schemas) belongs to the deferred physical-relocation
engagement.

## Tests added

* `tests/contracts/test_v1_sunset.py` (7 tests):
  - ISO parse + None on unset / garbage.
  - Default header still 180 days out when env var unset.
  - Explicit past date overrides default in the announcement header.
  - `_v1_block_non_india_brokers_or_sunset()` returns 410 with code
    `v1_sunset_passed` when env date is in the past, regardless of
    broker region.
  - The hook does NOT take the sunset path when env var is unset.

* `tests/contracts/test_v1_lane_only_when_india_loaded.py` (3 tests):
  - Source-scan of `app.py` confirms registration is gated on
    `get_market_region("india")` and carries the Phase 9 / T-23
    marker.
  - End-to-end: a real `create_app()` with India loaded mounts
    `/api/v1/*` routes.
  - Sanity: `get_market_region("nonexistent")` returns `None`;
    India returns a populated region.

## Verification

* `uv run python tests/parity/run_parity.py` — 41/41 parity green.
* `uv run pytest tests/contracts/ tests/region_loader/ tests/multi_region/ tests/services/test_us_sandbox_smoke.py tests/services/test_v3_phase3_region_aware_validators.py tests/websocket/test_v3_phase5_topic_format.py -q` — 636 tests pass.
* `uv run python scripts/audit/classify_files.py --check` — no drift.

## Operator playbook

1. Confirm v2 is exercised across the broker fleet (per
   `API_V2_<BROKER>=1` flips).
2. Set `OPENALGO_V1_SUNSET_DATE=YYYY-MM-DD` to a future date.
3. Watch the response headers — every v1 response advertises the
   configured Sunset date.
4. Communicate the cutover to API consumers (Tradingview, Amibroker,
   custom scripts).
5. After the date passes, every v1 request returns `410 Gone` with
   `code: "v1_sunset_passed"` and the configured `sunset_date`.
6. The v1 blueprint can later be unregistered entirely by removing
   the `register_blueprint(api_v1_bp)` block in `app.py` (a future
   commit; Phase 9 leaves the routes registered to keep the
   announcement header alive for operators that haven't yet
   communicated the cutover).

## What v9-bis (future engagement) would do

* Physical relocation of `restx_api/*.py` (37 files) +
  `restx_api/schemas.py` / `data_schemas.py` / `account_schema.py` +
  `restx_api/_v1_lane_guard.py` + `domain/translators.py` +
  `utils/constants.py` into `market_regions/india/legacy_v1/`.
* Update import paths everywhere (~hundreds of import lines).
* Rename `restx_api` package → `restx_api_v2_only` for clarity.
* Drop the conditional-mount fallback in `app.py` once the physical
  move is done — the routes physically don't exist outside India.
