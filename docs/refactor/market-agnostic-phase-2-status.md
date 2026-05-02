# Phase 2 — Relocate India regional logic into the India region plugin

Status: **shipped (data + tests + parallel US example)**.

This is Phase 2 of the market-agnostic refactor described in
`openalgo_market_agnostic_refactor_claude_code_prompt.md`. It moves
the India-specific data tables and grammar from PROMOTED_CORE files
into a real Python package at `market_regions/india/`. The data is
relocated **byte-equivalently**: every value, dictionary key, regex
pattern, lot size, and date format matches the legacy inline source
the relocation replaces. The legacy import paths continue to expose
the symbols via re-export so existing consumers see no change.

## What landed in this phase

### T-09 — India holiday calendar
- `market_regions/india/holidays.py` — `HOLIDAYS_2026` list (17
  entries: 16 trading holidays + Diwali Muhurat trading session).
- `database/market_calendar_db.py:seed_holidays_2026` now imports
  `HOLIDAYS_2026` from the relocated source instead of carrying the
  list inline.

### T-10 — IST timezone object
- `market_regions/india/sessions.py` — single source of truth for
  `IST = pytz.timezone("Asia/Kolkata")`.
- Re-exported from `database/market_calendar_db.py`,
  `blueprints/python_strategy.py`, `utils/auth_utils.py`,
  `sandbox/catch_up_processor.py`, `sandbox/squareoff_thread.py`. All
  five legacy `IST` symbols are now `is`-identical to the relocated
  one.

### T-11 — MIS auto-square-off rules
- `market_regions/india/squareoff.py` — `MANDATORY_CLOSE_RULES` table
  in the schema-shape `MarketRegion.mandatory_close_rules` consumes.
- The legacy `sandbox/squareoff_manager.py` continues to read its
  HH:MM defaults via `get_config(...)` so operator overrides keep
  working. Phase 2 records the data; live wiring to read directly
  from `region_plugin.mandatory_close_rules` is deferred to a future
  phase (see Deferred section).
- Parallel US example: `market_regions/us/squareoff.py`
  (`MANDATORY_CLOSE_RULES` for XNYS/XNAS/ARCX/BATS at 16:00 ET, data
  only — Phase 7 wires the live US sandbox engine).

### T-12 — NFO quantity-freeze rules
- `market_regions/india/qty_freeze.py` — `QUANTITY_FREEZE_RULES`
  carrying the venue-level fact (NFO has a per-underlying CSV table;
  other India venues default to 1) in the schema-shape
  `MarketRegion.quantity_freeze_rules` consumes.
- The legacy `database/qty_freeze_db.py` continues to load
  per-underlying values from `data/qtyfreeze.csv` at startup.

### T-14 — India options grammar (data)
- `market_regions/india/options_grammar.py` — DDMMMYY format pattern
  + symbol-pattern regex + lot-size table + index classification
  (`NSE_INDEX` / `BSE_INDEX`) + 15:30 IST equity-index expiry cutoff.
- The live `services/options/providers/india/__init__.py` continues
  to drive the parser/formatter logic; only the data is region-owned
  now. The byte-identical test file pins both copies in sync until
  Phase 7 folds them into a single import.

### T-15 — India locale formatters
- `market_regions/india/locale.py` — `format_indian_currency`,
  `format_indian_number`, `INDIAN_CURRENCY_LOCALE`.
- `utils/number_formatter.py` re-exports the symbols so the existing
  legacy India callers continue to import them from the same path.

## Tests added

All under `tests/region_loader/`, all green (37 tests):

- `test_india_holidays_byte_identical.py` — pins all 17 holiday
  entries (date / description / type / closed venues / open-window
  count) plus the Diwali Muhurat 7-venue list.
- `test_india_sessions_byte_identical.py` — `IST is
  pytz.timezone("Asia/Kolkata")` + identity equality across the 5
  legacy modules' re-exports.
- `test_india_squareoff_byte_identical.py` — pins all 8 squareoff
  rules + drift-guards the legacy
  `SquareOffManager.__init__` defaults.
- `test_india_qty_freeze_byte_identical.py` — pins the NFO rule
  shape + drift-guards the legacy `qty_freeze_db` CSV reference.
