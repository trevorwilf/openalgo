"""Phase 5 — declarative order rule enforcement.

Happy path, disallowed order type / TIF / fractional, closed session,
DST boundary and wildcard-vs-specific precedence.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from database import broker_rules_repo
from domain.enums import (
    OrderSide,
    OrderType,
    QuantityUnit,
    Session as SessionEnum,
    TimeInForce,
)
from domain.instrument_ref import InstrumentRef
from domain.orders import NormalizedOrderRequest
from services.rule_enforcement import OrderRuleViolation, check_order


@pytest.fixture
def fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_file = tmp_path / "rules.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    broker_rules_repo._reset_engine_for_tests()
    broker_rules_repo.init_broker_rules_tables()
    yield db_file
    broker_rules_repo._reset_engine_for_tests()


def _seed_fake_us_rules():
    broker_rules_repo.rules_upsert(
        broker_code="fake_us",
        venue_code="XNAS",
        asset_class="EQUITY",
        session_name="REGULAR",
        allowed_order_types=["MARKET", "LIMIT"],
        allowed_time_in_force=["DAY", "GTC"],
        allows_fractional=True,
        allows_short=False,
    )


def _order(
    *,
    order_type: OrderType = OrderType.MARKET,
    time_in_force: TimeInForce = TimeInForce.DAY,
    side: OrderSide = OrderSide.BUY,
    quantity: str = "1",
    quantity_unit: QuantityUnit = QuantityUnit.WHOLE,
    session: SessionEnum = SessionEnum.REGULAR,
    price: str | None = None,
) -> NormalizedOrderRequest:
    return NormalizedOrderRequest(
        instrument=InstrumentRef(venue_code="XNAS", canonical_symbol="AAPL"),
        side=side,
        order_type=order_type,
        quantity=Decimal(quantity),
        quantity_unit=quantity_unit,
        time_in_force=time_in_force,
        session=session,
        price=Decimal(price) if price is not None else None,
    )


def test_happy_path_passes(fresh_db):
    _seed_fake_us_rules()
    check_order(
        _order(),
        broker_code="fake_us",
        venue_code="XNAS",
        asset_class="EQUITY",
        now_tz_aware=datetime(2026, 4, 23, 14, 30, tzinfo=timezone.utc),
    )


def test_stop_not_in_allowed_list(fresh_db):
    _seed_fake_us_rules()
    # A STOP order needs trigger_price — provide it.
    order = NormalizedOrderRequest(
        instrument=InstrumentRef(venue_code="XNAS", canonical_symbol="AAPL"),
        side=OrderSide.BUY,
        order_type=OrderType.STOP,
        quantity=Decimal("1"),
        quantity_unit=QuantityUnit.WHOLE,
        trigger_price=Decimal("100.00"),
        time_in_force=TimeInForce.DAY,
    )
    with pytest.raises(OrderRuleViolation) as exc:
        check_order(
            order,
            broker_code="fake_us",
            venue_code="XNAS",
            asset_class="EQUITY",
            now_tz_aware=datetime(2026, 4, 23, 14, 30, tzinfo=timezone.utc),
        )
    assert exc.value.code == "order_type_not_allowed"


def test_disallowed_time_in_force_raises(fresh_db):
    _seed_fake_us_rules()
    with pytest.raises(OrderRuleViolation) as exc:
        check_order(
            _order(time_in_force=TimeInForce.IOC),
            broker_code="fake_us",
            venue_code="XNAS",
            asset_class="EQUITY",
            now_tz_aware=datetime(2026, 4, 23, 14, 30, tzinfo=timezone.utc),
        )
    assert exc.value.code == "time_in_force_not_allowed"


def test_fractional_requires_rule_allows(fresh_db):
    # Seed a rule that DOES NOT allow fractional.
    broker_rules_repo.rules_upsert(
        broker_code="fake_in",
        venue_code="NSE",
        asset_class="EQUITY",
        session_name="REGULAR",
        allowed_order_types=["MARKET", "LIMIT"],
        allowed_time_in_force=["DAY"],
        allows_fractional=False,
    )
    with pytest.raises(OrderRuleViolation) as exc:
        check_order(
            _order(quantity_unit=QuantityUnit.FRACTIONAL, quantity="0.5"),
            broker_code="fake_in",
            venue_code="NSE",
            asset_class="EQUITY",
            now_tz_aware=datetime(2026, 4, 23, 14, 30, tzinfo=timezone.utc),
        )
    assert exc.value.code == "fractional_not_allowed"


def test_closed_session_override_blocks(fresh_db):
    _seed_fake_us_rules()
    target_date = date(2026, 11, 26)  # US Thanksgiving
    broker_rules_repo.session_override_upsert(
        broker_code="fake_us",
        venue_code="XNAS",
        session_name="REGULAR",
        is_enabled=False,
        effective_date=target_date,
        reason="US Thanksgiving — broker holiday",
    )
    with pytest.raises(OrderRuleViolation) as exc:
        check_order(
            _order(),
            broker_code="fake_us",
            venue_code="XNAS",
            asset_class="EQUITY",
            now_tz_aware=datetime(
                2026, 11, 26, 14, 30, tzinfo=timezone.utc
            ),
        )
    assert exc.value.code == "session_closed"
    assert "Thanksgiving" in exc.value.message


def test_dst_boundary_check_is_tz_aware(fresh_db):
    """An order at 9:30 America/New_York on the DST switch date must
    resolve via tz-aware arithmetic. No timezone literals — we construct
    via ZoneInfo.
    """
    _seed_fake_us_rules()
    ny = ZoneInfo("America/New_York")
    # 2026-03-08 is the US DST start — local 09:30 EST/EDT.
    local = datetime(2026, 3, 9, 9, 30, tzinfo=ny)  # day after switch
    # Must not raise — session is open on a regular trading day post-DST.
    check_order(
        _order(),
        broker_code="fake_us",
        venue_code="XNAS",
        asset_class="EQUITY",
        now_tz_aware=local,
    )


def test_naive_datetime_refused(fresh_db):
    _seed_fake_us_rules()
    with pytest.raises(ValueError):
        check_order(
            _order(),
            broker_code="fake_us",
            venue_code="XNAS",
            asset_class="EQUITY",
            now_tz_aware=datetime(2026, 4, 23, 14, 30),  # naive
        )


def test_wildcard_and_specific_rules_specific_wins(fresh_db):
    # Wildcard (venue=None) allows LIMIT and DAY.
    broker_rules_repo.rules_upsert(
        broker_code="alpha",
        venue_code=None,
        asset_class=None,
        session_name=None,
        allowed_order_types=["LIMIT"],
        allowed_time_in_force=["DAY"],
    )
    # Specific rule for XNAS allows MARKET and GTC.
    broker_rules_repo.rules_upsert(
        broker_code="alpha",
        venue_code="XNAS",
        asset_class="EQUITY",
        session_name="REGULAR",
        allowed_order_types=["MARKET"],
        allowed_time_in_force=["GTC"],
    )

    # A MARKET/GTC order on XNAS should pass under the specific rule.
    order = _order(order_type=OrderType.MARKET, time_in_force=TimeInForce.GTC)
    check_order(
        order,
        broker_code="alpha",
        venue_code="XNAS",
        asset_class="EQUITY",
        now_tz_aware=datetime(2026, 4, 23, 14, 30, tzinfo=timezone.utc),
    )

    # A LIMIT/DAY order on XNAS should fail the specific rule (which
    # forbids LIMIT) — even though the wildcard rule would have allowed
    # it. Specificity beats permissiveness.
    order2 = _order(
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        price="100.00",
    )
    with pytest.raises(OrderRuleViolation) as exc:
        check_order(
            order2,
            broker_code="alpha",
            venue_code="XNAS",
            asset_class="EQUITY",
            now_tz_aware=datetime(2026, 4, 23, 14, 30, tzinfo=timezone.utc),
        )
    assert exc.value.code == "order_type_not_allowed"


def test_no_rule_for_broker_raises_no_rule_matches(fresh_db):
    # No rules seeded.
    with pytest.raises(OrderRuleViolation) as exc:
        check_order(
            _order(),
            broker_code="nobody",
            venue_code="XNAS",
            asset_class="EQUITY",
            now_tz_aware=datetime(2026, 4, 23, 14, 30, tzinfo=timezone.utc),
        )
    assert exc.value.code == "no_rule_matches"
