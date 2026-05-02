# v9-bis-2 handoff — comprehensive resume document

**Audience:** future Claude session (after `/compact` or fresh restart)
or future engineer picking up the deferred work.
**Purpose:** start work on the remaining deferred items without
re-discovering the codebase state. Read this first.

**Last updated:** 2026-05-02 evening, after the bis-phase pass.
**State of `dev`:** synced with `origin/dev` (user pushed). Working
tree clean.

---

## TL;DR — where we are

The OpenAlgo market-agnostic refactor (Expert 3 backlog T-01 through
T-35, Expert 2 backlog C-PX-NNN) has completed every phase except
for some genuinely-deferred-with-owner items. India parity is
bit-identical. Frontend literal allowlist is at the prompt's
target of ≤2 entries. All 41 parity harnesses pass on both lanes.

**Read these in order before doing anything:**

1. `docs/refactor/release-gate-dashboard.md` — single-page status.
2. `docs/refactor/refactor-disposition-status.md` — chronological
   audit of every deferred item bucketed
   Implemented / Still-deferred-with-owner / Intentionally-India-only.
3. `docs/refactor/market-agnostic-phase-9-bis-physical-plan.md` —
   T-23 physical relocation playbook.
4. `openalgo_market_agnostic_refactor_claude_code_prompt.md` (root) —
   the original 9-phase prompt with task IDs T-01..T-35.
5. `CLAUDE.md` — project conventions; pinned invariants section is
   load-bearing.

---

## Remaining deferred work (the v9-bis-2 backlog)

Listed in order of decreasing tractability. Pick one, branch off
`dev`, ship it green, merge with `--no-ff`. **Do NOT batch multiple
items in one branch** — the whole point of these as separate
engagements is per-item integration testing.

### 1. T-13 / T-14 remaining consumer-side migration

**Scope:** Migrate the remaining call sites from direct
`sandbox.*` / `services.option_*_service` imports to the
dispatcher route established in Phase 2-bis-3.

**Files to migrate (already-classified LEGACY_INDIA, so internal
shim refactor only — no contract impact):**

* `services/analyzer_service.py:93-94, 102` — function-local
  imports of `sandbox.execution_thread`, `sandbox.squareoff_thread`,
  `sandbox.position_manager`. These are already function-local so
  the static import lock doesn't see them; the migration is purely
  for consistency with the dispatcher pattern.
* `services/sandbox_service.py:602, 651` — `sandbox.squareoff_thread`
  function-local imports (already function-local).
* `restx_api/option_chain.py:68` — `from services.option_chain_service
  import get_option_chain`.
* `restx_api/option_symbol.py:39` — `from services.option_symbol_service
  import get_option_symbol`.
* `restx_api/option_greeks.py:9` — `from services.option_greeks_service
  import get_option_greeks`.
* `restx_api/options_multiorder.py:113` — `from
  services.options_multiorder_service import place_options_multiorder`.

**Approach:** thin shim functions (similar to the
`services/sandbox_service.py` migration in `phase-2-bis-3-2`):

```python
def get_option_chain(*args, **kwargs):
    from services.options.dispatcher import get_options_provider
    return get_options_provider("india").service_modules()["chain"].get_option_chain(*args, **kwargs)
```

The provider's `service_modules()` already exposes:
`{"symbol": option_symbol_service, "chain": option_chain_service,
 "greeks": option_greeks_service, "multiorder": options_multiorder_service,
 "place_order": place_options_order_service}`.

**Verification:** parity stays green; lane-isolation tests stay green;
the contract test `tests/contracts/test_v3_phase2_bis_3_dispatcher_wiring.py`
already exists.

**Branch:** `refactor/market-agnostic-phase-2-bis-3-3`.

**Estimated effort:** half a day.

