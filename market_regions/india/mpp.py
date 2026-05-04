"""T-13 (v7 Phase 3-ter) — India MPP slab declarations.

Source-of-truth for India's SEBI-regulated Market Price Protection
slabs. Mirrors ``market_regions.india.legacy_v1.utils.mpp_slab``
for backwards-compatible import paths; new code should reach
these via the active region plugin's ``mpp_slabs()`` accessor
instead of importing this module directly.

The values are SEBI-regulatory and must NOT be changed without
exchange approval.
"""

from __future__ import annotations

# (max_price, protection_percentage). Same values as legacy_v1's
# mpp_slab.py — pinned by parity for India brokers.
INDIA_EQ_FUT_MPP_SLABS: list[tuple[float, float]] = [
    (100, 2.0),
    (500, 1.0),
    (float("inf"), 0.5),
]

INDIA_OPT_MPP_SLABS: list[tuple[float, float]] = [
    (10, 5.0),
    (100, 3.0),
    (500, 2.0),
    (float("inf"), 1.0),
]


def get_india_mpp_slabs(instrument_type: str) -> list[tuple[float, float]]:
    """Return India MPP slab table for the given instrument type.

    Instrument types: ``"CE"`` / ``"PE"`` use options slabs;
    everything else (``"EQ"``, ``"FUT"``) uses the equity/futures
    slabs.
    """
    if instrument_type.upper() in ("CE", "PE"):
        return list(INDIA_OPT_MPP_SLABS)
    return list(INDIA_EQ_FUT_MPP_SLABS)


__all__ = [
    "INDIA_EQ_FUT_MPP_SLABS",
    "INDIA_OPT_MPP_SLABS",
    "get_india_mpp_slabs",
]
