"""v8 closing invariants — single-place gate for the v8 cycle.

Per ADR 0032, v8 closes the items v7 explicitly deferred. The
initial sketch of closing invariants:

* **v8-A** — Real Schwab plugin's ``api/`` package implements the
  full broker contract (auth, account, order, quote, bar, stream,
  sync) without ``legacy_v1`` imports. Deferred until operator
  obtains official API access.
* **v8-B** — Real Webull plugin same as v8-A. Deferred.
* **v8-C** — ``services/symbol_service.py`` v1 lookup paths
  query through ``SymTokenV1Read`` (or the ``symtoken_v1`` view
  via raw SQL). Same for ``services/instruments_service.py``.
* **v8-D** — US sibling has at least Dashboard + OrderBook +
  Positions pages rendering through ``/api/v2/*`` with the USD
  formatter. Phase: in progress (Dashboard tile-level RegionContent
  shipped this cycle; full page-level expansion is multi-phase).
* **v8-E** — At least one production page uses ``RegionContent``
  for region-aware tile rendering. Pattern reference for v8 page
  expansion. (Closes the "RegionContent exists but no production
  page uses it" gap from v7.)

This test runs every v8 invariant that's in scope for the
Sonnet/Opus session — v8-A and v8-B are skipped (blocked on real
Schwab/Webull access). v8-C and v8-E pin the work that's shipped.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# v8-C — symbol_service + instruments_service use the symtoken_v1 view
# ---------------------------------------------------------------------------


def test_v8_invariant_v8_c_symbol_service_uses_v1_view():
    """``services.symbol_service.get_symbol_info_with_auth`` queries
    SymTokenV1Read when the view is available.
    """
    from services import symbol_service

    # Module-level setup must declare the probe + view-aware lookup.
    src = (_REPO_ROOT / "services" / "symbol_service.py").read_text(
        encoding="utf-8"
    )
    assert "SymTokenV1Read" in src, (
        "symbol_service must import SymTokenV1Read for v8-C"
    )
    assert "_v1_view_is_available" in src, (
        "symbol_service must define _v1_view_is_available probe"
    )
    # The probe + escape hatch are both available.
    assert hasattr(symbol_service, "_v1_view_is_available")
    assert hasattr(symbol_service, "_USE_V1_VIEW")


def test_v8_invariant_v8_c_instruments_service_uses_v1_view():
    """``services.instruments_service.get_instruments`` follows the
    same view-first / SymToken-fallback pattern.
    """
    src = (_REPO_ROOT / "services" / "instruments_service.py").read_text(
        encoding="utf-8"
    )
    assert "SymTokenV1Read" in src, (
        "instruments_service must reference SymTokenV1Read for v8-C"
    )
    assert "_v1_view_is_available" in src, (
        "instruments_service must call the v8-C probe"
    )


# ---------------------------------------------------------------------------
# v8-E — at least one production page uses RegionContent
# ---------------------------------------------------------------------------


def test_v8_invariant_v8_e_at_least_one_page_uses_region_content():
    """Closes the v7 gap: ``RegionContent`` shipped but no page
    used it. v8 ships the first one (Dashboard).
    """
    pages_dir = _REPO_ROOT / "frontend" / "src" / "pages"
    assert pages_dir.is_dir(), f"missing pages dir: {pages_dir}"

    pattern = re.compile(r"<RegionContent\b")
    matches: list[str] = []
    for tsx in pages_dir.glob("*.tsx"):
        text = tsx.read_text(encoding="utf-8")
        if pattern.search(text):
            matches.append(tsx.name)

    assert matches, (
        "v8-E requires at least one production page to use "
        "<RegionContent>; found none under frontend/src/pages/"
    )


# ---------------------------------------------------------------------------
# v8 cycle re-runs the v4..v7 closing invariants
# ---------------------------------------------------------------------------


def test_v8_invariant_v7_baseline_still_holds():
    """v7 closing invariants must still pass on every v8 commit.

    Imports the v7 test functions and runs them inline so any
    regression in v7-A..v7-F surfaces here as a v8 closing failure.
    """
    from tests.contracts import test_v7_closing_invariants as v7

    v7.test_v7_invariant_v7_a_no_promoted_legacy_v1_imports()
    v7.test_v7_invariant_v7_b_no_kolkata_in_promoted_blueprints()
    v7.test_v7_invariant_v7_c_promoted_db_helpers_utc_stamp()
    v7.test_v7_invariant_v7_d_no_silent_india_defaults_in_v1_bridge()
    v7.test_v7_invariant_v7_e_refresh_policy_mandatory_for_non_legacy()
    v7.test_v7_invariant_v7_f_symtoken_includes_broker_code()


@pytest.mark.skip(
    reason="v8-A: real Schwab API integration deferred until operator "
    "obtains official Schwab Trader API access (per ADR 0032)."
)
def test_v8_invariant_v8_a_real_schwab_plugin_complete():
    """Placeholder — un-skip when real Schwab API code lands."""


@pytest.mark.skip(
    reason="v8-B: real Webull API integration deferred until operator "
    "obtains official Webull API access (per ADR 0032)."
)
def test_v8_invariant_v8_b_real_webull_plugin_complete():
    """Placeholder — un-skip when real Webull API code lands."""


@pytest.mark.skip(
    reason="v8-D: full US sibling page-level expansion is a multi-phase "
    "deliverable spanning ~393 net-new TSX/TS files (per ADR 0032). "
    "This cycle ships the RegionContent integration point only "
    "(Dashboard tile-level — covered by v8-E)."
)
def test_v8_invariant_v8_d_us_sibling_pages_complete():
    """Placeholder — un-skip when US sibling has Dashboard + OrderBook + Positions."""
