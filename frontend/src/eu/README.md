# EU region frontend sibling

Mirror of `frontend/src/india_legacy/` for EU-region brokers
(future EU pilot brokers per Phase 6 stakeholder notes). Builds
on the v2 capability hooks + `/api/v2/*` endpoints.

## Status

Scaffolding only. EU venues currently route through the EU
sandbox provider (T-21) but no production EU broker plugin
ships in this engagement.

## Mounting

Selected when the active broker's primary region is `"eu"`.

## Currency formatting

Use `formatCurrencyAmount(amount, "EUR")`. MiFID II / EMIR
compliance disclosures (when relevant) live in
`components/disclosures/`.
