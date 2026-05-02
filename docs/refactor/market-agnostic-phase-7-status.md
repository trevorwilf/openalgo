# Phase 7 — India + US region plugins (RegionPlugin Protocol)

Status: **shipped**.

This is Phase 7 of the market-agnostic refactor. Defines the
`RegionPlugin` Python Protocol and ships complete India and US
plugin implementations. EU and UK remain stub-grade per the
prompt's explicit non-goal.

## What landed

### Sub-phase 7a — RegionPlugin Protocol + IndiaRegionPlugin

`domain/region_plugin.py` defines the `RegionPlugin` Protocol with 13
methods covering manifest, timezone, calendar, sessions, squareoff
rules, qty-freeze rules, options grammar, index classification,
locale, settlement, and the three provider handles (sandbox /
options / screener).

`market_regions/india/plugin.py` implements `IndiaRegionPlugin` by
composing the Phase 2 data modules (`holidays`, `sessions`,
`squareoff`, `qty_freeze`, `options_grammar`, `locale`) plus the
manifest cache. Every method delegates — no duplicate data.

`utils/region_loader.py` adds:

* `get_region_plugin(region_code)` — lazy-loads
  `market_regions.<code>.plugin` and instantiates the
  `<Code>RegionPlugin` class once per process.
* Cache cleared by `_reset_cache_for_tests()`.

The 13 Protocol methods are all populated for India:

| Method | India return |
|--------|--------------|
| `region_code` | `"india"` |
| `manifest()` | parsed `MarketRegion` (10 venues, 3 sessions) |
| `timezone_object()` | `pytz.timezone("Asia/Kolkata")` (identity) |
| `holiday_calendar(2026)` | 17 entries (16 trading + 1 Muhurat) |
| `session_templates()` | 3 (equity, MCX, CDS) |
| `squareoff_rules()` | 8 (NSE/BSE/NFO/BFO/CDS/BCD/MCX/NCDEX) |
| `qty_freeze_rules()` | 1 (NFO) |
| `options_grammar()` | DDMMMYY + CE/PE + lot sizes + 15:30 IST |
| `index_classification()` | `{NSE: [NSE_INDEX], BSE: [BSE_INDEX]}` |
| `locale()` | INR / ₹ / en-IN / Cr/L thresholds |
| `settlement_template(venue)` | `"T+1"` |
| `sandbox_provider()` | `IndiaSandboxProvider` |
| `options_provider()` | `IndiaOptionsProvider` |
| `screener_providers()` | `["chartink"]` |

### Sub-phase 7b — USRegionPlugin + supporting modules

New `market_regions/us/` Python modules:

* `holidays.py` — NYSE / NASDAQ holidays for 2024 / 2025 / 2026 /
  2027 (federal holidays + early-close days for the day after
  Thanksgiving + Christmas Eve when on a weekday).
* `sessions.py` — `US_EASTERN` timezone (`pytz.timezone("America/New_York")`)
  + 3 session templates (PRE_MARKET 04:00–09:30, REGULAR 09:30–16:00,
  POST_MARKET 16:00–20:00) for XNYS / XNAS / ARCX / BATS.
* `qty_freeze.py` — empty list (no US equivalent of NFO freeze).
* `options_grammar.py` — OCC OSI 21-character format
  (`<root[6]><yymmdd[6]><C/P[1]><strike_dollars[5]><strike_decimals[3]>`),
  C/P right codes, $USD currency, OPRA venue, 100 lot size, 16:00 ET
  expiry cutoff.
* `locale.py` — `format_us_currency(value)` → `$1,234.56` /
  `-$1,234.56`.
* `settlement.py` — T+1 since SEC Rule 15c6-2 amendment (May 2024).
* `plugin.py` — `USRegionPlugin` composing the above + the existing
  US sandbox / options providers.

`USRegionPlugin` satisfies the `RegionPlugin` Protocol. The existing
US sandbox provider (`services/sandbox/providers/us/__init__.py`)
already had:

* T+2 equity / T+1 options settlement with weekend-skipping business-
  day arithmetic.
* DAY_TRADE / OVERNIGHT / MARGIN products (no MIS).
* USD currency, $100,000 initial funds.
* DAY_TRADE auto-close at 16:00 ET on equity venues.
* Partial-fill simulation for low-liquidity orders (volume < 100).

The existing US options provider already had OSI-21 parse / format
plus mock chain + Greeks via Black-Scholes. The new
`market_regions/us/options_grammar.py` records the data tables
(format string, right codes, lot size, expiry cutoff) so future
provider migrations don't need to touch the parser.

`services/screeners/providers/us/` remains a stub — no US screener
ships in this engagement (matches the prompt's "stub provider that
registers the slot but every method raises NotImplementedError").

## EU + UK status

EU and UK manifests load and their stub sandbox providers
(`EUSandboxProvider`, `UKSandboxProvider`) remain stub-grade. The
RegionPlugin Protocol is defined for all 4 regions, but no
`market_regions/eu/plugin.py` / `market_regions/uk/plugin.py` Python
class ships yet — `get_region_plugin("eu")` returns `None`. This is
the intentional shape per the prompt:

> EU and UK explicitly stay as stubs in this phase. Their providers
> continue to raise RegionProviderNotRegistered. This is intentional
> — the user instruction was "start with writing the india and US
> market plugins."

## Tests added

* `tests/region_loader/test_india_region_plugin_complete.py` (5
  tests): Protocol satisfaction, region_loader resolution, every
  method returns non-empty data, deep-copy semantics on mutable
  fields.
* `tests/region_loader/test_us_region_plugin_complete.py` (6
  tests): Protocol, loader, calendar populated for 2024-2027 (≥9
  closed days/year), US-shaped data (USD locale, US venues, no India
  literals), OSI-21 round-trip on `AAPL  240419C00185000`,
  America/New_York timezone identity.
* `tests/services/test_us_sandbox_smoke.py` (6 tests): $100k
  initial funds, simulate_fill at last price, partial fill on low
  liquidity, T+2 equity settlement (weekend-skipped), 16:00 ET
  DAY_TRADE squareoff, products contain `DAY_TRADE` and NOT India
  codes.

## Verification

* `uv run python tests/parity/run_parity.py` — 41/41 parity green
  (India unaffected).
* `uv run pytest tests/contracts/ tests/region_loader/ tests/multi_region/ tests/services/test_us_sandbox_smoke.py tests/services/test_v3_phase3_region_aware_validators.py -q` — 616 tests pass.
* `uv run python scripts/audit/classify_files.py --check` — 897
  files classified, no drift; the 8 new region-plugin files are all
  REGION_PLUGIN-classified by the existing `path_prefix:
  market_regions/` rule.
* `tests/multi_region/test_v6_capability_load_four_regions.py` —
  green; US now resolves to a real `RegionPlugin`.
* `tests/multi_region/test_v6_no_india_fallback_for_non_india.py` —
  green.