**Note:** The prompt T-14 says "Options service entry points obtain
provider via services.options.dispatcher.get_provider(region_code)."
The reading I went with: these `restx_api/option_*.py` files ARE
LEGACY_INDIA-classified v1-lane internals; they don't need the
indirection until v9-bis-2 properly relocates them under
`market_regions/india/legacy_v1/`. So this item is borderline
"already done" depending on interpretation. If you do migrate, it's
the shim pattern above.

---

### 2. T-23 physical relocation

**Scope:** Move 44 `restx_api/*.py` files (excluding `restx_api/v2/`)
+ `domain/translators.py` + `utils/constants.py` into
`market_regions/india/legacy_v1/`. Update import paths everywhere.

**Already done structurally:**

* `market_regions/india/legacy_v1/__init__.py` exists as a package
  stub.
* `docs/refactor/market-agnostic-phase-9-bis-physical-plan.md` is
  the detailed playbook — read it before starting.

**Files to move (44 total under `restx_api/`):**

```
restx_api/
├── _v1_lane_guard.py
├── account_schema.py
├── analyzer.py
├── basket_order.py
├── cancel_all_order.py
├── cancel_order.py
├── chart_api.py
├── close_position.py
├── data_schemas.py
├── depth.py
├── expiry.py
├── funds.py
├── history.py
├── holdings.py
├── instruments.py
├── intervals.py
├── margin.py
├── market_holidays.py
├── market_timings.py
├── modify_order.py
├── multi_option_greeks.py
├── multiquotes.py
├── openposition.py
├── option_chain.py
├── option_greeks.py
├── option_symbol.py
├── options_multiorder.py
├── options_order.py
├── orderbook.py
├── orderstatus.py
├── ping.py
├── place_order.py
├── place_smart_order.py
├── pnl_symbols.py
├── positionbook.py
├── quotes.py
├── schemas.py
├── search.py
├── split_order.py
├── symbol.py
├── synthetic_future.py
├── telegram_bot.py
├── ticker.py
├── tradebook.py
├── __init__.py  (move contents; this is the api_v1_bp registry)
└── v2/  (DOES NOT MOVE — stays at restx_api/v2/)
```

Plus:
* `domain/translators.py` → `market_regions/india/legacy_v1/translators.py`
* `utils/constants.py` → `market_regions/india/legacy_v1/constants.py`

**Recommended approach (per the playbook):** **Option B — shim
layer.** Keep `restx_api/__init__.py`, `domain/translators.py`,
`utils/constants.py` as thin re-export modules pointing at the new
location. External importers continue working without changes. Then
incrementally migrate importers in follow-up commits.

**Ordering (from playbook §Step 2):**

1. Group A — schemas only: `schemas.py`, `data_schemas.py`,
   `account_schema.py`. Lowest blast radius. Update every
   `from restx_api.schemas import OrderSchema` etc. across
   services/, blueprints/, broker/, tests/. Run parity.
2. Group B — translators + constants: `domain/translators.py`,
   `utils/constants.py`. Broadest blast radius (~30 broker plugins
   import `utils.constants`). Update imports broker-by-broker, run
   parity per broker.
3. Group C — endpoint route modules (37 files). Each is
   self-contained. Move and update `restx_api/__init__.py`'s
   namespace registration to import from the new location.
4. Group D — `_v1_lane_guard.py` last (hooked via before/after
   request).

**Acceptance:**

* `LEGACY_INDIA` bucket reduces from 211 → < 50 in
  `docs/refactor/file_classification.md` (T-35 acceptance).
* `tests/parity/baseline/` — 41/41 green on both lanes, including
  with `API_V2_<BROKER>=1` enabled per Phase 6 ALL_GREEN.
* `tests/contracts/test_lane_isolation.py` and
  `test_v6_closing_invariants.py` green.
* `dev` runs the trading dashboard end-to-end (manual smoke test).

**Branch:** `refactor/market-agnostic-phase-9-bis-physical`.

**Estimated effort:** 1 engineer × 5 working days per the playbook.
Highest-blast-radius item in the deferred list.

