"""Phase 6 — replay tool tests."""
from __future__ import annotations

import pandas as pd
import pytest

import bowaka_v2_replay as rp


def test_replay_byte_identical_to_live_run():
    """A replay with the matching config_hash + universe_hash
    produces a clean report — no drift detected."""
    universe = {
        "config_hash": "sha256:abc",
        "universe_hash": "sha256:def",
        "symbols": [{"symbol": "AAA"}],
    }
    rep = rp.replay_session(
        "2026-05-15",
        universe_snapshot=universe,
        daily_cache=pd.DataFrame(),
        bars_supplier=lambda s, t: pd.DataFrame(),
        expected_config_hash="sha256:abc",
    )
    assert rep["drift_detected"] is False
    assert rep["replay_complete"] is True


def test_replay_detects_config_drift():
    universe = {
        "config_hash": "sha256:abc",
        "universe_hash": "sha256:def",
        "symbols": [],
    }
    rep = rp.replay_session(
        "2026-05-15",
        universe_snapshot=universe,
        daily_cache=pd.DataFrame(),
        bars_supplier=lambda s, t: pd.DataFrame(),
        expected_config_hash="sha256:THIS_IS_WRONG",
    )
    assert rep["drift_detected"] is True
    assert rep["expected_config_hash"] != rep["actual_config_hash"]
