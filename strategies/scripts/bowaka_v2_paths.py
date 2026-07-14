#!/usr/bin/env python3
"""Bowaka v2 — single source of truth for output paths.

All v2 outputs live under ``data/bowaka_v2/<subdir>/`` (mirrors v1's
``data/paper/<subdir>/`` layout). The repo root is resolved the same
way v1's ``bowaka_strategy._resolve_path`` does — anchor on the
strategies/scripts directory and walk up two levels.

Importing this module is a pure side-effect-free operation. Path
constants are computed once at import time so callers can use them
as drop-in path literals.
"""
from __future__ import annotations

from pathlib import Path

# strategies/scripts/bowaka_v2_paths.py -> repo root
_THIS_FILE = Path(__file__).resolve()
_SCRIPTS_DIR = _THIS_FILE.parent
REPO_ROOT = _SCRIPTS_DIR.parent.parent

_DATA_ROOT = REPO_ROOT / "strategies" / "scripts" / "data" / "bowaka_v2"
_LOGS_ROOT = REPO_ROOT / "logs"


# ---- Core ------------------------------------------------------------

UNIVERSE_SNAPSHOT_PATH      = _DATA_ROOT / "universe_snapshot.json"
DAILY_FEATURE_CACHE_PATH    = _DATA_ROOT / "daily_feature_cache.parquet"
VOLUME_CURVE_PATH           = _DATA_ROOT / "volume_curve.parquet"
CANDIDATE_EVENTS_PATH       = _DATA_ROOT / "candidate_events.jsonl"
ENTRY_DECISIONS_PATH        = _DATA_ROOT / "entry_decisions.jsonl"
V2_STATE_PATH               = _DATA_ROOT / "state.json"
V2_LEDGER_PATH              = _DATA_ROOT / "trade_ledger.jsonl"
V2_DAILY_SUMMARY_PATH       = _DATA_ROOT / "daily_summary.jsonl"
V2_LOG_PATH                 = _LOGS_ROOT / "bowaka_v2_strategy.log"

# ---- Observability (v1 parity) ---------------------------------------

REJECTED_CANDIDATES_PATH    = _DATA_ROOT / "rejected_candidates.jsonl"
ORDER_EXEC_QUALITY_PATH     = _DATA_ROOT / "order_execution_quality.jsonl"
PROTECTION_EVENTS_PATH      = _DATA_ROOT / "protection_events.jsonl"
SHADOW_RISK_PATH            = _DATA_ROOT / "shadow_risk_controls.jsonl"
COUNTERFACTUAL_ENTRIES_PATH = _DATA_ROOT / "counterfactual_entries.jsonl"
COUNTERFACTUAL_EXITS_PATH   = _DATA_ROOT / "counterfactual_exits.jsonl"
CONFIG_SNAPSHOTS_DIR        = _DATA_ROOT / "config_snapshots"
CANDIDATE_MINUTE_BARS_DIR   = _DATA_ROOT / "candidate_bars"
PER_POSITION_TICKS_DIR      = _DATA_ROOT / "ticks"
LIQUIDITY_MONITOR_PATH      = _DATA_ROOT / "liquidity_monitor.jsonl"
SCANNER_HEARTBEAT_PATH      = _DATA_ROOT / "scanner_heartbeat.jsonl"
SCANNER_STATE_PATH          = _DATA_ROOT / "scanner_state.json"
SCANNER_GATE_DUMP_PATH      = _DATA_ROOT / "scanner_gate_dump.jsonl"
GATE_DUMP_ARCHIVE_DIR       = _DATA_ROOT / "gate_dump_archive"

# ---- Backtest / replay outputs ---------------------------------------

BACKTEST_REPORTS_DIR        = _DATA_ROOT / "backtest_reports"
COUNTERFACTUAL_REPORTS_DIR  = _DATA_ROOT / "counterfactual_reports"
REPLAY_REPORTS_DIR          = _DATA_ROOT / "replay_reports"


def ensure_dirs() -> None:
    """Create every v2 directory used by the strategy. Safe to call
    repeatedly; idempotent. Callers should invoke this once at
    process startup so the per-event open(O_APPEND) paths don't fail
    on a missing parent directory."""
    for p in (
        _DATA_ROOT, _LOGS_ROOT,
        CONFIG_SNAPSHOTS_DIR, CANDIDATE_MINUTE_BARS_DIR,
        PER_POSITION_TICKS_DIR,
        BACKTEST_REPORTS_DIR, COUNTERFACTUAL_REPORTS_DIR,
        REPLAY_REPORTS_DIR,
    ):
        p.mkdir(parents=True, exist_ok=True)


__all__ = [
    "REPO_ROOT",
    "UNIVERSE_SNAPSHOT_PATH",
    "DAILY_FEATURE_CACHE_PATH",
    "VOLUME_CURVE_PATH",
    "CANDIDATE_EVENTS_PATH",
    "ENTRY_DECISIONS_PATH",
    "V2_STATE_PATH",
    "V2_LEDGER_PATH",
    "V2_DAILY_SUMMARY_PATH",
    "V2_LOG_PATH",
    "REJECTED_CANDIDATES_PATH",
    "ORDER_EXEC_QUALITY_PATH",
    "PROTECTION_EVENTS_PATH",
    "SHADOW_RISK_PATH",
    "COUNTERFACTUAL_ENTRIES_PATH",
    "COUNTERFACTUAL_EXITS_PATH",
    "CONFIG_SNAPSHOTS_DIR",
    "CANDIDATE_MINUTE_BARS_DIR",
    "PER_POSITION_TICKS_DIR",
    "LIQUIDITY_MONITOR_PATH",
    "SCANNER_HEARTBEAT_PATH",
    "SCANNER_STATE_PATH",
    "SCANNER_GATE_DUMP_PATH",
    "GATE_DUMP_ARCHIVE_DIR",
    "BACKTEST_REPORTS_DIR",
    "COUNTERFACTUAL_REPORTS_DIR",
    "REPLAY_REPORTS_DIR",
    "ensure_dirs",
]