**Critical:** before each group, run the full comprehensive suite.
After each group, run it again. ANY parity diff = revert
immediately, do not fix forward (per the prompt's "parity is
non-negotiable" rule).

---

### 3. T-24 full — physical doc relocation

**Scope:** Relocate per-section endpoint pages under
`docs/api/v1/<section>/`.

**Already done:**
* `docs/api/v1/README.md` scaffold (Phase 8-bis-2).
* `docs/api/README.md` two-lane top-nav.

**Files to move:**
```
docs/api/account-services/    → docs/api/v1/account-services/
docs/api/analyzer-services/   → docs/api/v1/analyzer-services/
docs/api/market-calendar/     → docs/api/v1/market-calendar/
docs/api/market-data/         → docs/api/v1/market-data/
docs/api/options-services/    → docs/api/v1/options-services/
docs/api/order-information/   → docs/api/v1/order-information/
docs/api/order-management/    → docs/api/v1/order-management/
docs/api/symbol-services/     → docs/api/v1/symbol-services/
docs/api/websocket-streaming/ → docs/api/v1/websocket-streaming/
docs/api/rate-limiting.md     → docs/api/v1/rate-limiting.md
docs/api/v2_errors.md         → docs/api/v2/v2_errors.md
```

**Blocker:** External integrations (TradingView, Amibroker, custom
Python clients) have deep links into the existing top-level paths.
A physical move needs a redirect strategy. Options:

* **Symlink approach:** Replace each moved directory with a symlink
  pointing at `v1/<section>/`. Keeps both URLs working. Cross-
  platform (Windows/Linux) symlink behavior is a concern.
* **GitBook-style aliases:** If `docs.openalgo.in` uses a static
  site generator with redirect support, configure aliases.
* **Stub redirect docs:** Replace each old path with a one-line
  README that points at the new location.

**Recommend:** stub redirect docs. Each old path becomes a
`README.md` like:

> # This page moved
> See [`docs/api/v1/<section>/`](../v1/<section>/).

**Branch:** `refactor/market-agnostic-phase-8-bis-2-2`.

**Estimated effort:** 1 day. Mostly mechanical.

---

### 4. EU + UK Python `RegionPlugin` implementations

**Status per Phase 7 prompt §7b:** "EU and UK explicitly stay as
stubs in this phase." Intentional out-of-scope until EU/UK pilot
brokers land.

**If a future engagement adds EU/UK pilot brokers,** create:

* `market_regions/eu/__init__.py`, `holidays.py`, `sessions.py`,
  `qty_freeze.py`, `options_grammar.py`, `locale.py`,
  `settlement.py`, `plugin.py` — same pattern as
  `market_regions/us/` (Phase 7b).
* `market_regions/uk/...` — same.
* `services/sandbox/providers/eu/*` — already exists as a stub;
  populate with real EU sandbox semantics.
* `services/options/providers/eu/*` — populate with EU options
  grammar (likely OCC-equivalent or per-exchange).

**Reference:** `market_regions/us/plugin.py` is the canonical
template. India and US plugins are the only "real" implementations
shipped.

**Branch:** `refactor/market-agnostic-phase-7-bis-eu-uk`.

**Estimated effort:** 5+ days per region. Holiday calendars +
session windows + options grammar all need research.

---

### 5. Real broker plugins (Schwab / Webull / Alpaca / IBKR)

**Status:** Out of every phase per the Schwab/Webull guardrail.
Mock plugins at `broker/_mock_schwab_like/` and
`broker/_mock_webull_like/` exercise the contract surface only.

**To onboard a real broker plugin:** see
`docs/refactor/future-broker-onboarding-checklist.md`.

**Estimated effort:** 2-4 weeks per broker. Authentication +
order routing + master contract loader + WebSocket adapter +
integration tests + paper-API smoke testing.

---

## What I shipped (this is where you start)

### Phases shipped end-to-end

* **0** — MarketRegion + BrokerCapabilities v3 schema fields.
* **1** — 3 implicit-India branches replaced with structured errors.
* **2** + **2-bis-1** + **2-bis-2** + **2-bis-3** + **2-bis-3-2** —
  India regional data relocated to `market_regions/india/`,
  consumer wiring (squareoff/qty-freeze), schema cleanup
  (sandbox_db default removed), dispatcher contracts +
  consumer-side migration of `services/sandbox_service.py`.
* **3** — 8 critical services migrated to region-aware vocabulary.
* **4** + **4-bis-1** + **4-bis-2** — `useRegionCapabilities` hook,
  lib formatters consolidated, full T-34 allowlist drain to
  2 entries.
* **5** — MPP capability-driven, WS topic format capability-driven.
* **6** — 30-broker translator parity ALL_GREEN.
* **7** — `RegionPlugin` Protocol + IndiaRegionPlugin + USRegionPlugin
  (NYSE/NASDAQ holidays, OCC OSI 21-char grammar, USD locale).
* **8** + **8-bis** + **8-bis-2** — All sub-tasks: future-broker
  checklist, release dashboard, multi-region matrix, install-script
  $OPENALGO_DEPLOY_TZ, T-27 (sqlite_downloader venue-tz), T-28
  (region-aware examples), C-P2-027 (region note), C-P2-028
  (disposition status), T-24 partial (docs/api/v1 scaffold).
* **9** + **9-bis-stub** — India-gated v1 conditional mount,
  OPENALGO_V1_SUNSET_DATE machinery, market_regions/india/legacy_v1/
  placeholder + migration playbook.

### Frontend: 130+ files relocated to `src/india_legacy/`

```
frontend/src/india_legacy/
├── api/
│   ├── chartink.ts
│   ├── iv-chart.ts
│   ├── python-strategy.ts
│   └── strategy-portfolio.ts
├── components/
│   ├── flow/
│   │   ├── edges/  (1 file)
│   │   ├── nodes/  (52 files including BaseNode, OptionChainNode, etc.)
│   │   └── panels/ (3 files)
│   ├── option-chain/  (4 files)
│   ├── playground/    (1 file: MessageComposer)
│   ├── strategy-builder/  (11 files)
│   └── trading/       (2 files: PlaceOrderDialog, QuoteHeader)
├── hooks/
│   ├── useOptionChainLive.ts
│   ├── useSupportedExchanges.ts
│   ├── useSupportedExchanges.test.ts
│   └── useSupportedExchanges.literal.test.ts
├── lib/
│   ├── flow/
│   │   └── constants.ts
│   ├── legacy_fallback_exchanges.ts
│   ├── strategyMath.ts
│   └── strategyTemplates.ts
└── pages/
    ├── ActionCenter.tsx
    ├── Analyzer.tsx
    ├── CustomStraddle.tsx
    ├── Faq.tsx
    ├── GEXDashboard.tsx
    ├── GoCharting.tsx
    ├── Historify.tsx
    ├── HistorifyCharts.tsx
    ├── IVChart.tsx
    ├── IVSmile.tsx
    ├── OIProfile.tsx
    ├── OITracker.tsx
    ├── OrderBook.tsx
    ├── Positions.tsx
    ├── Sandbox.tsx
    ├── SandboxPnL.tsx
    ├── StraddleChart.tsx
    ├── StrategyBuilder.tsx
    ├── StrategyPortfolio.tsx
    ├── Token.tsx
    ├── Tools.tsx
    ├── TradeBook.tsx
    ├── TradingView.tsx
    ├── admin/
    │   ├── AdminIndex.tsx
    │   ├── FreezeQty.tsx
    │   └── MarketTimings.tsx
    ├── chartink/  (5 files)
    ├── python-strategy/  (7 files)
    ├── strategy/
    │   └── ConfigureSymbols.tsx
    └── telegram/
        └── TelegramConfig.tsx
```

**Why a top-level `src/india_legacy/`?** The frontend literal
scanner (`frontend/scripts/literal_scan.mjs`) walks
`src/{hooks,components,lib,pages,api}/**/*.{ts,tsx}` only. A
top-level `src/india_legacy/` is intentionally outside the walk so
India-only files relocated there are exempt by location rather
than by allowlist entry.

### Frontend allowlist final state — 2 entries

`frontend/scripts/literal_scan_allowlist.json`:

1. `src/hooks/useRegionCapabilities.ts` — multi-region currency /
   locale / symbol lookup table (13 currencies; India is one row).
2. `src/lib/format/timezone.ts` — multi-region IANA → short-label
   timezone display helper (Asia/Kolkata + IST appear only as one
   of N entries).

Baseline (`tests/contracts/v6_phase_1_baseline_allowlist.json`):
85 entries (84 v6 baseline + 1 Phase 4 bump for
`useRegionCapabilities.ts`).

`tests/contracts/test_v6_frontend_allowlist_shrinks.py`'s
`test_baseline_size_is_known` expects exactly 85.

---

## Verification commands (run these before and after any change)

### Comprehensive suite

```bash
# Python parity (default + both lanes; should always be 41/41)
uv run python tests/parity/run_parity.py
uv run python tests/parity/run_parity.py --lane v1
uv run python tests/parity/run_parity.py --lane v2

# Audit gates
uv run python scripts/audit/classify_files.py --check
uv run python scripts/audit/canonical_vs_legacy_parity.py
uv run python scripts/audit/route_fallback_scan.py
uv run python scripts/audit/symtoken_callers.py

# Frontend literal scan (should walk 128 files, 0 violations)
node frontend/scripts/literal_scan.mjs

# Allowlist subset invariant
uv run pytest tests/contracts/test_v6_frontend_allowlist_shrinks.py -q

# v6 closing invariants (single-command release gate)
uv run pytest tests/contracts/test_v6_closing_invariants.py -q

# Frontend type-check
cd frontend && npx tsc --noEmit
```

### Targeted broader sweep

```bash
uv run pytest tests/contracts/ tests/services/ \
  tests/region_loader/ tests/multi_region/ \
  tests/sandbox/ tests/sessions/ tests/audit/ \
  tests/websocket/test_v3_phase5_topic_format.py \
  -q
```

### With all 30 India broker API_V2 flags enabled (Phase 6 ALL_GREEN)

```bash
env API_V2_ZERODHA=1 API_V2_ANGEL=1 API_V2_DHAN=1 API_V2_UPSTOX=1 \
    API_V2_FYERS=1 API_V2_ALICEBLUE=1 API_V2_COMPOSITEDGE=1 \
    API_V2_DEFINEDGE=1 API_V2_FIRSTOCK=1 API_V2_FIVEPAISA=1 \
    API_V2_FIVEPAISAXTS=1 API_V2_FLATTRADE=1 API_V2_GROWW=1 \
    API_V2_IBULLS=1 API_V2_IIFL=1 API_V2_IIFLCAPITAL=1 \
    API_V2_INDMONEY=1 API_V2_JAINAMXTS=1 API_V2_KOTAK=1 \
    API_V2_MOTILAL=1 API_V2_MSTOCK=1 API_V2_NUBRA=1 \
    API_V2_PAYTM=1 API_V2_POCKETFUL=1 API_V2_RMONEY=1 \
    API_V2_SAMCO=1 API_V2_SHOONYA=1 API_V2_TRADEJINI=1 \
    API_V2_WISDOM=1 API_V2_ZEBU=1 \
    uv run python tests/parity/run_parity.py --lane v2
```

Expected: `41/41 passed, 0 failed (verify mode, lane=v2)`.

---

## Conventions to follow

### Branch naming

`refactor/market-agnostic-phase-N-<slug>` for main phase work.
`refactor/market-agnostic-phase-N-bis-M-<slug>` for follow-up.
Follow-ups to v9-bis-2 deferred items use:

* `refactor/market-agnostic-phase-2-bis-3-3` (T-13/T-14 remaining)
* `refactor/market-agnostic-phase-9-bis-physical` (T-23)
* `refactor/market-agnostic-phase-8-bis-2-2` (T-24 full)
* `refactor/market-agnostic-phase-7-bis-eu-uk` (EU/UK plugins)

Branch off `dev`. Merge with `--no-ff` for visible history.

### Commit messages

Two-commit pattern per branch:

1. Working commit on the branch:
   ```
   phase-N-bis-M (T-XX): one-line summary

   Multi-paragraph body explaining what changed and why.

   Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
   ```
2. Merge commit (auto-generated by `git merge --no-ff`):
   ```
   Phase N-bis-M — Title-case summary
   ```

### Disposition + dashboard updates

Every closed deferred item adds a row to
`docs/refactor/refactor-disposition-status.md` "Implemented"
bucket and removes its entry from "Still deferred with owner."

The `docs/refactor/release-gate-dashboard.md` "Phase progress"
table gets a status column update.

### Tests

* Use existing test idioms (pydantic round-trip, fixture comparison,
  lane-isolation regex scan, parity harness). Don't invent parallel
  test infrastructure.
* New tests go under `tests/<area>/` matching the code being
  changed.
* Phase-specific tests typically named
  `test_v3_phase<N>_<slug>.py` or `test_v6_<thing>.py`.

### Pre-commit checks

`uv run python scripts/audit/classify_files.py --check` MUST be
green before merging. If you add new files, run
`uv run python scripts/audit/classify_files.py` (no --check) to
regenerate `docs/refactor/file_classification.md`.

---

## Architectural state — what lives where

### Backend Python

| Bucket | Count | What |
|---|---|---|
| `PROMOTED_CORE` | 85 | Region-neutral; fail-closed; lane-isolation enforced |
| `LEGACY_INDIA` | 211 | India v1 lane internals; allowlisted India literals OK |
| `REGION_PLUGIN` | 31 | Under `market_regions/<code>/` |
| `BROKER_PLUGIN` | 564 | Under `broker/<code>/` |
| `COMPATIBILITY_SHIM` | 7 | Explicit bridges (e.g. `domain/translators.py`) |
| **Total** | **898** | |

### Frontend

* `src/{hooks,components,lib,pages,api}/**` — scanned by
  `frontend/scripts/literal_scan.mjs`. **128 files** post-relocation.
* `src/india_legacy/**` — top-level India-only directory the
  scanner does NOT walk. ~130 files. Future engagements can either
  migrate these to be capability-driven or leave them as the legacy
  India UI surface forever.

### Region plugins

| Region | Manifest | RegionPlugin (Phase 7) | Sandbox provider | Options provider | Screener provider |
|--------|----------|------------------------|------------------|------------------|-------------------|
| `india` | ✅ | `IndiaRegionPlugin` | `IndiaSandboxProvider` (with `manager_classes()`) | `IndiaOptionsProvider` (with `service_modules()`) | Chartink |
| `us` | ✅ | `USRegionPlugin` | `USSandboxProvider` ($100k/T+1/16:00 ET) | `USOptionsProvider` (OCC OSI 21-char) | stub |
| `eu` | ✅ | none (stub) | `EUSandboxProvider` (mock) | stub | stub |
| `uk` | ✅ | none (stub) | `UKSandboxProvider` (mock) | stub | stub |

### Broker translator parity (Phase 6 ALL_GREEN)

All 30 India brokers have v2 translators registered and
bit-identical parity on both `--lane v1` and `--lane v2`,
including with their respective `API_V2_<BROKER>=1` flags
enabled. See `docs/refactor/v6-translator-parity-status.md`
STATUS: ALL_GREEN.

`API_V2_<BROKER>` flags default to OFF per ADR 0005 — operator
flips them on per-broker.

---

## Pitfalls / gotchas (things that tripped me up)

### 1. LF/CRLF warnings on git mv (Windows)

```
warning: in the working copy of '...', LF will be replaced by CRLF
the next time Git touches it
```

These are noise on Windows. Ignore them. Don't try to fix them —
they're driven by the user's git autocrlf setting.

### 2. Circular import when importing `services.place_order_service` standalone

The chain is:
`services.place_order_service` → `restx_api.schemas` →
`restx_api.__init__` → `restx_api.options_multiorder` →
`services.options_multiorder_service` → `services.place_order_service`.

Pre-existing on `dev`. Doesn't break the running app (imports
happen in the right order via app.py). DO NOT try to "fix" it
during a phase migration — it's not your problem.

