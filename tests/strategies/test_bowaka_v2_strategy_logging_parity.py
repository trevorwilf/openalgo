"""Phase 4 — 11 v1-parity logging streams."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import bowaka_v2_strategy as v2
import bowaka_v2_schemas as schemas
import bowaka_v2_paths as paths


def _candidate(symbol: str) -> dict:
    return {
        "schema_version": 3, "strategy": "bowaka_v2",
        "event_type": "candidate_signal",
        "event_id": f"bowaka_v2:2026-05-18:{symbol}:2026-05-18T14:35:00Z",
        "generated_at": "2026-05-18T14:35:00Z",
        "session_date": "2026-05-18",
        "scan_timestamp": "2026-05-18T14:35:00Z",
        "provider": "alpaca", "data_feed": "iex", "bar_interval": "1m",
        "config_hash": "sha256:test", "universe_hash": "sha256:test",
        "symbol": symbol, "exchange": "NASDAQ", "venue_code": "XNAS",
        "instrument_class": "operating_equity",
        "eligible_for_bowaka_equity_bucket": True,
        "prior_daily_baselines": {
            "prior_close": 7.42, "avg_volume_20d": 450000,
            "avg_dollar_volume_20d": 3_000_000,
            "prior_atr_14d": 0.52, "prior_atr_pct": 0.07,
            "ema_10_prior": 7.18, "ema_10_lag_3": 7.04,
            "ema_slope_prior": 0.02,
        },
        "forming_session_bar": {
            "session_open": 7.61, "session_high": 8.20,
            "session_low": 7.50, "last_price": 8.11,
            "session_volume": 820000, "session_range": 0.70,
            "last_bar_timestamp": "2026-05-18T18:34:00Z",
        },
        "intraday_volume_context": {
            "volume_curve_fraction": 0.42,
            "expected_volume_until_scan": 189000,
            "rvol_so_far": 4.34, "projected_full_day_rvol": 4.34,
        },
        "features": {
            "gap_pct": 0.03, "current_return_pct": 0.15,
            "range_expansion_so_far": 1.3,
            "close_location_so_far": 0.87,
            "ema_distance": 0.13, "ema_slope": 0.02,
            "signal_strength": 7.82,
        },
        "gate_results": {
            "price_gate": True, "avg_dollar_volume_gate": True,
            "rvol_gate": True, "prior_atr_pct_gate": True,
            "range_expansion_gate": True, "close_location_gate": True,
            "ema_distance_gate": True, "ema_slope_gate": True,
            "max_gap_gate": True, "instrument_gate": True,
        },
        "candidate_rank": 1,
        "signal_expiry_timestamp": "2026-05-19T00:00:00Z",
    }


def _cfg(tmp_path: Path) -> dict:
    return {
        "strategy": {"mode": "forming_daily_bar_monitor",
                       "environment": "paper"},
        "paths": {
            "candidate_events_path": str(tmp_path / "candidates.jsonl"),
            "state_path": str(tmp_path / "state.json"),
        },
        "data": {"feed": "iex", "allow_non_sip_for_research_only": True},
        "execution": {"parent_order_style": "market"},
        "sizing": {
            "bankroll_fixed_dollars": 90000,
            "max_concurrent_positions": 18,
            "equal_slice_bankroll_fraction": 0.80,
            "min_order_notional": 500,
        },
        "risk": {
            "daily_loss_pct": 0.03, "max_gross_exposure_pct": 0.80,
            "max_total_entries_per_day": 10,
            "shadow": {
                "daily_loss_pct": 0.01,
                "max_gross_exposure_pct": 0.30,
                "max_total_entries_per_day": 1,  # forces shadow hit
            },
        },
        "exits": {"stop_pct": 0.08, "target_pct": 0.15,
                    "max_hold_days": 3},
        "logging": {
            "emit_entry_decisions": True,
            "emit_rejected_candidates": True,
            "log_order_execution_quality": True,
            "log_protection_state": True,
            "log_shadow_risk_controls": True,
            "log_counterfactual_entries": True,
            "log_counterfactual_exits": True,
            "persist_config_snapshot": True,
        },
        "liquidity_monitor": {"enabled": False},
    }


@pytest.fixture(autouse=True)
def _redirect(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "ENTRY_DECISIONS_PATH",
                         tmp_path / "entry_decisions.jsonl")
    monkeypatch.setattr(paths, "REJECTED_CANDIDATES_PATH",
                         tmp_path / "rejected_candidates.jsonl")
    monkeypatch.setattr(paths, "ORDER_EXEC_QUALITY_PATH",
                         tmp_path / "order_exec_quality.jsonl")
    monkeypatch.setattr(paths, "PROTECTION_EVENTS_PATH",
                         tmp_path / "protection_events.jsonl")
    monkeypatch.setattr(paths, "SHADOW_RISK_PATH",
                         tmp_path / "shadow_risk.jsonl")
    monkeypatch.setattr(paths, "COUNTERFACTUAL_ENTRIES_PATH",
                         tmp_path / "counterfactual_entries.jsonl")
    monkeypatch.setattr(paths, "COUNTERFACTUAL_EXITS_PATH",
                         tmp_path / "counterfactual_exits.jsonl")
    monkeypatch.setattr(paths, "LIQUIDITY_MONITOR_PATH",
                         tmp_path / "liquidity_monitor.jsonl")
    monkeypatch.setattr(paths, "CONFIG_SNAPSHOTS_DIR",
                         tmp_path / "config_snapshots")


# ---- per-stream tests -----------------------------------------------


def test_emit_entry_decisions_writes_for_accepted_and_rejected(tmp_path):
    cfg = _cfg(tmp_path)
    v2.emit_entry_decision_v2(cfg, {"decision": "accepted", "x": 1})
    v2.emit_entry_decision_v2(cfg, {"decision": "rejected", "y": 2})
    lines = paths.ENTRY_DECISIONS_PATH.read_text().splitlines()
    assert len(lines) == 2


def test_emit_rejected_candidates_separate_stream(tmp_path):
    cfg = _cfg(tmp_path)
    for r in ("spread_too_wide", "kill_switch", "adv_cap"):
        v2.emit_rejected_candidate(cfg, {"reason": r})
    lines = paths.REJECTED_CANDIDATES_PATH.read_text().splitlines()
    assert len(lines) == 3


def test_log_order_execution_quality(tmp_path):
    cfg = _cfg(tmp_path)
    v2.emit_order_execution_quality(cfg, {
        "submit": {"bid": 8.10, "ask": 8.14},
        "fill": {"price": 8.13, "latency_ms": 22},
    })
    assert paths.ORDER_EXEC_QUALITY_PATH.exists()
    rec = json.loads(paths.ORDER_EXEC_QUALITY_PATH.read_text().splitlines()[0])
    assert "submit" in rec and "fill" in rec


def test_log_protection_state(tmp_path):
    cfg = _cfg(tmp_path)
    for r in ("ok", "retry", "fallback_stop"):
        v2.emit_protection_state(cfg, {"result": r})
    assert len(paths.PROTECTION_EVENTS_PATH.read_text().splitlines()) == 3


def test_log_shadow_risk_records_would_have_blocked(tmp_path):
    cfg = _cfg(tmp_path)
    v2.emit_shadow_risk(cfg, {
        "symbol": "AAA",
        "would_have_blocked": ["shadow_max_entries"],
    })
    rec = json.loads(paths.SHADOW_RISK_PATH.read_text().splitlines()[0])
    assert rec["would_have_blocked"] == ["shadow_max_entries"]


def test_log_counterfactual_entries(tmp_path):
    cfg = _cfg(tmp_path)
    v2.emit_counterfactual_entry(cfg, {
        "order_style": "marketable_limit", "hypothetical_fill": 8.12,
    })
    rec = json.loads(paths.COUNTERFACTUAL_ENTRIES_PATH.read_text().splitlines()[0])
    assert rec["order_style"] == "marketable_limit"


def test_log_counterfactual_exits(tmp_path):
    cfg = _cfg(tmp_path)
    v2.emit_counterfactual_exit(cfg, {
        "variant": "signal_fade_active", "pnl_pct": -0.02,
    })
    rec = json.loads(paths.COUNTERFACTUAL_EXITS_PATH.read_text().splitlines()[0])
    assert rec["variant"] == "signal_fade_active"


def test_persist_config_snapshot_on_startup(tmp_path):
    cfg = _cfg(tmp_path)
    out = v2.persist_config_snapshot(cfg)
    assert out and out.exists()
    rec = json.loads(out.read_text())
    assert "config_hash" in rec
    assert "git_sha" in rec
    assert "redacted_env" in rec
    # API keys redacted.
    for k, v_ in rec["redacted_env"].items():
        if any(s in k.upper() for s in ("KEY", "SECRET", "TOKEN", "PASS")):
            assert v_ == "<REDACTED>"


def test_liquidity_monitor_disabled_emits_nothing(tmp_path):
    cfg = _cfg(tmp_path)
    cfg["liquidity_monitor"]["enabled"] = False
    v2.emit_liquidity_monitor(cfg, {"any": "thing"})
    assert not paths.LIQUIDITY_MONITOR_PATH.exists()


def test_liquidity_monitor_enabled_writes(tmp_path):
    cfg = _cfg(tmp_path)
    cfg["liquidity_monitor"]["enabled"] = True
    v2.emit_liquidity_monitor(cfg, {"spread_pct": 0.05})
    rec = json.loads(paths.LIQUIDITY_MONITOR_PATH.read_text().splitlines()[0])
    assert rec["spread_pct"] == 0.05


def test_log_toggles_off_means_no_writes(tmp_path):
    cfg = _cfg(tmp_path)
    cfg["logging"]["emit_entry_decisions"] = False
    v2.emit_entry_decision_v2(cfg, {"decision": "accepted"})
    assert not paths.ENTRY_DECISIONS_PATH.exists()


def test_all_log_streams_use_atomic_append(tmp_path):
    """Two back-to-back writes produce exactly two well-formed
    JSON lines."""
    cfg = _cfg(tmp_path)
    v2.emit_entry_decision_v2(cfg, {"decision": "accepted", "n": 1})
    v2.emit_entry_decision_v2(cfg, {"decision": "rejected", "n": 2})
    lines = paths.ENTRY_DECISIONS_PATH.read_text().splitlines()
    assert len(lines) == 2
    for l in lines:
        json.loads(l)
