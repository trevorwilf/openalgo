"""Phase 3 — services/account_context_service.

Round-trips a structured AccountContext from auth_token + broker
capabilities. Per-broker resolvers register and override the default.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from domain.account_context import AccountContext, from_legacy_dict
from domain.currency import Currency
from services import account_context_service


@pytest.fixture(autouse=True)
def _reset():
    account_context_service._reset_for_tests()
    yield
    account_context_service._reset_for_tests()


def test_default_resolver_uses_auth_token_as_account_id() -> None:
    caps = SimpleNamespace(base_currency=Currency.USD)
    ctx = account_context_service.resolve_account_context(
        broker_code="alpaca",
        auth_token="tok-123",
        capabilities=caps,
    )
    assert isinstance(ctx, AccountContext)
    assert ctx.broker_code == "alpaca"
    assert ctx.account_id == "tok-123"
    assert ctx.base_currency == Currency.USD


def test_default_resolver_without_capabilities_omits_currency() -> None:
    ctx = account_context_service.resolve_account_context(
        broker_code="zerodha", auth_token="abc",
    )
    assert ctx.base_currency is None


def test_per_broker_resolver_overrides_default() -> None:
    def schwab_resolver(token: str, caps: dict) -> AccountContext:
        return AccountContext(
            broker_code="schwab",
            account_id="ACC-1234",
            account_hash="aabbccdd",
            base_currency=Currency.USD,
        )

    account_context_service.register_account_resolver("schwab", schwab_resolver)
    ctx = account_context_service.resolve_account_context(
        broker_code="schwab",
        auth_token="ignored-by-resolver",
    )
    assert ctx.account_hash == "aabbccdd"
    assert ctx.account_id == "ACC-1234"


def test_from_legacy_dict_promotes_auth_token() -> None:
    ctx = from_legacy_dict(
        {"broker_code": "x", "auth_token": "tok"}
    )
    assert ctx.account_id == "tok"
    assert ctx.broker_code == "x"


def test_from_legacy_dict_unknown_keys_dropped_into_extra() -> None:
    ctx = from_legacy_dict(
        {"broker_code": "x", "account_id": "id", "weird_key": "weird_val"}
    )
    assert ctx.extra["weird_key"] == "weird_val"


def test_from_legacy_dict_passthrough_account_context() -> None:
    original = AccountContext(broker_code="x", account_id="id")
    assert from_legacy_dict(original) is original


def test_account_context_is_frozen() -> None:
    ctx = AccountContext(broker_code="x", account_id="y")
    with pytest.raises(Exception):
        ctx.broker_code = "z"  # type: ignore[misc]


def test_account_context_extra_forbid() -> None:
    with pytest.raises(Exception):
        AccountContext(broker_code="x", account_id="y", unknown_field=True)  # type: ignore[call-arg]
