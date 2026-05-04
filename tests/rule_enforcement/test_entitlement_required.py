"""Phase 4-bis-2 — entitlement-aware rejects in check_order.

Rules MAY declare ``metadata.required_entitlements`` (a list of
strings). When non-empty AND the caller passes an ``account_ctx``,
``check_order`` raises ``OrderRuleViolation(code="entitlement_required")``
if any required entitlement is not granted on the account.

The check is opt-in on both sides:
  * Rules with no ``required_entitlements`` (the default) skip the check.
  * Calls without ``account_ctx`` skip the check (legacy callers).

Both opt-outs preserve backward compatibility — every existing
deployment + every existing rule row sees no behavior change.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from database import broker_rules_repo
from domain.account_context import AccountContext
from domain.enums import OrderSide, OrderType, QuantityUnit, Session as SessionEnum, TimeInForce
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


def _basic_order() -> NormalizedOrderRequest:
    return NormalizedOrderRequest(
        instrument=InstrumentRef(venue_code="XNAS", canonical_symbol="AAPL"),
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        quantity_unit=QuantityUnit.WHOLE,
        time_in_force=TimeInForce.DAY,
        session=SessionEnum.REGULAR,
    )


def _seed_realtime_required_rule():
    broker_rules_repo.rules_upsert(
        broker_code="fake_us",
        venue_code="XNAS",
        asset_class="EQUITY",
        session_name="REGULAR",
        allowed_order_types=["MARKET", "LIMIT"],
        allowed_time_in_force=["DAY", "GTC"],
        allows_fractional=True,
        allows_short=False,
        metadata={"required_entitlements": ["us_equity_realtime"]},
    )


def _seed_no_entitlements_rule():
    broker_rules_repo.rules_upsert(
        broker_code="fake_no_ent",
        venue_code="XNAS",
        asset_class="EQUITY",
        session_name="REGULAR",
        allowed_order_types=["MARKET", "LIMIT"],
        allowed_time_in_force=["DAY", "GTC"],
        allows_fractional=True,
        allows_short=False,
    )


def test_missing_entitlement_raises_with_account_ctx(fresh_db):
    """Account doesn't carry the required entitlement -> structured reject."""
    _seed_realtime_required_rule()
    ctx = AccountContext(
        broker_code="fake_us",
        account_id="acct-1",
        entitlements=[],  # explicitly no entitlements
    )
    with pytest.raises(OrderRuleViolation) as exc:
        check_order(
            _basic_order(),
            broker_code="fake_us",
            venue_code="XNAS",
            asset_class="EQUITY",
            now_tz_aware=datetime(2026, 4, 23, 14, 30, tzinfo=timezone.utc),
            account_ctx=ctx,
        )
    assert exc.value.code == "entitlement_required"
    assert "us_equity_realtime" in exc.value.message


def test_granted_entitlement_passes(fresh_db):
    _seed_realtime_required_rule()
    ctx = AccountContext(
        broker_code="fake_us",
        account_id="acct-2",
        entitlements=["us_equity_realtime", "options_l1"],
    )
    # No raise expected.
    check_order(
        _basic_order(),
        broker_code="fake_us",
        venue_code="XNAS",
        asset_class="EQUITY",
        now_tz_aware=datetime(2026, 4, 23, 14, 30, tzinfo=timezone.utc),
        account_ctx=ctx,
    )


def test_missing_entitlement_skipped_when_no_account_ctx(fresh_db):
    """Backward-compat: callers that don't pass account_ctx skip the
    check entirely. Existing pre-Phase-4-bis-2 callers stay green."""
    _seed_realtime_required_rule()
    check_order(
        _basic_order(),
        broker_code="fake_us",
        venue_code="XNAS",
        asset_class="EQUITY",
        now_tz_aware=datetime(2026, 4, 23, 14, 30, tzinfo=timezone.utc),
        # account_ctx left unset
    )


def test_rule_without_required_entitlements_passes_without_check(fresh_db):
    """Backward-compat: rules without required_entitlements (every
    legacy India rule today) are NOT subject to the new check."""
    _seed_no_entitlements_rule()
    ctx = AccountContext(
        broker_code="fake_no_ent",
        account_id="acct-3",
        entitlements=[],  # empty — but the rule doesn't require any
    )
    check_order(
        _basic_order(),
        broker_code="fake_no_ent",
        venue_code="XNAS",
        asset_class="EQUITY",
        now_tz_aware=datetime(2026, 4, 23, 14, 30, tzinfo=timezone.utc),
        account_ctx=ctx,
    )


def test_partial_entitlement_match_still_raises(fresh_db):
    """Rule requires multiple entitlements; account has some but not
    all -> still rejects."""
    broker_rules_repo.rules_upsert(
        broker_code="fake_us2",
        venue_code="XNAS",
        asset_class="EQUITY",
        session_name="REGULAR",
        allowed_order_types=["MARKET", "LIMIT"],
        allowed_time_in_force=["DAY", "GTC"],
        allows_fractional=True,
        allows_short=False,
        metadata={
            "required_entitlements": ["us_equity_realtime", "options_l2"],
        },
    )
    ctx = AccountContext(
        broker_code="fake_us2",
        account_id="acct-4",
        entitlements=["us_equity_realtime"],  # missing options_l2
    )
    with pytest.raises(OrderRuleViolation) as exc:
        check_order(
            _basic_order(),
            broker_code="fake_us2",
            venue_code="XNAS",
            asset_class="EQUITY",
            now_tz_aware=datetime(2026, 4, 23, 14, 30, tzinfo=timezone.utc),
            account_ctx=ctx,
        )
    assert exc.value.code == "entitlement_required"
    assert "options_l2" in exc.value.message
    assert "us_equity_realtime" not in exc.value.message
