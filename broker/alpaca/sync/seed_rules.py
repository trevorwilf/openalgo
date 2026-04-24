"""Seed BrokerOrderRule rows for Alpaca. Idempotent.

Called at app startup (after init_db) so the promoted-lane rule
enforcement has the Alpaca matrix in place before the first order.
"""

from __future__ import annotations

from database import broker_rules_repo
from domain.enums import OrderType, QuantityUnit, Session, TimeInForce


BROKER_CODE = "alpaca"


def seed_alpaca_rules() -> None:
    """Insert or update the Alpaca rule matrix. Safe to re-run."""
    broker_rules_repo.init_broker_rules_tables()
    broker_rules_repo.rules_upsert(
        broker_code=BROKER_CODE,
        venue_code=None,  # applies across all Alpaca-supported US venues
        asset_class="EQUITY",
        session_name=Session.REGULAR.value,
        allowed_order_types=[OrderType.MARKET.value, OrderType.LIMIT.value],
        allowed_time_in_force=[TimeInForce.DAY.value, TimeInForce.GTC.value],
        allows_fractional=True,
        allows_notional=True,
        allows_short=True,
        requires_limit_price=False,
    )


__all__ = ["BROKER_CODE", "seed_alpaca_rules"]
