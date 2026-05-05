"""Phase 6 — pre-trade validator: every guard with positive + negative cases."""

from __future__ import annotations

import time
from decimal import Decimal

import pytest

from services.charts.pre_trade_validator import (
    IDEMPOTENCY_WINDOW_SECONDS,
    IntentRequest,
    PreTradeValidator,
)
from services.charts.safety_defaults import SafetyDefaults


def _defaults(**over) -> SafetyDefaults:
    base = SafetyDefaults(
        max_order_size=100,
        max_notional=Decimal("100000"),
        currency="USD",
        kill_switch=False,
        live_mode_enabled=False,
    )
    return SafetyDefaults(**{**base.__dict__, **over})


def _intent(**over) -> IntentRequest:
    base = IntentRequest(
        idempotency_token="tok-1",
        user_id="u1",
        account_id="acct1",
        intent_kind="place",
        symbol="AAPL",
        qty=Decimal("10"),
        price=Decimal("100"),
        is_live=False,
    )
    return IntentRequest(**{**base.__dict__, **over})


def _user_accounts() -> list[str]:
    return ["acct1", "acct2"]


@pytest.fixture
def validator():
    v = PreTradeValidator()
    yield v
    v.reset_for_tests()


def test_ok_path(validator):
    r = validator.validate(_intent(), _defaults(), _user_accounts())
    assert r.code == "ok"


def test_missing_token(validator):
    r = validator.validate(_intent(idempotency_token=""), _defaults(), _user_accounts())
    assert r.code == "missing_token"


def test_missing_qty_for_place(validator):
    r = validator.validate(_intent(qty=None), _defaults(), _user_accounts())
    assert r.code == "missing_qty"


def test_size_exceeded(validator):
    r = validator.validate(_intent(qty=Decimal("101")), _defaults(), _user_accounts())
    assert r.code == "size_exceeded"


def test_notional_exceeded(validator):
    r = validator.validate(
        _intent(qty=Decimal("50"), price=Decimal("3000")),  # 150k > 100k
        _defaults(),
        _user_accounts(),
    )
    assert r.code == "notional_exceeded"


def test_kill_switch_on_blocks(validator):
    r = validator.validate(_intent(), _defaults(kill_switch=True), _user_accounts())
    assert r.code == "kill_switch_on"


def test_wrong_account(validator):
    r = validator.validate(_intent(account_id="other"), _defaults(), _user_accounts())
    assert r.code == "wrong_account"


def test_live_mode_disabled_blocks_live_intents(validator):
    r = validator.validate(_intent(is_live=True), _defaults(live_mode_enabled=False), _user_accounts())
    assert r.code == "live_mode_disabled"


def test_live_mode_enabled_passes_live_intents(validator):
    r = validator.validate(_intent(is_live=True), _defaults(live_mode_enabled=True), _user_accounts())
    assert r.code == "ok"


def test_no_notional_cap_configured(validator):
    r = validator.validate(_intent(), _defaults(max_notional=None, currency="EUR"), _user_accounts())
    assert r.code == "no_notional_cap_configured"


def test_idempotency_dedupes_within_window(validator):
    a = validator.validate(_intent(idempotency_token="tok-A"), _defaults(), _user_accounts())
    assert a.code == "ok"
    b = validator.validate(_intent(idempotency_token="tok-A"), _defaults(), _user_accounts())
    assert b.code == "duplicate_intent"


def test_idempotency_constants():
    assert IDEMPOTENCY_WINDOW_SECONDS == 300


def test_idempotency_does_not_burn_token_on_size_reject(validator):
    # An intent that fails the size guard does NOT consume the token —
    # the user should be able to fix the qty and retry.
    r1 = validator.validate(
        _intent(idempotency_token="tok-burn", qty=Decimal("9999")),
        _defaults(),
        _user_accounts(),
    )
    assert r1.code == "size_exceeded"
    r2 = validator.validate(
        _intent(idempotency_token="tok-burn"),
        _defaults(),
        _user_accounts(),
    )
    assert r2.code == "ok"
