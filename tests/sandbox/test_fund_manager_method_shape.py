"""Regression test: FundManager has the methods it advertises.

T-16 (v7 Phase 4-bis-3) inserted ``_resolve_starting_capital_default``
into the legacy ``fund_manager.py`` module body in a way that placed
the new helper *between* the class declaration line and the class
methods, AND at module-level indent. The result was that every
method that followed (``__init__``, ``initialize_funds``,
``get_funds``, ``block_margin``, ``release_margin``,
``transfer_margin_to_holdings``, ``credit_sale_proceeds``,
``calculate_margin_required``, ``check_margin_available``,
``_get_leverage``, ``_check_and_reset_funds``, ``_reset_funds``,
``_ensure_funds_initialized``) became NESTED FUNCTIONS inside
``_resolve_starting_capital_default()`` instead of methods on
``FundManager``.

Symptoms in production: ``FundManager(user_id)`` would crash with
``TypeError: object.__init__() takes exactly one argument (the
instance to initialize)``. This regression test pins the structure
so a future drive-by edit can't re-break it.
"""

from __future__ import annotations


def test_fund_manager_class_has_all_documented_methods():
    from market_regions.india.legacy_v1.sandbox.fund_manager import FundManager

    documented = (
        "__init__",
        "initialize_funds",
        "get_funds",
        "block_margin",
        "release_margin",
        "transfer_margin_to_holdings",
        "credit_sale_proceeds",
        "calculate_margin_required",
        "check_margin_available",
        "_get_leverage",
        "_check_and_reset_funds",
        "_reset_funds",
        "_ensure_funds_initialized",
    )
    missing = [m for m in documented if not hasattr(FundManager, m)]
    assert not missing, (
        f"FundManager is missing class-level methods (likely indented "
        f"inside a sibling helper function): {missing}"
    )


def test_fund_manager_init_accepts_user_id():
    """``__init__`` must accept ``user_id`` — the default
    ``object.__init__`` only takes ``self``, so a missing init is
    detectable at call-construct time."""
    from market_regions.india.legacy_v1.sandbox.fund_manager import FundManager

    # Verify the signature exposes ``user_id`` — we don't actually
    # construct an instance because the real init queries the DB.
    import inspect

    sig = inspect.signature(FundManager.__init__)
    params = list(sig.parameters)
    assert "user_id" in params, (
        f"FundManager.__init__ should accept user_id; got params={params}"
    )


def test_resolve_starting_capital_default_is_module_level():
    """The T-16 helper must be a module-level function so it doesn't
    accidentally swallow the class methods that follow it."""
    from market_regions.india.legacy_v1.sandbox import fund_manager as fm

    helper = getattr(fm, "_resolve_starting_capital_default", None)
    assert helper is not None, (
        "_resolve_starting_capital_default must be exported at module "
        "level (was previously nested inside the class body)"
    )
    assert callable(helper)
    # Returns a string (currency-stringified Decimal); should not raise
    # even if region plugin loading fails — has internal try/except.
    val = helper()
    assert isinstance(val, str) and val