- `test_india_options_grammar_byte_identical.py` — pins date format,
  right codes, lot-size table, index classification, equity-index
  expiry cutoff, symbol-pattern round-trip on known samples (NIFTY,
  BANKNIFTY, VEDL with decimal strike), rejection of non-India
  grammars (OCC-21).
- `test_india_locale_byte_identical.py` — pins the formatter
  behavior (Cr / L thresholds, ₹ prefix, negative values) and the
  re-export identity.
- `test_us_squareoff_parallel_example.py` — pins the US table
  *shape* + guards against accidental copy-paste of India venue
  codes / India `MIS` product.

## Verification

- `uv run python tests/parity/run_parity.py` — 41/41 parity
  harnesses pass (verify mode). Phase 2 relocation is parity-clean
  on both lanes.
- `uv run pytest tests/contracts/ -q` — 441 contracts pass.
- `uv run pytest tests/region_loader/ tests/multi_region/
  tests/sandbox/ tests/sessions/ tests/audit/ -q` — clean.
- `uv run python scripts/audit/classify_files.py --check` — no
  drift; the 7 new India files + 1 US file are correctly classified
  `REGION_PLUGIN`.
- `uv run python scripts/audit/canonical_vs_legacy_parity.py` and
  `route_fallback_scan.py` and `symtoken_callers.py` all clean
  (PROMOTED_LEAK = 0).

## What is intentionally deferred from Phase 2

The Phase 2 prompt specifies T-13 (live sandbox engine through
dispatcher) and T-14's *consumer wiring* (live options services
through dispatcher). Both are large refactors that the v6
maintainers themselves explicitly deferred to "Phase 8-bis follow-up"
in the IndiaSandboxProvider and IndiaOptionsProvider docstrings. They
require touching ~15 files in `sandbox/*`, `blueprints/sandbox.py`,
`services/option_*_service.py` and re-running every parity harness
on every commit.

This phase ships the **data relocation** (T-09, T-10, T-11 data,
T-12 data, T-14 data, T-15) and the **byte-identical test net** so
the dispatcher wiring can be done in a focused future commit without
risking a parity regression on the data layer at the same time.

Specifically deferred:

* **T-11 wiring** — `sandbox/squareoff_manager.py` and
  `blueprints/sandbox.py` still read square-off times from the
  sandbox config table; they should read defaults from
  `region_plugin.mandatory_close_rules`. Drift between the two
  sources is guarded by `test_india_squareoff_byte_identical.py`.
* **T-12 wiring** — `database/qty_freeze_db.py` continues to load
  CSV directly; should consume the relocated rule's
  `csv_source` field.
* **T-13** — `blueprints/sandbox.py` does not yet route through
  `services.sandbox.dispatcher.get_sandbox_provider(region_code)`.
  The IndiaSandboxProvider continues to expose its contract surface
  but the live engine still runs through `sandbox/*` modules
  directly.
* **T-14 wiring** — `services/option_symbol_service.py` and the
  rest of the option service entry points do not yet route through
  `services.options.dispatcher.get_provider(region_code)`. The
  IndiaOptionsProvider exposes its contract surface; the live
  services run inline.
* **T-15 caller migration** — `format_indian_currency` /
  `format_indian_number` continue to be called from
  PROMOTED_CORE-classified files via the legacy
  `utils.number_formatter` import path. The relocated
  `market_regions/india/locale.py` is the new home; the per-caller
  switch to `format_currency_amount(amount, currency, locale)` is a
  follow-up.
* **`database/sandbox_db.py:299`** `total_capital DEFAULT
  10000000.00` schema change to `DEFAULT NULL` + India-side seed +
  upgrade migration is deferred (would touch the schema and require
  a backfill migration; out of scope for the data-relocation phase).
* **Lane-isolation `PROMOTED_PATH_ROOTS` extension** — the relocated
  files (`market_regions/india/*`, `market_regions/us/*`) are
  REGION_PLUGIN-classified and the literal-scanner already exempts
  them by classification. No PROMOTED_PATH_ROOTS edit was needed in
  this phase.

The deferred items remain on the Phase 2 backlog and are tracked in
this status doc; the next focused commit can knock them out without
re-relocating data.
