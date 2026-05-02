"""Phase 2 T-11 — byte-identical relocation of MIS auto-square-off
rules.

The square-off times for India MIS positions lived as default-value
literals in ``sandbox/squareoff_manager.py`` (read via
``get_config(..., default)``). Phase 2 T-11 relocates the table to
``market_regions/india/squareoff.py``. This test pins the relocated
data so future drift fails loudly.
"""

from __future__ import annotations

from market_regions.india.squareoff import MANDATORY_CLOSE_RULES


# Snapshot taken from sandbox/squareoff_manager.py defaults at the
# moment of relocation:
#   nse_bse_square_off_time = 15:15  (covers NSE / BSE / NFO / BFO)
#   cds_bcd_square_off_time = 16:45  (covers CDS / BCD)
#   mcx_square_off_time     = 23:30  (covers MCX)
#   ncdex_square_off_time   = 17:00  (covers NCDEX)
EXPECTED_SQUAREOFF_RULES: list[tuple[str, str, tuple[str, ...]]] = [
    ("NSE", "15:15", ("MIS",)),
    ("BSE", "15:15", ("MIS",)),
    ("NFO", "15:15", ("MIS",)),
    ("BFO", "15:15", ("MIS",)),
    ("CDS", "16:45", ("MIS",)),
    ("BCD", "16:45", ("MIS",)),
    ("MCX", "23:30", ("MIS",)),
    ("NCDEX", "17:00", ("MIS",)),
]


def test_squareoff_rule_count():
    assert len(MANDATORY_CLOSE_RULES) == len(EXPECTED_SQUAREOFF_RULES), (
        f"MANDATORY_CLOSE_RULES has {len(MANDATORY_CLOSE_RULES)} "
        f"entries; snapshot expects {len(EXPECTED_SQUAREOFF_RULES)}."
    )


def test_squareoff_rules_byte_identical():
    actual = [
        (rule["venue"], rule["local_close"], tuple(rule["applies_to"]))
        for rule in MANDATORY_CLOSE_RULES
    ]
    assert actual == EXPECTED_SQUAREOFF_RULES, (
        "MANDATORY_CLOSE_RULES drifted from the relocation snapshot. "
        "If you intend to change a square-off time, update the legacy "
        "sandbox/squareoff_manager.py defaults *and* the snapshot in "
        "this test in the same commit."
    )


def test_legacy_squareoff_defaults_still_match():
    """The legacy ``SquareOffManager.__init__`` reads HH:MM defaults
    from ``get_config(...)``. The default values it passes must match
    the relocated table — drift would mean two sources of truth."""
    from sandbox.squareoff_manager import SquareOffManager

    # SquareOffManager doesn't expose the defaults directly; we check
    # by reading the source. This test prevents someone from changing
    # the defaults in one place but not the other.
    import inspect

    src = inspect.getsource(SquareOffManager.__init__)
    for venue, hhmm, _ in EXPECTED_SQUAREOFF_RULES:
        assert hhmm in src, (
            f"squareoff_manager.SquareOffManager.__init__ no longer "
            f"references the {venue} default {hhmm!r}; "
            "market_regions.india.squareoff has it but the legacy "
            "manager fell out of sync."
        )
