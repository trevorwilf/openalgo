"""Phase 6 — heartbeat monitor tests."""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import bowaka_v2_heartbeat as hb


def test_heartbeat_writes_kill_flag_on_stale_scanner(tmp_path):
    hb_path = tmp_path / "scanner_heartbeat.jsonl"
    hb_path.write_text(json.dumps({
        "ts": "2026-05-18T13:00:00+00:00",
        "scan_timestamp": "2026-05-18T13:00:00+00:00",
        "universe_size": 100,
        "passed_gates_this_scan": 0,
        "emitted_count": 0,
    }) + "\n")
    # Now check at a "current time" that's WAY later than the stamp.
    now = datetime(2026, 5, 18, 14, 0, 0, tzinfo=timezone.utc)
    kf = tmp_path / "KILL_NEW.flag"
    result = hb.check_and_kill(
        hb_path, kf,
        stale_threshold_seconds=60.0,
        now_utc=now,
    )
    assert result["kill_flag_written"] is True
    assert kf.exists()


def test_heartbeat_no_kill_when_recent(tmp_path):
    hb_path = tmp_path / "scanner_heartbeat.jsonl"
    now = datetime(2026, 5, 18, 14, 0, 0, tzinfo=timezone.utc)
    fresh = (now - timedelta(seconds=5)).isoformat()
    hb_path.write_text(json.dumps({"ts": fresh}) + "\n")
    kf = tmp_path / "KILL_NEW.flag"
    result = hb.check_and_kill(
        hb_path, kf, stale_threshold_seconds=60.0,
        now_utc=now,
    )
    assert result["kill_flag_written"] is False
    assert not kf.exists()


def test_heartbeat_writes_kill_when_no_heartbeat_file(tmp_path):
    """File missing entirely = scanner never ran = treat as stale."""
    hb_path = tmp_path / "scanner_heartbeat.jsonl"  # not created
    kf = tmp_path / "KILL_NEW.flag"
    result = hb.check_and_kill(
        hb_path, kf, stale_threshold_seconds=60.0,
        now_utc=datetime(2026, 5, 18, 14, 0, 0, tzinfo=timezone.utc),
    )
    assert result["kill_flag_written"] is True
