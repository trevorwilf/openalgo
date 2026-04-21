# ADR 0002: No specific non-Indian target broker in this refactor

- **Status:** Accepted
- **Date:** 2026-04-21

## Context

ADR 0001 commits us to a market-family-agnostic core. That raises the
question of *how* agnostic: do we design against a concrete non-Indian
broker's API (e.g., Interactive Brokers, Alpaca, Binance spot, Coinbase
Advanced), or do we design against a conceptual model general enough to host
any of them later?

Designing to a specific target gives a sharper acceptance criterion ("does
Alpaca work?") but bakes that broker's quirks into the domain types. The
legacy Indian path already shows what that looks like: `VALID_EXCHANGES`,
`VALID_PRODUCT_TYPES`, and `VALID_PRICE_TYPES` in `utils/constants.py` are
NSE/BSE/MCX shape, and the whole codebase imports them as if those are the
only possibilities.

## Decision

We design the domain model to be general enough for **Indian, US, and
European equities, plus crypto**, without importing or referencing any
specific broker SDK in the core.

The **first** non-Indian broker adapter is explicitly out of scope for
Phase 0–Phase 9 of this refactor. It is a post-refactor concern.

Concretely:

- `domain/enums.py` (Phase 1a) carries `MarketFamily.{IN_STOCK, US_STOCK,
  EU_STOCK, UK_STOCK, CRYPTO, FUTURES, FX, COMMODITY, OTHER}`. These are
  design targets, not delivery targets.
- `OrderType` includes US/EU-specific types (`MARKET_ON_OPEN`,
  `MARKET_ON_CLOSE`, `LIMIT_ON_OPEN`, `LIMIT_ON_CLOSE`, `TRAILING_STOP`,
  `PEGGED`) so the enum does not need to change when the first non-Indian
  broker lands.
- `TimeInForce` includes `GTC`, `GTD`, `OPG`, `ATC`. `Session` includes
  `PRE_MARKET`, `OPENING_AUCTION`, `CLOSING_AUCTION`, `POST_MARKET`,
  `EXTENDED`, `ALL_DAY`. `QuantityUnit` includes `FRACTIONAL` and
  `NOTIONAL` for US-retail-style fractional and crypto notional orders.
- `Currency` is a first-class field on orders and balances, not inferred
  from broker name.
- Invariant §8 of the refactor playbook applies: no FINRA, MiFID, or other
  jurisdiction-specific code lands during this refactor unless the
  playbook explicitly calls for it.

## Consequences

**Positive**

- The domain model does not need a breaking change when the first non-Indian
  broker adapter lands.
- Reviewers have a clear rejection rule: a PR that adds a named US or EU
  broker module is not Track A.
- Indian behavior is unaffected because every new concept (fractional,
  notional, extended-hours sessions, MOO/MOC) is additive and gated by
  broker capabilities.

**Negative**

- The enums contain values that have no consumer today. Without discipline,
  that can look like dead code.
- There is no concrete integration test proving the non-Indian design targets
  work end-to-end. We can only round-trip the enums and DTOs.

## References

- `docs/adr/0001-track-a-scope.md` — Track A scope statement
- `utils/constants.py:48,67,75` — legacy `VALID_EXCHANGES`,
  `VALID_PRODUCT_TYPES`, `VALID_PRICE_TYPES`
- Refactor playbook §2 invariant 8 — "US and European support is a design
  target, not a delivery target"