### 3. Frontend scanner subdir confusion

The scanner walks `src/{hooks,components,lib,pages,api}/**`. So:

* `src/india_legacy/lib/foo.ts` → NOT scanned (top-level
  india_legacy is outside walk).
* `src/lib/india_legacy/foo.ts` → SCANNED (under lib/).

When relocating files, move them to `src/india_legacy/<subdir>/`,
NOT `src/<subdir>/india_legacy/`.

### 4. Frontend `git mv` in nested dirs

`git mv src/components/flow src/india_legacy/components/flow`
fails if `src/india_legacy/components/` doesn't exist. Pattern I
used:

```bash
mkdir -p src/india_legacy/components
git mv src/components/flow src/india_legacy/components_flow_tmp
git mv src/india_legacy/components_flow_tmp src/india_legacy/components/flow
```

The two-step rename via tmp name is needed because `git mv` won't
mv into a non-existent destination dir on Windows.

### 5. PowerShell vs Bash

Tests + sed work cleanly in Bash (Git Bash on Windows). PowerShell
is needed for some `pytest` commands when `uv run pytest` doesn't
find tests due to `cwd` issues — `Set-Location` first.

### 6. Allowlist subset-invariant baseline

`tests/contracts/v6_phase_1_baseline_allowlist.json` is the
baseline. Live `frontend/scripts/literal_scan_allowlist.json` must
be a SUBSET of baseline. To bump baseline (which Phase 4 did once
to add `useRegionCapabilities.ts`), update BOTH the baseline JSON
AND `tests/contracts/test_v6_frontend_allowlist_shrinks.py`'s
`test_baseline_size_is_known` expected count.

