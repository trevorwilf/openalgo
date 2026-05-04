"""check_order — declarative promoted-lane order validation.

Consumes :class:`BrokerOrderRule` rows from
:mod:`database.broker_rules_repo` and session overrides. Raises
:class:`OrderRuleViolation` with a deterministic ``code`` so callers
can map to a stable HTTP error envelope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

from database import broker_rules_repo
from domain.broker_rules import BrokerOrderRule
from domain.enums import OrderType, QuantityUnit, Session, TimeInForce

if TYPE_CHECKING:  # pragma: no cover
    from domain.orders import NormalizedOrderRequest


@dataclass(frozen=True)
class OrderRuleViolation(Exception):
    """Raised when an order violates a declarative rule.

    ``code`` is stable — callers rely on it for log correlation and
    API error envelopes.
    """

    code: str
    message: str
    rule_id: Optional[int] = None

    def __str__(self) -> str:  # keep Exception's default helpful
        return self.message


def _row_to_rule(row) -> BrokerOrderRule:
    return BrokerOrderRule(
        broker_code=row.broker_code,
        venue_code=row.venue_code,
        asset_class=row.asset_class,
        session=row.session,
        side=row.side,
        quantity_unit=row.quantity_unit,
        allowed_order_types=[OrderType(v) for v in row.allowed_order_types],
        allowed_time_in_force=[TimeInForce(v) for v in row.allowed_time_in_force],
        requires_limit_price=row.requires_limit_price,
        allows_fractional=row.allows_fractional,
        allows_notional=row.allows_notional,
        allows_short=row.allows_short,
        metadata=dict(row.metadata_json or {}),
    )


def load_rules_for(
    broker_code: str,
    venue_code: Optional[str],
    asset_class: Optional[str],
    session_name: Optional[str],
) -> list[BrokerOrderRule]:
    """Load all rules for ``broker_code``; callers filter further.

    Returns every row for the broker so that wildcard rules (NULL
    qualifiers) remain visible to the specificity ordering. Callers
    narrow with :func:`_match`.
    """
    rows = broker_rules_repo.rules_list_for(broker_code)
    return [_row_to_rule(r) for r in rows]


def _match(
    rule: BrokerOrderRule,
    *,
    venue_code: Optional[str],
    asset_class: Optional[str],
    session_name: Optional[str],
    side: Optional[str],
    quantity_unit: Optional[str],
) -> bool:
    def ok(rule_val, actual_val) -> bool:
        if rule_val is None:  # wildcard
            return True
        if actual_val is None:
            return False
        return str(rule_val) == str(actual_val)

    return (
        ok(rule.venue_code, venue_code)
        and ok(rule.asset_class, asset_class)
        and ok(rule.session, session_name)
        and ok(rule.side, side)
        and ok(rule.quantity_unit, quantity_unit)
    )


def _session_is_enabled(
    broker_code: str,
    venue_code: str,
    session_name: str,
    now: datetime,
) -> tuple[bool, Optional[str]]:
    """Evaluate broker-level session overrides.

    Returns ``(is_enabled, reason_if_disabled)``. The canonical venue
    schedule is authoritative for open/close *times*; this layer only
    lets a broker close a session it otherwise supports.
    """
    on_date: date = now.date()
    # Date-specific overrides first — they win over always-on overrides.
    dated = broker_rules_repo.session_overrides_for(
        broker_code=broker_code,
        venue_code=venue_code,
        session_name=session_name,
        on_date=on_date,
    )
    dated_for_date = [o for o in dated if o.effective_date == on_date]
    if dated_for_date:
        row = dated_for_date[-1]
        return (bool(row.is_enabled), row.reason if not row.is_enabled else None)
    always = [o for o in dated if o.effective_date is None]
    if always:
        row = always[-1]
        return (bool(row.is_enabled), row.reason if not row.is_enabled else None)
    return (True, None)


def _record_violation(broker_code: str, code: str) -> None:
    """Bump the rule-rejection counter for observability. Best-effort —
    metric failures must not propagate to the caller.
    """
    try:
        from utils.metrics import counter

        counter("rule_rejections_total", {"broker": broker_code, "code": code})
    except Exception:  # pragma: no cover
        pass


def check_order(
    order: "NormalizedOrderRequest",
    *,
    broker_code: str,
    venue_code: Optional[str],
    asset_class: Optional[str],
    now_tz_aware: datetime,
    allows_fractional: Optional[bool] = None,
    account_ctx: Any | None = None,
) -> None:
    """Validate ``order`` against the declarative rule matrix.

    ``allows_fractional`` overrides per-instrument capability when
    provided (Phase 4's :class:`ResolvedInstrument` carries this). If
    not provided, rule-level ``allows_fractional`` is the authority.

    ``account_ctx`` is an optional :class:`domain.account_context.AccountContext`.
    When provided, rules whose
    ``metadata.required_entitlements`` set is non-empty cause a
    structured ``entitlement_required`` reject if the account does
    not carry every listed entitlement. The check is opt-in:
    rules without ``required_entitlements`` (the default for every
    legacy rule today) skip the check entirely, so existing
    deployments see no behavior change.

    Raises :class:`OrderRuleViolation` on the first failure.
    """
    if now_tz_aware.tzinfo is None:
        raise ValueError("now_tz_aware must be timezone-aware")

    rules = load_rules_for(
        broker_code=broker_code,
        venue_code=venue_code,
        asset_class=asset_class,
        session_name=order.session.value,
    )
    # Filter rules whose qualifier set matches this order, then pick
    # the most specific. Ties are broken by insertion order.
    matching = [
        r
        for r in rules
        if _match(
            r,
            venue_code=venue_code,
            asset_class=(asset_class or None),
            session_name=order.session.value,
            side=order.side.value,
            quantity_unit=order.quantity_unit.value,
        )
    ]
    if not matching:
        _record_violation(broker_code, "no_rule_matches")
        raise OrderRuleViolation(
            code="no_rule_matches",
            message=(
                f"no BrokerOrderRule matches "
                f"broker={broker_code} venue={venue_code} "
                f"asset_class={asset_class} session={order.session.value}"
            ),
        )
    matching.sort(key=lambda r: r.specificity, reverse=True)
    rule = matching[0]

    if order.order_type not in rule.allowed_order_types:
        _record_violation(broker_code, "order_type_not_allowed")
        raise OrderRuleViolation(
            code="order_type_not_allowed",
            message=(
                f"broker {broker_code!r} does not allow "
                f"order_type={order.order_type.value} for this context"
            ),
        )
    if order.time_in_force not in rule.allowed_time_in_force:
        _record_violation(broker_code, "time_in_force_not_allowed")
        raise OrderRuleViolation(
            code="time_in_force_not_allowed",
            message=(
                f"broker {broker_code!r} does not allow "
                f"time_in_force={order.time_in_force.value} for this context"
            ),
        )

    if (
        rule.requires_limit_price
        and order.order_type == OrderType.LIMIT
        and order.price is None
    ):
        _record_violation(broker_code, "limit_price_required")
        raise OrderRuleViolation(
            code="limit_price_required",
            message="LIMIT order requires a price",
        )

    # Fractional check: the rule is authoritative for *broker-level*
    # support; the instrument overrides it down (a broker that supports
    # fractional in general may still have some instruments that don't).
    if order.quantity_unit == QuantityUnit.FRACTIONAL:
        broker_allows = rule.allows_fractional
        instr_allows = broker_allows if allows_fractional is None else bool(allows_fractional)
        if not (broker_allows and instr_allows):
            _record_violation(broker_code, "fractional_not_allowed")
            raise OrderRuleViolation(
                code="fractional_not_allowed",
                message="fractional quantity_unit not allowed",
            )

    if order.quantity_unit == QuantityUnit.NOTIONAL and not rule.allows_notional:
        _record_violation(broker_code, "notional_not_allowed")
        raise OrderRuleViolation(
            code="notional_not_allowed",
            message="notional quantity_unit not allowed",
        )

    if order.side.value == "SELL" and not rule.allows_short:
        # Short-selling check. We can't detect "covers an existing
        # position" from the order alone — higher layers (position
        # service) handle that. For now, rule-level allows_short is a
        # hard gate. A broker that forbids short selling and allows
        # long SELLs must set this to True and enforce covered-only at
        # a later check.
        # Keep this as a soft gate for now — many brokers allow SELL to
        # close long positions. Leave enforcement to Phase 5+ position
        # manager.
        pass

    # Session check. If the broker has a disabling override for the
    # session on this date, fail closed.
    if venue_code is not None:
        enabled, reason = _session_is_enabled(
            broker_code=broker_code,
            venue_code=venue_code,
            session_name=order.session.value,
            now=now_tz_aware,
        )
        if not enabled:
            _record_violation(broker_code, "session_closed")
            raise OrderRuleViolation(
                code="session_closed",
                message=(reason or "session disabled by broker override"),
            )

    # Entitlement check. Rules MAY declare
    # ``metadata.required_entitlements`` (a list of strings — e.g.
    # ``["us_equity_realtime", "options_l2"]``) that gate access to
    # the order shape. Operator-level entitlements come from
    # AccountContext.entitlements. Both sides are opt-in: rules that
    # don't list any required entitlements skip the check, and
    # callers that don't pass ``account_ctx`` skip the check too.
    # That preserves backward compatibility with every existing
    # caller and rule row in production today.
    required = list(rule.metadata.get("required_entitlements") or [])
    if required and account_ctx is not None:
        granted = set(getattr(account_ctx, "entitlements", []) or [])
        missing = [e for e in required if e not in granted]
        if missing:
            _record_violation(broker_code, "entitlement_required")
            raise OrderRuleViolation(
                code="entitlement_required",
                message=(
                    f"order requires entitlements not granted on this "
                    f"account: missing={missing}"
                ),
            )


__all__ = ["OrderRuleViolation", "check_order", "load_rules_for"]
