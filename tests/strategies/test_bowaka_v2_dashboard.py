"""Phase 6 — dashboard render tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import bowaka_v2_dashboard as dash


def test_dashboard_renders_without_crashing(tmp_path):
    """Snapshot render against a fixture state file."""
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({
        "open_positions": {"AAA": {}, "BBB": {}},
        "gross_exposure_dollars": 32_000,
        "daily_realized_pnl_strategy": -120.0,
    }))
    cand_path = tmp_path / "candidate_events.jsonl"
    cand_path.write_text(json.dumps({
        "symbol": "AAA", "scan_timestamp": "2026-05-18T14:35:00Z",
    }) + "\n")
    dec_path = tmp_path / "entry_decisions.jsonl"
    dec_path.write_text(
        json.dumps({"session_date": "2026-05-18",
                     "decision": "accepted", "symbol": "AAA"}) + "\n"
        + json.dumps({"session_date": "2026-05-18",
                       "decision": "rejected", "symbol": "BBB",
                       "reason": "spread_too_wide"}) + "\n"
    )
    hb_path = tmp_path / "scanner_heartbeat.jsonl"
    hb_path.write_text("")
    snap = dash.build_dashboard_snapshot(
        "2026-05-18",
        state_path=state_path,
        candidates_path=cand_path,
        decisions_path=dec_path,
        heartbeat_path=hb_path,
        kill_flag_dir=tmp_path,
    )
    assert snap["open_positions_count"] == 2
    assert snap["decisions_today"]["accepted"] == 1
    assert snap["decisions_today"]["rejected"] == 1
    assert snap["decisions_today"]["rejection_breakdown"]["spread_too_wide"] == 1
    rendered = dash.render(snap)
    # Must render without exception and include key metrics.
    assert "Bowaka v2 Dashboard" in rendered
    assert "open positions" in rendered
    assert "gross exposure" in rendered.lower()