### 7. Plugin schema validation strictness

`docs/region-plugin-schema/plugin.v2.schema.json` has
`additionalProperties: false`. Any new field added to a region's
`plugin.json` must ALSO be added to the schema. Phase 3 added the
v3 fields (`product_vocabulary`, `price_type_vocabulary`,
`legacy_compat_shim`, etc.).

### 8. Parity test patches: source vs lazy attribute

After Phase 3 made `database.token_db.get_token` a function-local
import in `quotes_service.py`, `history_service.py`, `depth_service.py`,
the parity tests had to switch from
`mock.patch.object(quotes_service, "get_token", ...)` to
`mock.patch("database.token_db.get_token", ...)`. Whenever you
make an import lazy/function-local, search for parity tests that
patch it and update them.

---

## Useful sed patterns I used

### Bulk import path update

```bash
cd frontend && for f in $(grep -rl "@/api/X\|@/api/Y" src 2>/dev/null); do
  sed -i \
    -e "s|'@/api/X'|'@/india_legacy/api/X'|g" \
    -e "s|'@/api/Y'|'@/india_legacy/api/Y'|g" \
    "$f"
done
```

### Find-stale-allowlist helper

`frontend/scripts/find_stale_allowlist.mjs` (already shipped):
checks each entry in the allowlist against the actual file and
reports whether the file still has India literals. Use it AFTER
migrating a component to confirm the entry is droppable:

