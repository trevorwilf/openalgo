"""Phase 7 v5 — AccountContext entitlement enforcement.

Verifies the EntitlementRequired error from Phase 1 wraps a
clean, structured signal that account-context-aware admission
flow can raise. The actual admission code wires this in v6 with
real broker plugins; here we lock the error contract.
"""

from __future__ import annotations

import pytest

from domain.account_context import AccountContext, from_legacy_dict
from domain.currency import Currency
from domain.errors import EntitlementRequired, ErrorCode


def test_account_context_entitlements_default_empty_list():
    ctx = AccountContext(broker_code="x", account_id="acc-1")
    assert ctx.entitlements == []


def test_account_context_entitlements_set_via_constructor():
    ctx = AccountContext(
        broker_code="x",
        account_id="acc-1",
        entitlements=["us_equity_realtime", "options_l1"],
    )
    assert "us_equity_realtime" in ctx.entitlements
    assert "options_l1" in ctx.entitlements


def test_account_context_subaccount_id_optional():
    ctx = AccountContext(
        broker_code="webull",
        account_id="parent-1",
        subaccount_id="sub-7",
    )
    assert ctx.subaccount_id == "sub-7"


def test_account_context_base_currency_from_currency_enum():
    ctx = AccountContext(
        broker_code="x",
        account_id="acc-1",
        base_currency=Currency.USD,
    )
    assert ctx.base_currency == Currency.USD


def test_from_legacy_dict_preserves_entitlements():
    payload = {
        "broker_code": "x",
        "account_id": "acc-1",
        "entitlements": ["options_l2"],
    }
    ctx = from_legacy_dict(payload)
    assert ctx.entitlements == ["options_l2"]


def test_entitlement_required_from_phase1_error_class():
    err = EntitlementRequired("options_l2", account_id="acc-99")
    assert err.code == ErrorCode.ENTITLEMENT_REQUIRED
    assert err.entitlement == "options_l2"
    assert err.account_id == "acc-99"


def test_entitlement_required_message_includes_entitlement():
    err = EntitlementRequired("us_equity_realtime")
    assert "us_equity_realtime" in str(err)


def test_account_context_extra_field_for_unknown_keys():
    """Unknown legacy keys should land in `extra`, not raise."""
    payload = {
        "broker_code": "x",
        "account_id": "acc-1",
        "broker_random_field": "meh",
    }
    ctx = from_legacy_dict(payload)
    assert ctx.extra.get("broker_random_field") == "meh"


def test_account_context_frozen():
    """The model must be frozen so accidental mutation is impossible."""
    ctx = AccountContext(broker_code="x", account_id="acc-1")
    with pytest.raises(Exception):  # pydantic.ValidationError or AttributeError
        ctx.broker_code = "y"  # type: ignore
