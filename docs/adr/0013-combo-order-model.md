# ADR 0013 — Combo / multi-leg order model

Status: accepted (Phase 8, market-agnostic v2)
Date: 2026-04-25

## Context

`NormalizedOrderRequest` carries one instrument and one set of order
fields. That covers single-leg orders cleanly, but Schwab and Webull
both ship multi-leg / linked-order surfaces:

* Schwab `OrderStrategyType` — SINGLE / OCO / OTO / OTOCO / TRIGGER /
  COMBO / MULTILEG / BRACKET / ICEBERG.
* Webull `combo_type` — NORMAL / OCO / OTO / BRACKET / CONDITIONAL /
  MULTI_LEG.
* US-retail platforms commonly expose bracket orders (parent + take-
  profit + stop-loss) as a single submission.

A future plugin must be able to express "buy 1 AAPL, then if filled,
sell 1 AAPL at $120 OR sell 1 AAPL at $90 (OCO)" without dropping
into broker-specific dicts.

## Decision

`domain/orders.py` adds:

```python
class OrderLeg(BaseModel, frozen=True, extra="forbid"):
    instrument_ref: InstrumentRef
    side: OrderSide
    quantity: Decimal
    quantity_unit: QuantityUnit
    order_type: OrderType
    price: Decimal | None
    trigger_price: Decimal | None
    position_effect: PositionEffect | None

class NormalizedComboOrderRequest(BaseModel, frozen=True, extra="forbid"):
    combo_type: ComboType
    time_in_force: TimeInForce
    session: Session
    legs: list[OrderLeg]   # >= 1
    link_id: str | None    # for OTO/OCO/OTOCO grouping
    metadata: dict[str, Any]
```

`ComboType` enum values: SINGLE, OTO, OCO, OTOCO, COMBO,
MULTILEG_OPTIONS, ICEBERG, BRACKET.

Cross-leg invariants (enforced at `model_validator`):

* `legs` non-empty.
* `combo_type=SINGLE` ⇒ exactly one leg.
* `combo_type ∈ {OCO, OTO, OTOCO}` ⇒ at least two legs.
* `combo_type=BRACKET` ⇒ exactly three legs (parent, take-profit,
  stop).

`OrderLeg` reuses the limit/stop validators from
`NormalizedOrderRequest`: limit-type orders require `price`; stop-
type orders require `trigger_price`; quantity must be positive.

### Capability gating

Translators opt in via the new
`ProductCapabilities.supports_combo_types: list[ComboType]` field
(ADR 0015). A broker that doesn't list a combo_type in its product
capability simply never receives a `NormalizedComboOrderRequest`
of that type — the dispatcher rejects upfront with
`unsupported_capability`.

### Backward compatibility

`NormalizedOrderRequest` is unchanged. Existing single-leg orders
keep flowing through it. The combo shape is opt-in; no plugin is
forced to handle it.

## Consequences

* **Schwab and Webull combo / bracket orders are expressible** without
  touching translator code.
* **Single-leg traffic is unaffected.** No risk to legacy India or
  Alpaca flows.
* **Future combo families** (Schwab's TRIGGER variants, Webull's
  CONDITIONAL) can be added by extending `ComboType` without breaking
  any existing translator.

## Alternatives considered

* **Make `NormalizedOrderRequest` carry an optional second leg.**
  Rejected — combos can have 2-N legs; a fixed-shape extension hides
  intent and breaks composability.
* **Per-broker dict shape.** Rejected — defeats the point of a
  normalized layer.

## References

* `domain/orders.py` — `OrderLeg`, `NormalizedComboOrderRequest`
* `domain/enums.py` — `ComboType`
* `tests/domain/test_combo_order_model.py`
* `docs/refactor/schwab_readiness.md`
* `docs/refactor/webull_readiness.md`