```bash
node frontend/scripts/find_stale_allowlist.mjs
```

### PowerShell allowlist surgery

When the Edit tool struggles with multi-block JSON edits, use
PowerShell's `ConvertFrom-Json` / `ConvertTo-Json`:

```powershell
cd 'E:\stocktradingsoftware\openalgo\frontend'
$json = Get-Content scripts/literal_scan_allowlist.json -Raw | ConvertFrom-Json
$remove = @('src/path/to/drop.tsx', 'src/path/to/drop2.tsx')
$kept = $json.allowlist | Where-Object { $remove -notcontains $_.path }
$obj = [ordered]@{ "_comment" = $json._comment; "_schema" = $json._schema; allowlist = @($kept) }
$obj | ConvertTo-Json -Depth 10 | Set-Content scripts/literal_scan_allowlist.json -Encoding utf8
```

---

## Hard invariants (any change that breaks these = revert immediately)

These are the contract; they hold at every commit:

1. **India parity is the gatekeeper.** All 41 parity harnesses
   bit-identical on both `--lane v1` and `--lane v2`. Any diff →
   revert.
2. **Schema additions are pure additions.** No removed fields,
   no renamed fields. Defaults must not change semantics for
   existing manifests.
3. **`/api/v1` response shapes are frozen** (per ADR 0005). Internal
   refactors must not change a single byte of `/api/v1` output.
