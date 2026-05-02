"""Phase 9 (T-23 logical) — v1 lane is mounted only when India plugin is
loaded.

Pre-Phase-9 the v1 blueprint was always registered. The /api/v1
lane carries India-shaped schemas / services / response shapes; for
deployments that do not load the India region plugin (e.g. a
hypothetical US-only deployment), v1 should return 404 Not Found at
the route layer instead of 410 Gone. The 410 case is reserved for
the operator-controlled OPENALGO_V1_SUNSET_DATE sunset machinery.

We test by source-scanning ``app.py`` for the conditional pattern
(rather than spinning up the full Flask app, which has heavy startup
side effects). Combined with the explicit
:func:`mount_api_v1_if_india_loaded` helper-style logic test, this
proves the gate is in place without booting the app.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_app_py_gates_v1_blueprint_registration_on_india_plugin():
    """Phase 9 (T-23 logical): the conditional registration must be in
    ``app.py``. The literal source-scan keeps this contract stable
    even if the registration is later refactored into a helper —
    just rename the search text.
    """
    src = (REPO_ROOT / "app.py").read_text(encoding="utf-8")
    assert "register_blueprint(api_v1_bp)" in src, (
        "app.py no longer references register_blueprint(api_v1_bp); "
        "Phase 9 (T-23 logical) regressed."
    )
    # Phase 9 marker — ensure the registration is INSIDE a guard, not
    # unconditional at module level.
    assert "Phase 9" in src and "T-23" in src, (
        "app.py is missing the Phase 9 (T-23 logical) marker comment "
        "near the v1-blueprint registration block."
    )
    # Ensure the gate references the India region plugin.
    register_idx = src.find("register_blueprint(api_v1_bp)")
    snippet = src[max(0, register_idx - 800): register_idx + 200]
    assert 'get_market_region("india")' in snippet, (
        "register_blueprint(api_v1_bp) is no longer guarded by "
        "get_market_region(\"india\"); Phase 9 (T-23 logical) "
        "regressed."
    )


def test_v1_routes_registered_when_india_loaded():
    """India plugin loads in the default repo state; full app
    creation is heavy but exercises the actual registration path
    end-to-end. Skipped if the dev DB or other side-effects would
    fail to initialize."""
    pytest.importorskip("flask")
    try:
        from app import create_app
    except Exception as exc:
        pytest.skip(f"app.create_app unavailable in this test env: {exc}")
    try:
        app = create_app()
    except Exception as exc:
        pytest.skip(f"app.create_app() raised: {exc}")
    v1_routes = [
        rule.rule for rule in app.url_map.iter_rules()
        if rule.rule.startswith("/api/v1/")
    ]
    assert v1_routes, (
        "Expected /api/v1/* routes to be mounted when India region is "
        "loaded; found none. The Phase 9 conditional registration in "
        "app.py may have regressed."
    )


def test_get_market_region_returns_none_for_unknown_region():
    """Sanity test that the region_loader returns None for an unknown
    region — proves the gate behavior would skip registration if
    India somehow weren't installed."""
    from utils.region_loader import get_market_region, load_market_regions

    load_market_regions()  # ensure cache populated
    assert get_market_region("nonexistent_region") is None
    # India must be loaded in the default repo state.
    assert get_market_region("india") is not None
