# UK region frontend sibling

Mirror of `frontend/src/india_legacy/` for UK-region brokers
(future UK pilot brokers per Phase 6 stakeholder notes). Builds
on the v2 capability hooks + `/api/v2/*` endpoints.

## Status

Scaffolding only. UK venues currently route through the UK
sandbox provider (T-22) but no production UK broker plugin
ships in this engagement.

## Mounting

Selected when the active broker's primary region is `"uk"`.

## Currency formatting

Use `formatCurrencyAmount(amount, "GBP")`. FCA disclosures
live in `components/disclosures/`.
