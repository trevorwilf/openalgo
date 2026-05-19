"""Phase 4 — v1 erasure assertions.

The v2 strategy entry path (bowaka_v2_strategy.py) MUST NOT
reference v1 entry-discovery symbols. v1 reusable code is imported
under the alias ``_v1_reuse`` for adv_tier_cap / ledger / OCO
plumbing — that's the only legitimate v1 surface.
"""
from __future__ import annotations

from pathlib import Path


_V2_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "strategies" / "scripts" / "bowaka_v2_strategy.py"
)


def _source() -> str:
    return _V2_SOURCE.read_text(encoding="utf-8")


def test_no_run_session_entry_pass_symbol():
    src = _source()
    # The v2 strategy MUST NOT call the v1 once-per-day entry pass.
    assert "run_session_entry_pass" not in src, (
        "bowaka_v2_strategy.py must not reference run_session_entry_pass"
    )


def test_no_in_play_candidates_path():
    src = _source()
    assert "in_play_candidates.json" not in src, (
        "bowaka_v2_strategy.py must not read v1's in_play_candidates.json"
    )


def test_no_session_date_once_per_day_gate():
    src = _source()
    # The v1 sentinel: state["session_date"] != today_iso.
    assert 'state["session_date"] != today_iso' not in src
    assert "state['session_date'] != today_iso" not in src


def test_no_prefilter_handshake_call():
    """The v2 strategy doesn't call verify_prefilter_handshake — the
    universe builder + scanner handle the equivalent contract by
    sharing bowaka_v2_features."""
    src = _source()
    assert "verify_prefilter_handshake" not in src
