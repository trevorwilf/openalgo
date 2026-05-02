"""Phase 1 (T-05, T-07, T-08) — fail-closed contract test.

The three "unknown = India" branches that previously returned
``True`` / ``19800`` / ``Asia/Kolkata`` silently are now structured
errors / explicit-non-Kolkata defaults. This test pins the new
contract.

Coverage:
* ``mcp/mcpserver.py::_is_india_broker`` raises
  ``MissingRegionContext`` when the capability fetch returns None
  (T-05). The file shadows the installed ``mcp`` package so it is
  loaded via ``importlib.util.spec_from_file_location``.
* ``database.venue_offset.venue_local_offset_seconds(None)`` raises
  ``VenueResolutionError`` (T-07).
* ``utils.session._session_tz`` returns ``UTC`` (not
  ``Asia/Kolkata``) when ``SESSION_EXPIRY_TIMEZONE`` is unset and
  no broker session exists (T-08).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_SERVER_PATH = REPO_ROOT / "mcp" / "mcpserver.py"


def _is_india_broker_function() -> ast.FunctionDef:
    """Return the AST node for ``_is_india_broker`` in the script.

    The script can't be imported because the top-level ``mcp``
    namespace is owned by the installed FastMCP package. Instead we
    parse the AST and assert the rewrite happened by structural
    inspection. This is the same technique
    ``test_lane_isolation.py`` already uses for files it cannot
    import.
    """
    tree = ast.parse(MCP_SERVER_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_is_india_broker":
            return node
    raise AssertionError("_is_india_broker not found in mcp/mcpserver.py")


def test_t05_mcp_is_india_broker_no_longer_returns_true_on_none_caps() -> None:
    """The two prior `return True` branches in `_is_india_broker`
    have been replaced with `raise MissingRegionContext`. Verify
    via AST inspection (the file cannot be imported because the
    `mcp` namespace is owned by the installed FastMCP package)."""
    func = _is_india_broker_function()
    # Count Raise statements that mention MissingRegionContext.
    raise_count = 0
    for node in ast.walk(func):
        if isinstance(node, ast.Raise) and node.exc is not None:
            # node.exc is an ast.Call to MissingRegionContext(...)
            if isinstance(node.exc, ast.Call) and isinstance(node.exc.func, ast.Name):
                if node.exc.func.id == "MissingRegionContext":
                    raise_count += 1
    assert raise_count == 2, (
        f"Phase 1 T-05: _is_india_broker should raise MissingRegionContext "
        f"on both fallback branches; found {raise_count} raise(s)"
    )

    # And exactly one Return — the final `return "india" in regions`.
    returns = [n for n in ast.walk(func) if isinstance(n, ast.Return)]
    assert len(returns) == 1, (
        f"_is_india_broker should have exactly 1 `return` after T-05; "
        f"found {len(returns)}"
    )


def test_t05_mcp_is_india_broker_uses_attempted_sources_for_diagnostics() -> None:
    """The MissingRegionContext raised in T-05 carries
    attempted_sources for debuggability."""
    func = _is_india_broker_function()
    text = ast.unparse(func)
    assert "attempted_sources" in text, (
        "Phase 1 T-05: MissingRegionContext should carry attempted_sources"
    )


def test_t07_venue_local_offset_seconds_none_raises_venue_resolution_error() -> None:
    from database.venue_offset import venue_local_offset_seconds
    from domain.errors import VenueResolutionError

    with pytest.raises(VenueResolutionError):
        venue_local_offset_seconds(None)
    with pytest.raises(VenueResolutionError):
        # Default param is None → also raises.
        venue_local_offset_seconds()


def test_t07_venue_local_offset_seconds_india_venues_unchanged() -> None:
    """India venues remain bit-identical at 19800."""
    from database.venue_offset import venue_local_offset_seconds

    for venue in ("NSE", "BSE", "NFO", "BFO", "CDS", "MCX", "NSE_INDEX", "BSE_INDEX", "BCD"):
        assert venue_local_offset_seconds(venue) == 19800, (
            f"India venue {venue!r} offset drifted from 19800"
        )


def test_t08_session_tz_bootstrap_returns_utc_not_kolkata(monkeypatch) -> None:
    """When no broker session and no env var, _session_tz returns UTC.

    Phase 1 T-08: previously this branch returned ``Asia/Kolkata``.
    Now it returns ``UTC`` so non-India operators can come up
    cleanly without inheriting the Indian default.
    """
    monkeypatch.delenv("SESSION_EXPIRY_TIMEZONE", raising=False)

    from utils import session as utils_session

    # Force the "no broker session" branch by stubbing the resolver.
    monkeypatch.setattr(utils_session, "_resolve_active_broker_caps", lambda: None)
    # Reset the one-shot warned flag so we hit the warning path.
    if hasattr(utils_session._session_tz, "_bootstrap_warned"):
        delattr(utils_session._session_tz, "_bootstrap_warned")

    tz = utils_session._session_tz()
    assert tz.zone == "UTC", f"bootstrap default tz drifted from UTC to {tz.zone!r}"


def test_t08_session_tz_active_india_broker_still_uses_kolkata(monkeypatch) -> None:
    """India broker resolution path still returns Asia/Kolkata."""
    monkeypatch.delenv("SESSION_EXPIRY_TIMEZONE", raising=False)

    from utils import session as utils_session

    class _Caps:
        supported_regions = ["india"]

    monkeypatch.setattr(utils_session, "_resolve_active_broker_caps", lambda: _Caps())

    tz = utils_session._session_tz()
    assert tz.zone == "Asia/Kolkata", (
        f"India broker tz drifted from Asia/Kolkata to {tz.zone!r}"
    )


def test_t06_frontend_helper_is_documented_in_test_suite() -> None:
    """T-06 is a frontend (TypeScript) change — it lives in
    frontend/src/india_legacy/hooks/useSupportedExchanges.ts (relocated
    in v9-bis to the india_legacy/ subtree). This Python test only
    asserts the file ships the new fail-closed text so backend CI
    catches accidental reverts. Frontend behavior is covered by the
    Vitest suite under frontend/src/india_legacy/hooks/.
    """
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    hook = (
        repo_root
        / "frontend"
        / "src"
        / "india_legacy"
        / "hooks"
        / "useSupportedExchanges.ts"
    )
    body = hook.read_text(encoding="utf-8")
    assert "if (cap == null) return false" in body, (
        "Phase 1 T-06 frontend fail-closed return false (cap null) missing"
    )
    assert "if (regions.length === 0) return false" in body, (
        "Phase 1 T-06 frontend fail-closed return false (empty regions) missing"
    )
