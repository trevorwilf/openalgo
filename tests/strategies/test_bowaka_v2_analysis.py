"""Phase 5 — v2 analysis tests."""
from __future__ import annotations

import pytest

import bowaka_v2_analysis as ana


def test_analysis_consumes_v2_ledger():
    ledger = [
        {"event_type": "closure", "session_date": "2026-05-15",
         "payload": {"reason": "target_hit", "realized_pnl": 200.0}},
        {"event_type": "closure", "session_date": "2026-05-15",
         "payload": {"reason": "stop_hit", "realized_pnl": -100.0}},
        {"event_type": "closure", "session_date": "2026-05-14",
         "payload": {"reason": "time_stop", "realized_pnl": -10.0}},
    ]
    decisions = [
        {"session_date": "2026-05-15", "decision": "accepted"},
        {"session_date": "2026-05-15", "decision": "rejected",
         "reason": "spread_too_wide"},
    ]
    summary = ana.build_daily_summary(
        "2026-05-15", ledger=ledger, decisions=decisions,
    )
    assert summary["closures"]["count"] == 2
    assert summary["closures"]["total_realized_pnl"] == pytest.approx(100.0)
    assert summary["closures"]["by_reason"]["target_hit"] == 1
    assert summary["closures"]["by_reason"]["stop_hit"] == 1
    assert summary["decisions"]["accepted"] == 1
    assert summary["decisions"]["rejected"] == 1
    assert summary["decisions"]["by_rejection_reason"]["spread_too_wide"] == 1
