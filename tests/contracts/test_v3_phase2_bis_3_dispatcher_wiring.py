"""Phase 2-bis-3 (T-13 + T-14) — dispatcher wiring contract tests.

Verifies that the IndiaSandboxProvider and IndiaOptionsProvider
expose handles to the legacy India sandbox managers + option
services so future consumer migrations can route through the
dispatcher rather than direct ``sandbox.*`` / ``services.option_*``
imports.

This is the architectural pivot Phase 2-bis-3 ships. The actual
per-callsite migration in ``services/sandbox_service.py`` and
``restx_api/option_*.py`` is v9-bis-2 follow-up; the dispatcher
route is now available so future code can adopt it without further
provider changes.
"""

from __future__ import annotations

import pytest


def test_india_sandbox_provider_exposes_manager_classes():
    from services.sandbox.dispatcher import get_sandbox_provider

    provider = get_sandbox_provider("india")
    assert hasattr(provider, "manager_classes")
    classes = provider.manager_classes()
    assert isinstance(classes, dict)
    expected_roles = {"order", "position", "fund", "holdings", "squareoff"}
    assert set(classes.keys()) == expected_roles, (
        f"India sandbox provider must expose {expected_roles}; got "
        f"{set(classes.keys())}"
    )
    # Each value must be a class (not an instance).
    for role, cls in classes.items():
        assert isinstance(cls, type), f"role {role!r} → {cls!r} is not a class"


def test_india_sandbox_classes_match_legacy_imports():
    """The classes the dispatcher exposes must be the same identity
    as the ones services/sandbox_service.py imports today. This is
    the bit-identical guarantee — the dispatcher route doesn't
    introduce a duplicate engine; it just exposes the legacy one."""
    from sandbox.fund_manager import FundManager
    from sandbox.holdings_manager import HoldingsManager
    from sandbox.order_manager import OrderManager
    from sandbox.position_manager import PositionManager
    from sandbox.squareoff_manager import SquareOffManager
    from services.sandbox.dispatcher import get_sandbox_provider

    classes = get_sandbox_provider("india").manager_classes()
    assert classes["order"] is OrderManager
    assert classes["position"] is PositionManager
    assert classes["fund"] is FundManager
    assert classes["holdings"] is HoldingsManager
    assert classes["squareoff"] is SquareOffManager


def test_india_options_provider_exposes_service_modules():
    from services.options.dispatcher import get_options_provider

    provider = get_options_provider("india")
    assert hasattr(provider, "service_modules")
    modules = provider.service_modules()
    assert isinstance(modules, dict)
    expected_roles = {"symbol", "chain", "greeks", "multiorder", "place_order"}
    assert set(modules.keys()) == expected_roles, (
        f"India options provider must expose {expected_roles}; got "
        f"{set(modules.keys())}"
    )


def test_india_options_modules_match_legacy_imports():
    from services import (
        option_chain_service,
        option_greeks_service,
        option_symbol_service,
        options_multiorder_service,
        place_options_order_service,
    )
    from services.options.dispatcher import get_options_provider

    modules = get_options_provider("india").service_modules()
    assert modules["symbol"] is option_symbol_service
    assert modules["chain"] is option_chain_service
    assert modules["greeks"] is option_greeks_service
    assert modules["multiorder"] is options_multiorder_service
    assert modules["place_order"] is place_options_order_service


def test_us_sandbox_provider_does_not_expose_india_managers():
    """The US provider is mock-grade and does NOT compose the India
    sandbox engine. ``manager_classes`` either returns an empty
    dict or the method is absent."""
    from services.sandbox.dispatcher import get_sandbox_provider

    us_provider = get_sandbox_provider("us")
    if hasattr(us_provider, "manager_classes"):
        classes = us_provider.manager_classes()
        assert classes == {}, (
            "US sandbox provider must not expose India manager classes; "
            f"got {classes}"
        )


def test_us_options_provider_does_not_expose_india_services():
    from services.options.dispatcher import get_options_provider

    us_provider = get_options_provider("us")
    if hasattr(us_provider, "service_modules"):
        modules = us_provider.service_modules()
        assert modules == {}, (
            "US options provider must not expose India service modules; "
            f"got {list(modules.keys())}"
        )
