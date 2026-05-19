"""Phase 3 — scanner state file handling tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import bowaka_intraday_scanner as scanner
import bowaka_v2_paths as paths


def test_scanner_state_atomic_write(tmp_path, monkeypatch):
    """Concurrent writes must not produce a corrupted state file —
    save_scanner_state uses tmpfile + rename."""
    monkeypatch.setattr(paths, "SCANNER_STATE_PATH", tmp_path / "state.json")
    # Run two saves back-to-back; final file must be valid JSON.
    scanner.save_scanner_state({"session_date": "2026-05-18", "in_play_pool": {}})
    scanner.save_scanner_state({"session_date": "2026-05-18", "in_play_pool": {"A": 1}})
    on_disk = json.loads((tmp_path / "state.json").read_text())
    assert on_disk["session_date"] == "2026-05-18"
    assert on_disk["in_play_pool"] == {"A": 1}


def test_scanner_state_reads_strategy_entry_decisions(tmp_path, monkeypatch):
    """Scanner state hydration MUST read the strategy's
    entry_decisions.jsonl and populate entered_symbols_today."""
    decisions_path = tmp_path / "entry_decisions.jsonl"
    decisions_path.write_text(
        json.dumps({
            "session_date": "2026-05-18", "symbol": "XYZ",
            "decision": "accepted",
        }) + "\n"
        + json.dumps({
            "session_date": "2026-05-18", "symbol": "ABC",
            "decision": "rejected",
        }) + "\n"
        + json.dumps({
            "session_date": "2026-05-17", "symbol": "OLD",
            "decision": "accepted",
        }) + "\n"
    )
    monkeypatch.setattr(paths, "ENTRY_DECISIONS_PATH", decisions_path)
    state = scanner._empty_state("2026-05-18")
    scanner.hydrate_entered_symbols_from_decisions(state, "2026-05-18")
    assert "XYZ" in state["entered_symbols_today"]
    # ABC was rejected today — not in entered_today.
    assert "ABC" not in state["entered_symbols_today"]
    # OLD is from yesterday — must not bleed in.
    assert "OLD" not in state["entered_symbols_today"]
