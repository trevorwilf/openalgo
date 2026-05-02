# Region plugin schema — overview

The `MarketRegion` model in `domain/regions.py` is the source of truth
for what each market region declares. The schema has evolved across
three iterations:

| Iteration | Phase | Source | Surface |
|-----------|-------|--------|---------|
| v1 | pre-refactor | original plugin.json | `region_code`, `display_name`, `timezone_name`, `market_families`, `default_currency`, `default_venue_codes`, `default_sessions`, `country_codes`, `metadata` |
| v2 | refactor v3 Phase 2 | ADR 0006 | `venues[]`, `session_templates[]`, `calendar_exceptions[]`, `symbol_display`, `feature_flags` |
| v3 | refactor market-agnostic Phase 0 (T-01) | Expert 3 Appendix B §7.2 | `product_vocabulary`, `price_type_vocabulary`, `mandatory_close_rules[]`, `quantity_freeze_rules[]`, `currency_locale`, `option_grammar`, `index_classification`, `legacy_compat_shim`, `screener_providers[]`, `master_contract_refresh_policy` |

All v2 and v3 fields are **optional with empty defaults**. A v1
manifest continues to validate verbatim. A v3 field that is omitted
defaults to the empty container of the appropriate type. No live
consumer reads v3 fields in Phase 0 — they are added so later phases
have a place to put the relocated India data without a second schema
migration.

See:

* `v3-fields.md` — per-field reference for the v3 additions.
* `domain/regions.py` — authoritative pydantic source.
* `tests/region_loader/test_v6_region_schema_v3_fields.py` — the
  contract test that pins the v3 surface.
