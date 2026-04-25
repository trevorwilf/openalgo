# ADR 0015 — Product-specific capability matrix

Status: accepted (Phase 8, market-agnostic v2)
Date: 2026-04-25

## Context

Webull's docs make explicit that capabilities differ across products:

* Equities: support fractional shares, NOTIONAL quantity, extended-
  hours sessions.
* Options: do NOT support fractional; multi-leg combo flavors;
  different expiry grammar.
* Futures: only CONTRACTS quantity unit; only specific TIFs.
* Crypto: 24x7 sessions, fractional always supported.

A single broker-wide `BrokerCapabilities.supported_quantity_units`
list cannot represent "WHOLE+FRACTIONAL+NOTIONAL for equity but
CONTRACTS for futures". A future Webull plugin needs per-product
capability declarations.

Schwab has the same structure: equity vs option vs future have
different supported order types.

## Decision

`domain/capabilities.py` adds `ProductCapabilities`:

```python
class ProductCapabilities(BaseModel, frozen=True, extra="forbid"):
    asset_class: AssetClass
    supported_order_types: list[OrderType]
    supported_time_in_force: list[TimeInForce]
    supported_sessions: list[Session]
    supported_quantity_units: list[QuantityUnit]
    supports_fractional: bool
    supports_notional: bool
    supports_short: bool
    supports_combo_types: list[ComboType]
    streaming: dict[str, Any]
```

`BrokerCapabilities` gains:

* `products: list[ProductCapabilities]` — per-product matrix. Empty
  list means "use broker-wide fields" (backward compat).
* `auth_modes: list[AuthMode]` — Webull-direct (SIGNATURE) vs
  Webull-Connect / Schwab (OAUTH) vs legacy (API_KEY /
  SESSION_TOKEN).
* `streaming_transports: list[StreamTransport]` — what stream flavors
  the plugin will ship.
* `supports_account_hashes: bool` — Schwab-style URL hashes.
* `supports_subaccounts: bool` — Webull-style sub-accounts.

### Backward compatibility

Plugins that don't declare `products` get a derived single
`ProductCapabilities` for their primary asset class built from the
broker-wide fields. Promoted code reads `capabilities.products`
first; falls back to the broker-wide list when empty.

`rule_enforcement.check_order` (Phase 3) accepts an `account_ctx`
parameter (unused today). When the per-product matrix lookup is
wired in (Phase 9 or post-Phase-8 follow-up), it will resolve the
applicable `ProductCapabilities` by `instrument.asset_class` and
read the per-product order types instead of the broker-wide list.

## Consequences

* **Webull's per-product diff is expressible.** Equities can support
  fractional while futures don't, declared at the plugin level.
* **Schwab's per-product diff is expressible.** Same machinery.
* **Existing brokers are unaffected.** They don't declare `products`;
  the inferred single-product matrix preserves current behavior.
* **Auth-mode differences are first-class.** A future SDK reviewer
  can see at a glance whether a plugin needs HMAC signing or OAuth.

## Alternatives considered

* **Inline per-product fields on BrokerCapabilities (e.g.
  `supported_order_types_equity`, `supported_order_types_option`).**
  Rejected — combinatorial explosion, doesn't generalize.
* **Per-asset-class plugins.** Rejected — operators run one plugin
  per broker, not one per product.

## References

* `domain/capabilities.py` — `ProductCapabilities`,
  `BrokerCapabilities` Phase 8 fields
* `domain/enums.py` — `AuthMode`, `ComboType`, `StreamTransport`
* `tests/domain/test_product_capabilities.py`
* `docs/refactor/webull_readiness.md`
