# ADR 0007 — Region plugin schema v2

Status: accepted (Phase 2, market-agnostic v2)
Date: 2026-04-25

## Context

Schema v1 region plugins (`market_regions/<code>/plugin.json`) carried
only top-level metadata: region code, timezone, market families,
default currency, default venue codes, default sessions. Venue-level
facts (timezones, settlement templates, session windows, holiday
exceptions) lived in `database/market_calendar_db.py` and were
implicitly Indian.

Both expert reports for the v2 refactor flagged this. To make the
promoted lane region-aware in a way that scales beyond India, region
plugins must own:

* the venue catalog they cover,
* the session-template windows for those venues,
* the calendar exception list (holidays, early-close, late-open,
  special sessions),
* the symbol-grammar conventions (date format, option right codes,
  futures grammar), and
* per-region feature flags that gate India-specific surfaces from
  showing up unmodified in non-India regions.

## Decision

Introduce schema v2 alongside schema v1. Both are accepted by
`utils/region_loader.py` so existing v1 plugins continue to validate
verbatim.

### Schema additions (all optional, default empty)

* `venues` — array of `{venue_code, display_name, mic_code,
  country_code, timezone_name, base_currency, market_family,
  settlement_template, session_model, metadata}`. The region plugin
  is the source of truth for these in the promoted lane.
* `session_templates` — array of `{session_code, venue_code (or
  venue_codes), local_start_time, local_end_time, days_of_week,
  effective_from, effective_to, label}`.
* `calendar_exceptions` — array of `{date, venue_code, exception_type,
  local_start_time, local_end_time, reason, source}`. Empty for
  India in this phase; Phase 4 migrates the legacy
  `market_holidays`/`market_holiday_exchanges` rows into
  `venue_calendar_exceptions` (idempotent, additive — no legacy data
  is deleted).
* `symbol_display` — `{date_format, option_right_codes,
  futures_grammar, example_underlyings}`.
* `feature_flags` — boolean map. Phase 6 reads these to gate option,
  flow, sandbox, and analyzer surfaces by active region.

### Detection and routing

`utils/region_loader.py` looks for any of the v2 indicator keys
(`venues`, `session_templates`, `calendar_exceptions`, `symbol_display`,
`feature_flags`) in a plugin and routes that plugin to
`docs/region-plugin-schema/plugin.v2.schema.json`. Plugins without any
v2 sections continue to validate against v1's `plugin.schema.json`.
Both schemas share v1's required fields, so v1 plugins are unaffected.

### Domain model

`domain/regions.py` gains `VenueSeed`, `SessionTemplateSeed`,
`CalendarExceptionSeed`, `SymbolDisplay`, `RegionFeatureFlags`. They
are `frozen=True, extra="forbid"`. `MarketRegion` now exposes:

* `get_venue(venue_code)`
* `get_sessions_for(venue_code, on_date=None)` — filters by date range
* `get_calendar_exceptions_for(venue_code, from_date=None, to_date=None)`
* `is_feature_enabled(name, default=False)`

`SessionTemplateSeed` accepts both the singular `venue_code` shortcut
and the plural `venue_codes` form; the loader normalizes singular into
a one-element list so consumers always see `venue_codes`.

### Service accessors

`services/market_region_service.py` exposes:

* `get_venue_seed(region_code, venue_code)`
* `get_session_templates(region_code, venue_code)`
* `get_symbol_display(region_code)` — returns an empty
  `SymbolDisplay` if the plugin has no v2 section
* `is_region_feature_enabled(region_code, flag, default=False)`

### India seed parity

`market_regions/india/plugin.json` is upgraded to v2. The added
`venues`, `session_templates`, and `symbol_display` mirror the
existing legacy behavior (NSE/BSE/NFO/BFO 09:15–15:30 Mon–Fri, MCX
09:00–23:30, CDS 09:00–17:00, DDMMMYY date grammar with CE/PE option
rights). `calendar_exceptions` is intentionally empty — Phase 4
populates it from the migration script. `feature_flags` declares
`option_chain_enabled`, `iv_chart_enabled`,
`muhurat_session_supported`, `india_legacy_compatibility`,
`sandbox_enabled`, `analyzer_enabled`, and `flow_templates_enabled` as
true so Phase 6's region gates do not change India behavior.

### US/UK/EU seeds

`market_regions/us/plugin.json` adds XNYS/XNAS/ARCX/BATS/IEXG with
`PRE_REGULAR_POST` session model, T+1 settlement, USD, plus PRE/REGULAR/
POST session templates (04:00 / 09:30–16:00 / 16:00–20:00 ET).
`market_regions/uk/plugin.json` adds XLON 08:00–16:30 GBP T+2.
`market_regions/eu/plugin.json` adds XPAR/XETR 09:00–17:30 EUR T+2.
All three set their region feature flags to false for Indian-only
features so Phase 6's region gates fail closed by default.

## Consequences

* **Parity preserved.** v1 plugins continue to validate. `MarketRegion`'s
  v2 fields default to empty containers. The parity harness still
  passes.
* **Loader is fail-open per plugin.** A schema-invalid plugin is
  logged and skipped — never crashes app boot.
* **Promoted code can read venue data from the region plugin** without
  hitting `database/market_calendar_db.py`. Phase 4's promoted
  `/api/v2/venues` endpoint reads from the venue table, which Phase 4
  syncs from these plugin seeds.
* **Future regions are a JSON edit.** Adding Singapore would mean a
  new `market_regions/sg/plugin.json` only — no Python changes.

## Migration path

* Phase 4 migrates legacy `market_holidays` rows into
  `venue_calendar_exceptions` via
  `upgrade/migrate_holidays_to_venue_calendar.py`, idempotent on
  rerun.
* Phase 6 reads `feature_flags` to gate option chain, flow templates,
  sandbox, and analyzer surfaces by active region.

## Alternatives considered

* **Inline calendar in the plugin.** Rejected — calendars change
  yearly; checking JSON files into git for every holiday update is
  noisy. The DB migration in Phase 4 keeps the source of truth
  database-side; the plugin's `calendar_exceptions` is for the small
  number of region-permanent overrides (e.g. Diwali muhurat session
  template).
* **Discard schema v1.** Rejected — the v1 plugins ship today;
  forcing a re-write before Phase 2 lands would be a needless
  breaking change.

## References

* ADR 0001 — Track A scope
* ADR 0006 — Literal scanner and fail-closed capabilities
* `domain/regions.py`
* `utils/region_loader.py`
* `docs/region-plugin-schema/plugin.v2.schema.json`
