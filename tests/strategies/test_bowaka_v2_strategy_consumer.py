"""Phase 4 — v2 strategy event consumer."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import bowaka_v2_strategy as v2
import bowaka_v2_schemas as schemas


def _candidate(symbol: str, *, session_date: str = "2026-05-18",
                expiry: str = "2026-05-19T00:00:00Z",
                scan_ts: str = "2026-05-18T14:35:00Z") -> dict:
    return {
        "schema_version": schemas.CANDIDATE_EVENT_SCHEMA_VERSION,
        "strategy": "bowaka_v2",
        "event_type": "candidate_signal",
        "event_id": f"bowaka_v2:{session_date}:{symbol}:{scan_ts}",
        "generated_at": scan_ts,
        "session_date": session_date,
        "scan_timestamp": scan_ts,
        "provider": "alpaca",
        "data_feed": "iex",
        "bar_interval": "1m",
        "config_hash": "sha256:test",
        "universe_hash": "sha256:test",
        "symbol": symbol,
        "exchange": "NASDAQ",
        "venue_code": "XNAS",
        "instrument_class": "operating_equity",
        "eligible_for_bowaka_equity_bucket": True,
        "prior_daily_baselines": {
            "prior_close": 7.42, "avg_volume_20d": 450000,
            "avg_dollar_volume_20d": 3_000_000,
            "prior_atr_14d": 0.52, "prior_atr_pct": 0.0701,
            "ema_10_prior": 7.18, "ema_10_lag_3": 7.04,
            "ema_slope_prior": 0.0199,
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
            "gap_pct": 0.0256, "current_return_pct": 0.1482,
            "range_expansion_so_far": 1.346,
            "close_location_so_far": 0.871,
            "ema_distance": 0.128, "ema_slope": 0.0199,
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
        "signal_expiry_timestamp": expiry,
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
        "execution": {
            "parent_order_style": "market",
            "quote_gate": {"enabled": True, "max_spread_pct": 0.05,
                            "max_quote_age_seconds": 30,
                            "require_bid_ask_positive": True},
            "price_chase_gate": {"enabled": True,
                                  "max_pct_above_signal_price": 0.10,
                                  "min_pct_below_signal_price": -0.03},
            "halt_gate": {"enabled": True,
                           "block_on_halt_or_pending_review": True,
                           "block_on_recent_luld_pause": True},
        },
        "sizing": {
            "sizing_mode": "equal_slice",
            "bankroll_fixed_dollars": 90000,
            "max_concurrent_positions": 18,
            "equal_slice_bankroll_fraction": 0.80,
            "min_order_notional": 500,
        },
        "risk": {
            "daily_loss_pct": 0.03, "max_gross_exposure_pct": 0.80,
            "max_total_entries_per_day": 10,
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
            "persist_config_snapshot": False,
        },
    }


@pytest.fixture(autouse=True)
def _redirect_v2_paths(tmp_path, monkeypatch):
    """Redirect v2 logging paths to tmp_path for each test."""
    import bowaka_v2_paths as p
    monkeypatch.setattr(p, "ENTRY_DECISIONS_PATH",
                         tmp_path / "entry_decisions.jsonl")
    monkeypatch.setattr(p, "REJECTED_CANDIDATES_PATH",
                         tmp_path / "rejected_candidates.jsonl")
    monkeypatch.setattr(p, "ORDER_EXEC_QUALITY_PATH",
                         tmp_path / "order_exec_quality.jsonl")
    monkeypatch.setattr(p, "PROTECTION_EVENTS_PATH",
                         tmp_path / "protection_events.jsonl")
    monkeypatch.setattr(p, "SHADOW_RISK_PATH",
                         tmp_path / "shadow_risk.jsonl")
    monkeypatch.setattr(p, "COUNTERFACTUAL_ENTRIES_PATH",
                         tmp_path / "counterfactual_entries.jsonl")
    monkeypatch.setattr(p, "COUNTERFACTUAL_EXITS_PATH",
                         tmp_path / "counterfactual_exits.jsonl")
    monkeypatch.setattr(p, "LIQUIDITY_MONITOR_PATH",
                         tmp_path / "liquidity_monitor.jsonl")
    monkeypatch.setattr(p, "CONFIG_SNAPSHOTS_DIR",
                         tmp_path / "config_snapshots")


def _write_candidates(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")


# ---- new-lines-only consumer -----------------------------------------


def test_consumer_reads_new_lines_only(tmp_path):
    cfg = _cfg(tmp_path)
    cand_path = Path(cfg["paths"]["candidate_events_path"])
    state = {"last_consumed_event_offset": 0, "entered_today": [],
             "daily_entries_count": 0, "open_positions": {}}
    _write_candidates(cand_path, [
        _candidate("AAA"),
        _candidate("BBB"),
        _candidate("CCC"),
    ])
    s1 = v2.consume_candidate_events(state, cfg, today_iso="2026-05-18", now_utc=datetime(
        2026, 5, 18, 19, 0, tzinfo=timezone.utc,
    ))
    assert s1["consumed"] == 3
    # Append two more.
    _write_candidates(cand_path, [
        _candidate("DDD"),
        _candidate("EEE"),
    ])
    s2 = v2.consume_candidate_events(state, cfg, today_iso="2026-05-18", now_utc=datetime(
        2026, 5, 18, 19, 5, tzinfo=timezone.utc,
    ))
    assert s2["consumed"] == 2


def test_consumer_drops_expired_signals(tmp_path):
    cfg = _cfg(tmp_path)
    cand_path = Path(cfg["paths"]["candidate_events_path"])
    state = {"last_consumed_event_offset": 0, "entered_today": [],
             "daily_entries_count": 0, "open_positions": {}}
    expired = _candidate(
        "AAA", expiry="2026-05-18T14:40:00Z",
        scan_ts="2026-05-18T14:35:00Z",
    )
    _write_candidates(cand_path, [expired])
    s = v2.consume_candidate_events(
        state, cfg, today_iso="2026-05-18",
        now_utc=datetime(2026, 5, 18, 20, 0, tzinfo=timezone.utc),
    )
    assert s["expired"] == 1
    # entry_decision reason: lost_signal_before_entry.
    import bowaka_v2_paths as p
    lines = p.ENTRY_DECISIONS_PATH.read_text().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["decision"] == "rejected"
    assert rec["reason"] == "lost_signal_before_entry"


def test_consumer_dedupes_same_symbol(tmp_path):
    cfg = _cfg(tmp_path)
    cand_path = Path(cfg["paths"]["candidate_events_path"])
    state = {
        "last_consumed_event_offset": 0,
        "entered_today": ["AAA"],  # already entered today
        "daily_entries_count": 1, "open_positions": {},
    }
    _write_candidates(cand_path, [_candidate("AAA")])
    s = v2.consume_candidate_events(
        state, cfg, today_iso="2026-05-18",
        now_utc=datetime(2026, 5, 18, 19, 0, tzinfo=timezone.utc),
    )
    assert s["dedupe"] == 1
    import bowaka_v2_paths as p
    rec = json.loads(p.ENTRY_DECISIONS_PATH.read_text().splitlines()[0])
    assert rec["reason"] == "same_symbol_already_entered_today"


def test_consumer_invalid_schema_logged_and_dropped(tmp_path):
    cfg = _cfg(tmp_path)
    cand_path = Path(cfg["paths"]["candidate_events_path"])
    state = {"last_consumed_event_offset": 0, "entered_today": [],
             "daily_entries_count": 0, "open_positions": {}}
    cand_path.parent.mkdir(parents=True, exist_ok=True)
    # Write malformed JSON + a schema-invalid event.
    cand_path.write_text(
        "not a json object\n"
        + json.dumps({"schema_version": 99, "event_type": "wrong"}) + "\n",
    )
    s = v2.consume_candidate_events(
        state, cfg, today_iso="2026-05-18",
        now_utc=datetime(2026, 5, 18, 19, 0, tzinfo=timezone.utc),
    )
    # Malformed line dropped at tail; one schema-invalid event counted.
    assert s["invalid"] >= 1
    assert s["accepted"] == 0


def test_consumer_writes_entry_decision_for_every_event(tmp_path):
    cfg = _cfg(tmp_path)
    cand_path = Path(cfg["paths"]["candidate_events_path"])
    state = {"last_consumed_event_offset": 0, "entered_today": [],
             "daily_entries_count": 0, "open_positions": {}}
    # 1 accept + 1 expired-rejected.
    _write_candidates(cand_path, [
        _candidate("AAA"),
        _candidate("BBB", expiry="2026-05-18T14:40:00Z"),
    ])
    v2.consume_candidate_events(
        state, cfg, today_iso="2026-05-18",
        now_utc=datetime(2026, 5, 18, 20, 0, tzinfo=timezone.utc),
    )
    import bowaka_v2_paths as p
    decisions = p.ENTRY_DECISIONS_PATH.read_text().splitlines()
    assert len(decisions) == 2
    decisions_parsed = [json.loads(l) for l in decisions]
    decisions_by_symbol = {d["symbol"]: d for d in decisions_parsed}
    assert decisions_by_symbol["AAA"]["decision"] == "accepted"
    assert decisions_by_symbol["BBB"]["decision"] == "rejected"
