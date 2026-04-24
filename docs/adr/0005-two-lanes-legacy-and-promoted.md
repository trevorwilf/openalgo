# ADR 0005: Two lanes — legacy and promoted

- **Status:** Accepted
- **Date:** 2026-04-23

## Context

The market-agnostic refactor (ADRs 0001–0004 and
`docs/refactor/inventory/*`) establishes that OpenAlgo's *internal*
domain model should be market-family-agnostic while the deployment
model stays single-broker. Through Phase 9, the legacy Indian pipeline
has been preserved bit-identically while normalized domain models,
venue metadata, and `/api/v2` have been bolted on alongside.

`/api/v2` today is a *skeleton* that translates normalized requests
back into the legacy Indian shape before dispatch
(`restx_api/v2/orders.py` imports `normalized_order_to_legacy_fields`;
`restx_api/v2/quotes.py` and `restx_api/v2/bars.py` call the legacy
`services.quotes_service` and `services.history_service`). The legacy
stack still owns instrument resolution via
`database.token_db.get_token()` and venue validation via
`utils.constants.VALID_EXCHANGES`.

This arrangement is correct for Indian brokers — parity is the arbiter
and it still passes — but it makes `/api/v2` unsuitable for any
non-Indian broker. Any US or EU broker routed through the skeleton
would be force-mapped into Indian product / exchange / price-type
vocabulary by the legacy translator.

To move the platform forward without destabilizing the Indian flow, we
formalize two lanes.

## Decision

### The legacy lane

The legacy lane is the Indian-shaped stack that exists today.

- `/api/v1/*` is the external surface.
- `/api/v2/*` is currently a thin re-shape of `/api/v1` and counts as
  part of the legacy lane until explicitly promoted per broker.
- Owns: `services/place_order_service.py`,
  `services/quotes_service.py`, `services/history_service.py`,
  `utils/constants.py` (`VALID_EXCHANGES`, `VALID_PRODUCT_TYPES`,
  `VALID_PRICE_TYPES`), `database/token_db.py` (`get_token`),
  `domain/translators.py` (`normalized_order_to_legacy_fields`).
- **The legacy lane is frozen.** No new features. Only bug fixes and
  compliance work. Response shapes and field names are bit-identical
  with the Phase 0 baseline — parity fixtures in
  `tests/parity/baseline/` are the arbiter.

### The promoted lane

The promoted lane is the broker-native path for markets outside the
Indian legacy stack — US, EU, crypto-beyond-Delta, anything with a
different order / session / asset vocabulary than NSE+BSE+MCX.

- `/api/v2/*` is the *promoted* surface — the same URL — gated per
  broker with feature flags of the form `API_V2_<BROKER_CODE_UPPER>`.
  Example: `API_V2_ALPACA=1` promotes Alpaca onto the promoted lane;
  with the flag off or absent, Alpaca (or any other broker) stays on
  the legacy lane.
- Owns: `domain/broker_translator.py` (Phase 3),
  `services/broker_translator_registry.py` (Phase 3),
  `services/instrument_resolution.py` (Phase 4),
  `domain/broker_market_data.py` (Phase 4),
  `domain/broker_rules.py` and `services/rule_enforcement.py`
  (Phase 5), per-broker translator / quote / bar / order adapters
  under `broker/<code>/` (Phase 6).

### Import invariants for promoted paths

Code in promoted paths **must not** import, reference, or call:

- `utils.constants.VALID_EXCHANGES`
- `utils.constants.VALID_PRODUCT_TYPES`
- `utils.constants.VALID_PRICE_TYPES`
- `database.token_db.get_token`
- `domain.translators.normalized_order_to_legacy_fields`
- `services.quotes_service.get_quotes_with_auth` (and any other
  legacy-quotes entry point)
- `services.history_service.get_history_with_auth` (and any other
  legacy-history entry point)

Promoted paths resolve instruments through
`database.instruments_repo` (and `services.instrument_resolution`,
Phase 4). They dispatch orders through a per-broker
`BrokerOrderTranslator` (Phase 3). They fetch market data through a
per-broker `BrokerQuoteAdapter` / `BrokerBarAdapter` (Phase 4). They
enforce broker rules through `services.rule_enforcement.check_order`
(Phase 5).

This invariant is enforced by
`tests/contracts/test_lane_isolation.py`.

### Per-broker feature-flag rollout

Promotion is always per-broker and always flag-gated. A broker is on
the promoted lane if and only if `API_V2_<BROKER_CODE_UPPER>=1` is set
in the environment at request time. Rolling back is a single env
change — no code revert required. The flag is read through
`utils.feature_flags.is_enabled`.

## Consequences

### What this enables

- A real US broker MVP (Phase 6) without touching the legacy Indian
  flow.
- Region metadata becomes executable: a broker declares
  `supported_regions` in `plugin.json` and the promoted lane honors it
  through the rule matrix (Phase 5).
- Rollback is free — flip a flag.

### What this defers

- Multi-broker-per-instance concurrency. The
  one-broker-per-deployment invariant from ADR 0001 is preserved
  throughout. A single instance can have multiple *brokers known to
  the plugin loader*, but at most one active broker session.
- Europe and UK broker adapters. `market_regions/eu` and
  `market_regions/uk` exist as metadata only, intentionally.
- A full `/api/v3` rewrite. The promoted lane reuses `/api/v2` URLs
  and shapes; only the dispatch under the hood changes.

### What this requires

- A static CI guard (`tests/contracts/test_lane_isolation.py`) that
  fails PRs introducing forbidden imports into promoted paths.
- A short allowlist, scoped per phase, covering the known legacy
  call-sites that Phases 3 and 4 will remove. Every allowlist entry
  carries a `TODO: removed in Phase N` comment.

## Related

- [ADR 0001 — Track A scope](0001-track-a-scope.md)
- [ADR 0002 — no specific target broker](0002-no-specific-target-broker.md)
- [ADR 0003 — `/api/v1` frozen, `/api/v2` later](0003-api-v1-frozen-v2-later.md)
- [ADR 0004 — analyzer stays India-limited](0004-analyzer-india-only.md)
- [Inventory — `VALID_EXCHANGES` imports](../refactor/inventory/01-valid-exchanges-imports.md)
- [Inventory — `SymToken` usage](../refactor/inventory/02-symtoken-usage.md)
- [Inventory — IST / Kolkata references](../refactor/inventory/03-ist-kolkata-references.md)
