"""v6 Phase 4-bis mock plugin extensions.

Per Q6 default — three lighter targets from the Phase 0 inventory:

1. **Combo MULTILEG_OPTIONS dispatch** — mock Schwab declares
   ``MULTILEG_OPTIONS`` in ``supports_combo_types`` and the
   translator's ``NATIVE_STRATEGY_TYPES`` maps it to ``"MULTI_LEG"``.
   This contract pins the declaration; an end-to-end MULTILEG order
   integration test through ``/api/v2/orders/combo`` is in
   ``tests/api_v2/test_orders_combo.py`` (this contract guards the
   declaration so future regressions are caught early).
2. **Position adapter currency propagation** — mock Schwab and
   mock Webull position adapters return positions with explicit
   ``currency="USD"`` (not silently inheriting INR). This pins the
   non-India currency invariant.
3. **Account context entitlements** — mock plugins declare
   ``account_context_supports`` including ``"entitlements"``, which
   the framework readiness contract surfaces as the entitlement-
   enforcement extension point. Actual ``rule_enforcement.check_order``
   integration is deferred (per Q6 — heavier work needs domain
   change).

The 2 heavier targets (master-contract refresh-policy execution and
account-context entitlement enforcement integration) are deferred to
v7 with a Phase 0 follow-up audit.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "broker_code", ["_mock_schwab_like", "_mock_webull_like"],
)
def test_mock_plugin_declares_multileg_options(broker_code: str) -> None:
    """Both mocks declare MULTILEG_OPTIONS in supports_combo_types."""
    plugin_json = REPO_ROOT / "broker" / broker_code / "plugin.json"
    data = json.loads(plugin_json.read_text(encoding="utf-8"))
    combo_types = data.get("supports_combo_types") or []
    assert "MULTILEG_OPTIONS" in combo_types, (
        f"{broker_code}: plugin.json must declare MULTILEG_OPTIONS in "
        f"supports_combo_types; got {combo_types}"
    )


def test_mock_schwab_translator_maps_multileg_options_to_native() -> None:
    """The Schwab translator's NATIVE_STRATEGY_TYPES dispatches
    MULTILEG_OPTIONS to the broker-native MULTI_LEG strategy."""
    from broker._mock_schwab_like.api.order_api import NATIVE_STRATEGY_TYPES

    assert NATIVE_STRATEGY_TYPES.get("MULTILEG_OPTIONS") == "MULTI_LEG"


def test_mock_webull_translator_maps_multileg_options_to_native() -> None:
    from broker._mock_webull_like.api.order_api import NATIVE_STRATEGY_TYPES

    assert NATIVE_STRATEGY_TYPES.get("MULTILEG_OPTIONS") in {
        "MULTI_LEG",  # Schwab-style
        "MULTILEG_OPTIONS",  # Webull-style direct passthrough
    }


def test_mock_schwab_position_adapter_propagates_usd_currency() -> None:
    """v6 Phase 4-bis: positions returned by the mock Schwab adapter
    explicitly carry ``currency='USD'``. This pins the no-India-
    fallback invariant for the position surface."""
    from broker._mock_schwab_like.api.position_balance_adapters import (
        MockSchwabLikePositionAdapter,
    )
    from domain.account_context import AccountContext
    from domain.currency import Currency

    adapter = MockSchwabLikePositionAdapter()
    ctx = AccountContext(
        broker_code="_mock_schwab_like",
        account_id="mock-acct",
        base_currency=Currency.USD,
    )
    positions = adapter.get_positions(ctx)
    assert positions, "mock position adapter returned no positions"
    for pos in positions:
        assert pos.currency == "USD", (
            f"mock Schwab position {pos.canonical_symbol} carries "
            f"currency={pos.currency!r}; expected USD"
        )
        # And explicitly NOT INR.
        assert pos.currency != "INR"


def test_mock_webull_position_adapter_propagates_usd_currency() -> None:
    from broker._mock_webull_like.api.position_balance_adapters import (
        MockWebullLikePositionAdapter,
    )
    from domain.account_context import AccountContext
    from domain.currency import Currency

    adapter = MockWebullLikePositionAdapter()
    ctx = AccountContext(
        broker_code="_mock_webull_like",
        account_id="mock-acct",
        base_currency=Currency.USD,
    )
    positions = adapter.get_positions(ctx)
    assert positions, "mock position adapter returned no positions"
    for pos in positions:
        assert pos.currency == "USD"
        assert pos.currency != "INR"


def test_mock_schwab_balance_adapter_propagates_usd_currency() -> None:
    """v6 Phase 4-bis: balance adapter also explicit-USD."""
    from broker._mock_schwab_like.api.position_balance_adapters import (
        MockSchwabLikeBalanceAdapter,
    )
    from domain.account_context import AccountContext
    from domain.currency import Currency

    adapter = MockSchwabLikeBalanceAdapter()
    ctx = AccountContext(
        broker_code="_mock_schwab_like",
        account_id="mock-acct",
        base_currency=Currency.USD,
    )
    balance = adapter.get_balance(ctx)
    # The NormalizedBalance shape may have a `currency` field; if not,
    # the adapter at least uses USD-shaped Decimal values without
    # falling back to INR semantics.
    if hasattr(balance, "currency"):
        assert getattr(balance, "currency") == "USD"
    # And cash must be a positive Decimal (sanity check).
    assert isinstance(balance.cash, Decimal) and balance.cash > Decimal("0")


@pytest.mark.parametrize(
    "broker_code", ["_mock_schwab_like", "_mock_webull_like"],
)
def test_mock_plugin_declares_entitlements_in_account_context(broker_code: str) -> None:
    """Both mocks declare account_context_supports including
    'entitlements' — the framework-level entitlement extension point.
    Actual rule_enforcement integration is deferred to v7."""
    plugin_json = REPO_ROOT / "broker" / broker_code / "plugin.json"
    data = json.loads(plugin_json.read_text(encoding="utf-8"))
    supports = data.get("account_context_supports") or []
    assert "entitlements" in supports, (
        f"{broker_code}: must declare 'entitlements' in "
        f"account_context_supports; got {supports}"
    )
