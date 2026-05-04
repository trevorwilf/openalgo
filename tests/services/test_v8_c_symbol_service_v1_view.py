"""v8-C — services.symbol_service v1 lookup uses the symtoken_v1 view.

The view exists when the operator has run
``upgrade/migrate_symtoken_broker_provenance.py``. Until then the
service silently falls back to the SymToken table — same v1-shaped
output either way.

These tests exercise both branches via ``unittest.mock.patch`` on
the ``_v1_view_is_available`` probe.
"""

from __future__ import annotations

from unittest.mock import patch


def test_view_available_uses_symtokenv1read():
    """When the view exists, the v1 lookup queries SymTokenV1Read."""
    from services import symbol_service

    with patch.object(symbol_service, "_v1_view_is_available", return_value=True):
        # Spy on db_session.query so we can see which class was used.
        seen = []
        original_query = symbol_service.db_session.query

        def capture(*args, **kwargs):
            if args:
                seen.append(args[0].__name__ if hasattr(args[0], "__name__") else str(args[0]))
            return original_query(*args, **kwargs)

        with patch.object(symbol_service.db_session, "query", side_effect=capture):
            symbol_service.get_symbol_info_with_auth(
                "AAPL", "XNAS", auth_token="", broker=""
            )
        # First query call inside get_symbol_info_with_auth must
        # have been against SymTokenV1Read, not SymToken.
        assert seen, "expected at least one db_session.query() call"
        assert seen[0] == "SymTokenV1Read", (
            f"expected first query against SymTokenV1Read, got {seen[0]}"
        )


def test_view_unavailable_falls_back_to_symtoken():
    """Pre-migration: view doesn't exist, lookup hits SymToken."""
    from services import symbol_service

    with patch.object(symbol_service, "_v1_view_is_available", return_value=False):
        seen = []
        original_query = symbol_service.db_session.query

        def capture(*args, **kwargs):
            if args:
                seen.append(args[0].__name__ if hasattr(args[0], "__name__") else str(args[0]))
            return original_query(*args, **kwargs)

        with patch.object(symbol_service.db_session, "query", side_effect=capture):
            symbol_service.get_symbol_info_with_auth(
                "AAPL", "XNAS", auth_token="", broker=""
            )
        assert seen, "expected at least one db_session.query() call"
        assert seen[0] == "SymToken", (
            f"expected fallback to SymToken when view missing, got {seen[0]}"
        )


def test_view_probe_caches_result():
    """``_v1_view_is_available`` probes once and caches forever."""
    from services import symbol_service

    # Reset cache so we can observe the probe path.
    symbol_service._V1_VIEW_AVAILABLE = None
    call_count = {"n": 0}
    original_query = symbol_service.db_session.query

    def counting_query(*args, **kwargs):
        call_count["n"] += 1
        return original_query(*args, **kwargs)

    with patch.object(symbol_service.db_session, "query", side_effect=counting_query):
        a = symbol_service._v1_view_is_available()
        b = symbol_service._v1_view_is_available()
        c = symbol_service._v1_view_is_available()

    assert a == b == c
    # Probe makes exactly one db_session.query call; subsequent
    # calls hit the cached _V1_VIEW_AVAILABLE.
    assert call_count["n"] == 1, (
        f"probe should run exactly once, ran {call_count['n']} times"
    )


def test_env_var_disables_view():
    """OPENALGO_SYMTOKEN_V1_VIEW=0 forces the SymToken fallback."""
    import importlib
    import os

    os.environ["OPENALGO_SYMTOKEN_V1_VIEW"] = "0"
    try:
        from services import symbol_service

        importlib.reload(symbol_service)
        assert symbol_service._USE_V1_VIEW is False
        assert symbol_service._v1_view_is_available() is False
    finally:
        os.environ.pop("OPENALGO_SYMTOKEN_V1_VIEW", None)
        from services import symbol_service as ss

        importlib.reload(ss)
