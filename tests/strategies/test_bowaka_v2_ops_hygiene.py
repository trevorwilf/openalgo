"""Hardening Phase 7 — ops & hygiene.

Covers:
- bowaka_log_rotate: size-based copytruncate rotation with gzipped
  generations and keep-N pruning,
- scanner incremental dedupe hydrate (byte-offset, partial-line safe,
  truncation reset),
- the pure cadence-sleep helper.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

import bowaka_intraday_scanner as scanner
import bowaka_log_rotate as rot


# ---- log rotation -----------------------------------------------------------


def _mk_log(path: Path, size: int) -> None:
    path.write_bytes(b"x" * size)


def test_rotate_skips_small_files(tmp_path):
    p = tmp_path / "bowaka_v2_strategy.err.log"
    _mk_log(p, 1000)
    assert rot.rotate_file(p, max_bytes=5000, keep=3) is False
    assert p.stat().st_size == 1000
    assert not (tmp_path / "bowaka_v2_strategy.err.log.1.gz").exists()


def test_rotate_truncates_and_gzips(tmp_path):
    p = tmp_path / "bowaka_v2_strategy.err.log"
    p.write_bytes(b"line-one\nline-two\n" * 1000)
    original = p.read_bytes()
    assert rot.rotate_file(p, max_bytes=100, keep=3) is True
    assert p.stat().st_size == 0                  # truncated in place
    gz1 = tmp_path / "bowaka_v2_strategy.err.log.1.gz"
    assert gz1.exists()
    with gzip.open(gz1, "rb") as fh:
        assert fh.read() == original


def test_rotate_keeps_n_generations(tmp_path):
    p = tmp_path / "bowaka_v2_strategy.err.log"
    for gen in (b"GEN1", b"GEN2", b"GEN3", b"GEN4"):
        p.write_bytes(gen * 100)
        assert rot.rotate_file(p, max_bytes=10, keep=3) is True
    names = sorted(x.name for x in tmp_path.glob("*.gz"))
    assert names == [
        "bowaka_v2_strategy.err.log.1.gz",
        "bowaka_v2_strategy.err.log.2.gz",
        "bowaka_v2_strategy.err.log.3.gz",
    ]
    # Newest generation is the last-rotated content; the very first
    # (GEN1) fell off the end.
    with gzip.open(tmp_path / "bowaka_v2_strategy.err.log.1.gz") as fh:
        assert fh.read() == b"GEN4" * 100
    with gzip.open(tmp_path / "bowaka_v2_strategy.err.log.3.gz") as fh:
        assert fh.read() == b"GEN2" * 100


def test_rotate_all_targets_err_and_out_only(tmp_path):
    big = b"y" * 2000
    (tmp_path / "bowaka_v2_strategy.err.log").write_bytes(big)
    (tmp_path / "bowaka_v2_scanner.out.log").write_bytes(big)
    (tmp_path / "bowaka_v2_strategy.log").write_bytes(big)   # not a target
    (tmp_path / "unrelated.err.log").write_bytes(big)        # not a target
    n = rot.rotate_all(tmp_path, max_bytes=1000, keep=3)
    assert n == 2
    assert (tmp_path / "bowaka_v2_strategy.log").stat().st_size == 2000
    assert (tmp_path / "unrelated.err.log").stat().st_size == 2000


def test_rotate_dry_run_writes_nothing(tmp_path):
    p = tmp_path / "bowaka_v2_strategy.err.log"
    p.write_bytes(b"z" * 2000)
    n = rot.rotate_all(tmp_path, max_bytes=1000, keep=3, dry_run=True)
    assert n == 0
    assert p.stat().st_size == 2000
    assert list(tmp_path.glob("*.gz")) == []


def test_rotate_main_missing_dir_is_clean(tmp_path):
    assert rot.main(["--log-dir", str(tmp_path / "nope")]) == 0


# ---- incremental dedupe hydrate ---------------------------------------------


def _decision(symbol: str, decision: str = "accepted",
              session: str = "2026-07-14") -> str:
    return json.dumps({
        "session_date": session, "decision": decision, "symbol": symbol,
    }) + "\n"


@pytest.fixture()
def decisions_path(tmp_path, monkeypatch) -> Path:
    import bowaka_v2_paths as p
    path = tmp_path / "entry_decisions.jsonl"
    monkeypatch.setattr(p, "ENTRY_DECISIONS_PATH", path)
    return path


def test_hydrate_reads_only_new_lines(decisions_path):
    decisions_path.write_text(_decision("AAA"), encoding="utf-8")
    state: dict = {}
    scanner.hydrate_entered_symbols_from_decisions(state, "2026-07-14")
    assert state["entered_symbols_today"] == ["AAA"]
    first_offset = state["entry_decisions_offset"]
    assert first_offset == decisions_path.stat().st_size

    # Append a new accepted entry — only the delta is read.
    with open(decisions_path, "a", encoding="utf-8") as f:
        f.write(_decision("BBB"))
    scanner.hydrate_entered_symbols_from_decisions(state, "2026-07-14")
    assert state["entered_symbols_today"] == ["AAA", "BBB"]
    assert state["entry_decisions_offset"] > first_offset


def test_hydrate_noop_when_no_new_bytes(decisions_path):
    decisions_path.write_text(_decision("AAA"), encoding="utf-8")
    state: dict = {}
    scanner.hydrate_entered_symbols_from_decisions(state, "2026-07-14")
    offset = state["entry_decisions_offset"]
    scanner.hydrate_entered_symbols_from_decisions(state, "2026-07-14")
    assert state["entry_decisions_offset"] == offset
    assert state["entered_symbols_today"] == ["AAA"]


def test_hydrate_partial_line_not_consumed(decisions_path):
    """A mid-append line (no trailing newline) must not advance the
    offset — it is re-read complete on the next tick."""
    decisions_path.write_text(_decision("AAA"), encoding="utf-8")
    state: dict = {}
    scanner.hydrate_entered_symbols_from_decisions(state, "2026-07-14")
    offset = state["entry_decisions_offset"]

    partial = _decision("BBB").rstrip("\n")
    with open(decisions_path, "a", encoding="utf-8") as f:
        f.write(partial[: len(partial) // 2])     # torn write
    scanner.hydrate_entered_symbols_from_decisions(state, "2026-07-14")
    assert state["entry_decisions_offset"] == offset
    assert "BBB" not in state["entered_symbols_today"]

    with open(decisions_path, "a", encoding="utf-8") as f:
        f.write(partial[len(partial) // 2:] + "\n")  # completed
    scanner.hydrate_entered_symbols_from_decisions(state, "2026-07-14")
    assert "BBB" in state["entered_symbols_today"]


def test_hydrate_resets_on_truncated_file(decisions_path):
    decisions_path.write_text(
        _decision("AAA") + _decision("BBB"), encoding="utf-8")
    state: dict = {}
    scanner.hydrate_entered_symbols_from_decisions(state, "2026-07-14")
    assert state["entered_symbols_today"] == ["AAA", "BBB"]
    # File rotated/truncated smaller than the stored offset.
    decisions_path.write_text(_decision("CCC"), encoding="utf-8")
    scanner.hydrate_entered_symbols_from_decisions(state, "2026-07-14")
    assert "CCC" in state["entered_symbols_today"]


def test_hydrate_filters_rejections_and_other_sessions(decisions_path):
    decisions_path.write_text(
        _decision("AAA")
        + _decision("REJ", decision="rejected")
        + _decision("OLD", session="2026-07-11"),
        encoding="utf-8",
    )
    state: dict = {}
    scanner.hydrate_entered_symbols_from_decisions(state, "2026-07-14")
    assert state["entered_symbols_today"] == ["AAA"]


# ---- cadence helper -----------------------------------------------------------


def test_cadence_sleep_subtracts_scan_duration():
    assert scanner._cadence_sleep_seconds(60, 10.0) == 50
    assert scanner._cadence_sleep_seconds(60, 0.4) == 60
    # Slow scans floor at 5s — never spin hot, never double the wait.
    assert scanner._cadence_sleep_seconds(60, 58.0) == 5
    assert scanner._cadence_sleep_seconds(60, 120.0) == 5
