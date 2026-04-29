"""v6 Phase 2-bis sandbox — dispatcher-caller migration contract.

Asserts the sandbox production code paths import / call the sandbox
dispatcher (instead of carrying hardcoded India-only product /
currency / settlement values inline). India parity is preserved
because :class:`IndiaSandboxProvider` returns the same India values
the legacy code had hardcoded.

Phase 2-bis migrates one production caller per file per PR; this
contract grows as each caller adopts the dispatcher.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _file_text(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_order_manager_validates_via_dispatcher_supported_products() -> None:
    """``sandbox/order_manager.py`` validates product against
    ``provider.supported_products()`` (not a hardcoded list)."""
    text = _file_text("sandbox/order_manager.py")
    assert "from services.sandbox.dispatcher import get_sandbox_provider" in text
    assert "supported_products()" in text


def test_india_sandbox_provider_supported_products_match_legacy_set() -> None:
    """The India provider's product set matches the legacy hardcoded
    set verbatim, so the order_manager migration is byte-identical
    for India users."""
    from services.sandbox.dispatcher import get_sandbox_provider

    provider = get_sandbox_provider("india")
    assert provider.supported_products() == {"MIS", "CNC", "NRML"}


def test_fund_manager_default_capital_documents_provider_discrepancy() -> None:
    """``sandbox/fund_manager.py`` keeps the legacy ₹1Cr default but
    documents the discrepancy with the India provider's ₹10L
    initial_funds(). Future Phase 2-bis-2 reconciles the two values."""
    text = _file_text("sandbox/fund_manager.py")
    # The legacy default is preserved bit-identically.
    assert '"10000000.00"' in text
    # And the discrepancy is documented for future reconcile.
    assert "10×" in text or "10x" in text or "differs from" in text
