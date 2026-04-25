# ADR 0008 — Promoted dispatch fail-closed and AccountContext model

Status: accepted (Phase 3, market-agnostic v2)
Date: 2026-04-25

## Context

ADR 0005 introduced the two-lane model: legacy and promoted. The first
v2 dispatcher in `restx_api/v2/orders.py` retained an implicit
"flag-on with no translator falls back to legacy" branch. The expert
review for v2 flagged that branch as the highest-impact remaining
boundary leak: it lets a US/EU broker accidentally take the legacy
Indian translator if anyone forgets to register a translator.

Two related issues compound this:

1. The `account_ctx` argument that flows into translators was a loose
   `TypedDict` carrying only `broker_code` and `auth_token`. Schwab
   uses account hashes in URLs, Webull supports sub-accounts, and
   future entitlement checks need a richer payload.
2. `utils/plugin_loader.py` only validated plugins against the JSON
   schema. A non-India plugin missing `supported_order_types` would
   load successfully (with empty lists) and the dispatcher would
   silently allow whatever order primitive the user sent.

## Decision

### 1. Promoted dispatch is fail-closed

`restx_api/v2/orders.py` now applies these rules in order:

* **Flag on AND translator missing → 503 `translator_not_registered`.**
  The legacy translator is never imported on this branch. The
  observability counter `promoted_failclosed_total{code="translator_not_registered"}`
  is incremented. The legacy fallback counter
  (`promoted_legacy_fallback_total`) does NOT bump.

* **Flag on AND translator present → promoted lane.** No change.

* **Flag off AND broker is non-India non-crypto → 503
  `promoted_lane_required_for_non_india_broker`.** Detected via
  `BrokerCapabilities.supported_regions` (excludes "india") and
  `BrokerCapabilities.broker_type` (not "crypto"). Counter:
  `promoted_failclosed_total{code="promoted_lane_required_for_non_india_broker"}`.

* **Flag off AND broker is India OR crypto → legacy lane.** Bit-
  identical to today.

* **Promoted lane capability precheck.** Before calling the broker
  translator, the dispatcher rejects orders whose `order_type`,
  `time_in_force`, `session`, or `quantity_unit` is not in the
  broker's `BrokerCapabilities` lists. Returns 422
  `unsupported_capability` with the field name and the list of
  supported values. This catches mis-routed requests before they hit
  the wire.

The "broker is India" detection uses `supported_regions` containing
`"india"` OR an empty `supported_regions` (the legacy 24+ Indian
plugins). The "broker is crypto" detection reads
`BrokerCapabilities.broker_type == "crypto"` — there is no hardcoded
broker name list. Delta Exchange (the current crypto plugin)
satisfies the rule via its plugin.json `broker_type: "crypto"` field.

### 2. `AccountContext` is a structured pydantic model

`domain/account_context.py` defines `AccountContext`:

```python
class AccountContext(BaseModel, frozen=True, extra="forbid"):
    broker_code: str
    account_id: str
    account_hash: str | None = None
    base_currency: Currency | None = None
    subaccount_id: str | None = None
    entitlements: list[str] = []
    extra: dict[str, Any] = {}
```

`from_legacy_dict()` is a coercion shim for code that has not yet
moved off the loose-dict shape; it promotes `auth_token` to
`account_id` and routes unknown keys into `extra`.

`domain/broker_translator.py` re-exports the new model under the same
`AccountContext` name so existing translators (Alpaca,
`tests/fakes/fake_us_translator`) keep their `from
domain.broker_translator import AccountContext` import unchanged.

### 3. Resolver service

`services/account_context_service.py` exposes
`resolve_account_context(broker_code, auth_token, capabilities=None)`.
The default resolver uses `auth_token` as `account_id` and copies
`base_currency` from the capabilities. Brokers that need richer
context (Schwab, Webull) call `register_account_resolver(broker_code,
fn)` at startup; the dispatcher then routes through the registered
resolver.

The v2 dispatcher passes the resolved `AccountContext` through to:

* `BrokerOrderTranslator.validate / to_native / send_native`
* `BrokerQuoteAdapter.get_quote`
* `BrokerBarAdapter.get_bars`
* `services.rule_enforcement.check_order` (new optional `account_ctx`
  parameter; Phase 8 will read `entitlements`)

### 4. Plugin loader completeness gate

`utils/plugin_loader.py` checks every non-India plugin against the
required-fields list (Phase 1's four basics plus the order-shape
primitives `supported_regions`, `supported_order_types`,
`supported_time_in_force`, `supported_quantity_units`,
`supported_sessions`). Missing any field skips the plugin (logged at
ERROR), unless `STRICT_CAPABILITY_INFERENCE=0` downgrades the skip to
a logged WARNING. Legacy India plugins are unaffected.

## Consequences

* **No more silent legacy leak.** A non-India broker without a
  translator returns 503 instead of running `normalized_order_to_legacy_fields`.
* **Capability mismatches surface fast.** `unsupported_capability`
  fires before the wire, preventing per-broker rule logic from
  carrying responsibility for "is this primitive even allowed".
* **Translators get richer context.** Future Schwab / Webull plugins
  can carry account hashes / sub-accounts without ad-hoc dicts.
* **Operators get observable failure.** New
  `promoted_failclosed_total{code=...}` counter distinguishes the two
  failure modes (no translator vs. lane required) so dashboards can
  alert on each independently.

## Alternatives considered

* **Auto-register a no-op translator for unknown brokers.** Rejected
  — masks the real configuration gap.
* **Make rule_enforcement read entitlements now.** Deferred to Phase 8
  per the prompt scope. The signature is in place so the change is
  internal at that point.
* **Hardcoded crypto broker allowlist.** Rejected — `broker_type ==
  "crypto"` in plugin.json already serves as the canonical signal.

## References

* ADR 0005 — Two lanes (legacy and promoted)
* ADR 0006 — Literal scanner and fail-closed capabilities
* `restx_api/v2/orders.py` — `_broker_lane_check`, `_capability_precheck`
* `domain/account_context.py`
* `services/account_context_service.py`
* `tests/api_v2/test_orders_failclosed.py`