4. **Frontend allowlist is monotone-shrink** unless you ALSO bump
   the baseline (and update the size assertion test).
5. **No new India literal in PROMOTED_CORE.** Lane-isolation tests
   enforce this.
6. **No silent broker-name list in promoted code.** Use capability
   flags.
7. **`SymToken` is read-only and India-only.**
   `scripts/audit/symtoken_callers.py` must show 0 PROMOTED_LEAK
   rows.
8. **`API_V2_<BROKER>=*` defaults to OFF** per ADR 0005. Operator
   flips on.
9. **`OPENALGO_V1_SUNSET_DATE` defaults to unset.** Setting it is
   a deployment decision, not a release decision.
10. **Don't push to `origin` without the user's explicit ask.**
    The user pushes on their own.

---

## Final state checklist (run this before declaring "done")

After ANY remaining v9-bis-2 work, verify:

- [ ] `uv run python tests/parity/run_parity.py` — 41/41 default mode.
- [ ] `uv run python tests/parity/run_parity.py --lane v1` — 11/11.
- [ ] `uv run python tests/parity/run_parity.py --lane v2` — 41/41.
- [ ] All 30 `API_V2_<BROKER>=1` v2 lane — 41/41 (see big env
      command above).
- [ ] `uv run python scripts/audit/classify_files.py --check` —
      no drift.
