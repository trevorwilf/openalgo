"""Phase 4 v6 — `_legacy_india_region_for_compat` retirement contract.

Per the v6 prompt's Phase 4 spec, this test must assert:

* ``_legacy_india_region_for_compat`` is not importable from anywhere
  in the codebase.
* ``legacy_india_fallback`` is not a parameter of ``active_region_code``
  or any other public function in
  ``services.feature_gate_service``.

**Phase 4 retirement is blocked at v6 Phase 4 close.** The helper
still has live production callers because v6 Phase 2 shipped as
**scaffolding** (the per-surface dispatcher migrations are deferred
to Phase 2-bis per the v6 Phase 2 completion doc). The v6 prompt's
own Phase 4 prerequisite says explicitly:

    "If any non-test caller of legacy_india_fallback=True survived
    Phases 1–2, stop and report — Phase 2 was incomplete; do not
    proceed."

Per that prerequisite, helper retirement is correctly deferred to
the future Phase 4 (or Phase 4-bis) iteration that closes Phase
2-bis first.

This test currently asserts the **deferred state**:

1. The helper IS importable today (we document its current existence).
2. ``legacy_india_fallback`` IS a documented parameter today.

When Phase 4-bis runs (after Phase 2-bis migrates production
callers), invert these assertions and remove the legacy XFAIL
markers.
"""

from __future__ import annotations

import inspect

import pytest


def test_legacy_helper_is_currently_importable() -> None:
    """Phase 4 deferral marker: the helper still exists. Phase 4-bis
    inverts this assertion (asserts ImportError)."""
    from services.feature_gate_service import _legacy_india_region_for_compat

    # Helper must be callable until Phase 2-bis completes.
    assert callable(_legacy_india_region_for_compat)


def test_legacy_india_fallback_parameter_currently_exists() -> None:
    """Phase 4 deferral marker: the parameter still exists on
    ``active_region_code``. Phase 4-bis inverts this assertion."""
    from services.feature_gate_service import active_region_code

    sig = inspect.signature(active_region_code)
    # Parameter must currently be present until Phase 2-bis completes
    # the production-caller migration that allows safe parameter
    # removal.
    assert "legacy_india_fallback" in sig.parameters


@pytest.mark.xfail(
    reason="v6 Phase 2 shipped as scaffolding; Phase 4 helper "
    "retirement is blocked on Phase 2-bis production-caller "
    "migration. Phase 4-bis will invert this XFAIL.",
    strict=True,
)
def test_legacy_helper_is_not_importable() -> None:
    """Phase 4-bis target: when production callers are migrated, the
    helper should be removed and importing it must raise ImportError."""
    with pytest.raises(ImportError):
        from services.feature_gate_service import _legacy_india_region_for_compat  # noqa: F401


@pytest.mark.xfail(
    reason="Same v6 Phase 4-bis dependency as above.",
    strict=True,
)
def test_active_region_code_no_longer_has_legacy_fallback_parameter() -> None:
    """Phase 4-bis target."""
    from services.feature_gate_service import active_region_code

    sig = inspect.signature(active_region_code)
    assert "legacy_india_fallback" not in sig.parameters
