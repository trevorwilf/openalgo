"""Phase 5 (T-21) — capability-driven topic parsing.

The pre-Phase-5 WS router hardcoded ``NSE_INDEX`` / ``BSE_INDEX`` as
the only multi-segment venue codes. Phase 5 generalizes this: the
parser now reads the venue catalog from the loaded region plugins
and identifies any ``venue_code`` containing an underscore as a
multi-segment venue.

The India parity guarantee: the India region plugin declares
``NSE_INDEX`` and ``BSE_INDEX`` venues, so topics like
``NSE_INDEX_NIFTY_LTP`` continue to parse to
``("NSE_INDEX", "NIFTY", "LTP")`` bit-identically.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_caches():
    from utils import region_loader
    from websocket_proxy import server

    region_loader._reset_cache_for_tests()
    server._reset_topic_format_cache_for_tests()
    yield
    region_loader._reset_cache_for_tests()
    server._reset_topic_format_cache_for_tests()


def test_multi_segment_venues_pulled_from_region_plugins():
    from websocket_proxy.server import _multi_segment_venue_codes

    venues = _multi_segment_venue_codes()
    # India region's NSE_INDEX / BSE_INDEX must be discovered.
    assert "NSE_INDEX" in venues
    assert "BSE_INDEX" in venues


def test_multi_segment_venues_sorted_by_length_desc():
    """Longest-prefix-match wins: ensure the cache returns codes
    sorted by length descending so a hypothetical
    ``NSE_INDEX_FUT`` would match before ``NSE_INDEX``."""
    from websocket_proxy.server import _multi_segment_venue_codes

    codes = _multi_segment_venue_codes()
    if len(codes) >= 2:
        for a, b in zip(codes, codes[1:]):
            assert len(a) >= len(b), (
                "multi-segment venue codes must be sorted by length "
                "descending so the longest match wins"
            )


@pytest.mark.parametrize(
    "remaining, expected",
    [
        # Single-segment venues (default split)
        (["NSE", "RELIANCE"], ("NSE", "RELIANCE")),
        (["BSE", "INFY"], ("BSE", "INFY")),
        (["NFO", "NIFTY28MAR2420800CE"], ("NFO", "NIFTY28MAR2420800CE")),
        # Multi-segment venues — India parity
        (["NSE", "INDEX", "NIFTY"], ("NSE_INDEX", "NIFTY")),
        (["BSE", "INDEX", "SENSEX"], ("BSE_INDEX", "SENSEX")),
        # Crypto symbols with embedded underscores stay in the symbol
        # part — CRYPTO is a single-segment venue.
        (["CRYPTO", "SOL", "INR"], ("CRYPTO", "SOL_INR")),
        (["CRYPTO", "BTC", "USDT"], ("CRYPTO", "BTC_USDT")),
    ],
)
def test_split_topic_venue_and_symbol(remaining, expected):
    from websocket_proxy.server import _split_topic_venue_and_symbol

    assert _split_topic_venue_and_symbol(remaining) == expected


def test_topic_parser_no_hardcoded_nse_bse_index():
    """The pre-Phase-5 substring match on ``"NSE"`` / ``"BSE"`` /
    ``"INDEX"`` must be removed from the router. The capability
    helper is the only path."""
    import inspect

    from websocket_proxy import server

    src = inspect.getsource(server)
    # The pre-Phase-5 hardcoded branch had:
    #   remaining[0] in ("NSE", "BSE") and remaining[1] == "INDEX"
    # Phase 5 replaces it with _split_topic_venue_and_symbol() which
    # reads the multi-segment venue cache.
    assert "remaining[0] in (\"NSE\", \"BSE\")" not in src, (
        "websocket_proxy/server.py still has the hardcoded "
        "NSE/BSE substring match — Phase 5 (T-21) requires it to be "
        "replaced with _split_topic_venue_and_symbol()."
    )
    assert "remaining[1] == \"INDEX\"" not in src, (
        "websocket_proxy/server.py still has the hardcoded INDEX "
        "substring match — Phase 5 (T-21) requires it to be "
        "replaced with _split_topic_venue_and_symbol()."
    )