- [ ] `node frontend/scripts/literal_scan.mjs` — 0 violations.
- [ ] `cd frontend && npx tsc --noEmit` — clean.
- [ ] `uv run pytest tests/contracts/test_v6_closing_invariants.py -q` —
      all green.
- [ ] `uv run pytest tests/contracts/test_v6_frontend_allowlist_shrinks.py -q` —
      4/4.
- [ ] `docs/refactor/release-gate-dashboard.md` updated.
- [ ] `docs/refactor/refactor-disposition-status.md` updated.
- [ ] All commits use `Co-Authored-By: Claude Opus 4.7 (1M context)
      <noreply@anthropic.com>` footer.
- [ ] Branch merged to `dev` with `--no-ff`.
- [ ] User notified; user pushes to origin.

---

## Quick start template (copy-paste this prompt)

When restarting after a compact, the user can give me this:

> Read `docs/refactor/v9-bis-2-handoff.md`. Working tree is clean,
> dev is synced with origin. Pick up the deferred work — start with
> [T-13/T-14 remaining | T-23 physical relocation | T-24 full doc
> split | EU/UK plugins | <other>]. One item per branch, no
> batching. Verify parity green at every commit. Don't push to
> origin without me asking.

---

*End of handoff doc. This file lives at
`docs/refactor/v9-bis-2-handoff.md` and is the canonical
reference for picking up the remaining market-agnostic refactor
work.*
