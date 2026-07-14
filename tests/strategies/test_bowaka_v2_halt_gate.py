"""Hardening Phase 6 — halt-gate wiring (strategy side).

Covers:
- metadata.status from /api/v2/quotes reaches symbol_status in the
  client's quote normalization,
- _halt_gate blocks halted / pending_review / luld_pause / inactive,
- LULD memory: a pause observed earlier in the session blocks
  re-entry for the rest of the session (block_on_recent_luld_pause),
  purged on rollover,
- crossed-quote proxy rejects with quote_stale,
- once-per-session degraded-halt-detection log marker.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import bowaka_v2_openalgo_client as oa
import bowaka_v2_schemas as schemas
import bowaka_v2_strategy as v2


@pytest.fixture(autouse=True)
def _redirect_v2_paths(tmp_path, monkeypatch):
    import bowaka_v2_paths as p
    monkeypatch.setattr(p, "ENTRY_DECISIONS_PATH",
                        tmp_path / "entry_decisions.jsonl")
    monkeypatch.setattr(p, "REJECTED_CANDIDATES_PATH",
                        tmp_path / "rejected_candidates.jsonl")


_NOW = datetime(2026, 5, 18, 18, 35, tzinfo=timezone.utc)


def _candidate(symbol: str) -> dict:
    scan_ts = "2026-05-18T14:35:00Z"
    return {
        "schema_version": schemas.CANDIDATE_EVENT_SCHEMA_VERSION,
        "strategy": "bowaka_v2", "event_type": "candidate_signal",
        "event_id": f"bowaka_v2:2026-05-18:{symbol}:{scan_ts}",
        "generated_at": scan_ts, "session_date": "2026-05-18",
        "scan_timestamp": scan_ts, "provider": "alpaca",
        "data_feed": "iex", "bar_interval": "1m",
        "config_hash": "sha256:t", "universe_hash": "sha256:t",
        "symbol": symbol, "exchange": "NASDAQ", "venue_code": "XNAS",
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
        "signal_expiry_timestamp": "2026-05-18T23:59:00Z",
    }


def _cfg(tmp_path) -> dict:
    return {
        "strategy": {"mode": "forming_daily_bar_monitor",
                     "environment": "paper"},
        "paths": {
            "candidate_events_path": str(tmp_path / "candidates.jsonl"),
            "trade_ledger_path": str(tmp_path / "trade_ledger.jsonl"),
            "daily_summary_path": str(tmp_path / "daily_summary.jsonl"),
        },
        "data": {"feed": "iex", "allow_non_sip_for_research_only": True},
        "execution": {
            "default_venue_code": "XNAS",
            "parent_order_style": "market",
            "quote_gate": {"enabled": True,
                           "require_bid_ask_positive": True},
            "price_chase_gate": {"enabled": False},
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
        "risk": {"max_total_entries_per_day": 50,
                 "max_gross_exposure_pct": 5.0},
        "exits": {"stop_pct": 0.08, "target_pct": 0.15,
                  "max_hold_days": 3},
        "logging": {"emit_entry_decisions": True,
                    "emit_rejected_candidates": True,
                    **{k: False for k in (
                        "log_order_execution_quality",
                        "log_protection_state",
                        "log_shadow_risk_controls",
                        "log_counterfactual_entries",
                        "log_counterfactual_exits",
                    )}},
    }


def _write(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")


def _fresh_state() -> dict:
    return {"last_consumed_event_offset": 0, "entered_today": [],
            "daily_entries_count": 0, "open_positions": {},
            "gross_exposure_dollars": 0.0}


def _decisions(tmp_path) -> list[dict]:
    import bowaka_v2_paths as p
    if not p.ENTRY_DECISIONS_PATH.exists():
        return []
    return [json.loads(l) for l in
            p.ENTRY_DECISIONS_PATH.read_text().splitlines()]


def _quote(**over) -> dict:
    q = {"bid": 8.10, "ask": 8.12, "mid": 8.11, "spread_pct": 0.002,
         "quote_timestamp": "2026-05-18T18:35:00Z",
         "quote_age_seconds": 1, "symbol_status": None}
    q.update(over)
    return q


# ---- client normalization surfaces metadata.status ------------------------


def test_normalize_quote_reads_metadata_status():
    q = oa._normalize_quote({
        "bid": 8.10, "ask": 8.12, "timestamp": "2026-05-18T18:35:00Z",
        "metadata": {"status": "halted"},
    })
    assert q["symbol_status"] == "halted"


def test_normalize_quote_top_level_status_wins():
    q = oa._normalize_quote({
        "bid": 8.10, "ask": 8.12, "status": "luld_pause",
        "metadata": {"status": "active"},
    })
    assert q["symbol_status"] == "luld_pause"


def test_normalize_quote_no_status_stays_none():
    q = oa._normalize_quote({"bid": 8.10, "ask": 8.12})
    assert q["symbol_status"] is None


# ---- halt gate statuses -----------------------------------------------------


@pytest.mark.parametrize("status", [
    "halted", "pending_review", "luld_pause", "inactive", "HALTED",
])
def test_halt_gate_blocks_halt_statuses(status):
    cfg = {"execution": {"halt_gate": {"enabled": True}}}
    assert v2._halt_gate(status, cfg) == "halt_or_pending_review"


def test_halt_gate_passes_active_and_none():
    cfg = {"execution": {"halt_gate": {"enabled": True}}}
    assert v2._halt_gate("active", cfg) is None
    assert v2._halt_gate(None, cfg) is None


def test_halted_candidate_rejected_end_to_end(tmp_path):
    cfg = _cfg(tmp_path)
    state = _fresh_state()
    _write(Path(cfg["paths"]["candidate_events_path"]),
           [_candidate("AAA")])
    s = v2.consume_candidate_events(
        state, cfg,
        quote_supplier=lambda sym: _quote(symbol_status="halted"),
        submit_supplier=lambda sym, qty: pytest.fail("must not submit"),
        today_iso="2026-05-18", now_utc=_NOW,
    )
    assert s["rejected"] == 1
    assert _decisions(tmp_path)[0]["reason"] == "halt_or_pending_review"
    # The pause is remembered for the session.
    assert "AAA" in state["luld_pauses"]


# ---- LULD memory ------------------------------------------------------------


def test_recent_pause_blocks_even_after_status_clears(tmp_path):
    cfg = _cfg(tmp_path)
    state = _fresh_state()
    state["session_date"] = "2026-05-18"
    state["luld_pauses"] = {"AAA": "2026-05-18T15:00:00Z"}
    _write(Path(cfg["paths"]["candidate_events_path"]),
           [_candidate("AAA")])
    s = v2.consume_candidate_events(
        state, cfg,
        quote_supplier=lambda sym: _quote(symbol_status="active"),
        submit_supplier=lambda sym, qty: pytest.fail("must not submit"),
        today_iso="2026-05-18", now_utc=_NOW,
    )
    assert s["rejected"] == 1
    assert _decisions(tmp_path)[0]["reason"] == "halt_or_pending_review"


def test_pause_memory_purged_on_rollover(tmp_path):
    cfg = _cfg(tmp_path)
    Path(cfg["paths"]["candidate_events_path"]).write_text("")
    state = _fresh_state()
    state["session_date"] = "2026-05-15"
    state["luld_pauses"] = {"AAA": "2026-05-15T15:00:00Z"}
    v2.consume_candidate_events(
        state, cfg, today_iso="2026-05-18", now_utc=_NOW,
    )
    assert "luld_pauses" not in state


def test_recent_pause_gate_respects_flag_off(tmp_path):
    cfg = _cfg(tmp_path)
    cfg["execution"]["halt_gate"]["block_on_recent_luld_pause"] = False
    state = _fresh_state()
    state["session_date"] = "2026-05-18"
    state["luld_pauses"] = {"AAA": "2026-05-18T15:00:00Z"}
    _write(Path(cfg["paths"]["candidate_events_path"]),
           [_candidate("AAA")])
    s = v2.consume_candidate_events(
        state, cfg,
        quote_supplier=lambda sym: _quote(symbol_status="active"),
        submit_supplier=lambda sym, qty: {
            "_http_status": 200, "data": {"order_id": "P-1"}},
        today_iso="2026-05-18", now_utc=_NOW,
    )
    assert s["accepted"] == 1


# ---- crossed / zero quote proxies -------------------------------------------


def test_crossed_quote_rejected_as_stale(tmp_path):
    cfg = _cfg(tmp_path)
    state = _fresh_state()
    _write(Path(cfg["paths"]["candidate_events_path"]),
           [_candidate("AAA")])
    s = v2.consume_candidate_events(
        state, cfg,
        quote_supplier=lambda sym: _quote(bid=8.20, ask=8.10, mid=8.15),
        submit_supplier=lambda sym, qty: pytest.fail("must not submit"),
        today_iso="2026-05-18", now_utc=_NOW,
    )
    assert s["rejected"] == 1
    assert _decisions(tmp_path)[0]["reason"] == "quote_stale"


def test_zero_sided_quote_rejected_as_stale(tmp_path):
    cfg = _cfg(tmp_path)
    state = _fresh_state()
    _write(Path(cfg["paths"]["candidate_events_path"]),
           [_candidate("AAA")])
    s = v2.consume_candidate_events(
        state, cfg,
        quote_supplier=lambda sym: _quote(bid=0.0, mid=None,
                                          spread_pct=None),
        submit_supplier=lambda sym, qty: pytest.fail("must not submit"),
        today_iso="2026-05-18", now_utc=_NOW,
    )
    assert s["rejected"] == 1
    assert _decisions(tmp_path)[0]["reason"] == "quote_stale"


def test_quote_gate_crossed_check_unit():
    cfg = {"execution": {"quote_gate": {"enabled": True}}}
    crossed = {"bid": 8.20, "ask": 8.10, "quote_age_seconds": 1}
    assert v2._quote_gate(crossed, cfg) == "quote_stale"
    normal = {"bid": 8.10, "ask": 8.12, "quote_age_seconds": 1}
    assert v2._quote_gate(normal, cfg) is None


# ---- degraded-detection session log marker -----------------------------------


def test_missing_status_logs_once_per_session(tmp_path):
    cfg = _cfg(tmp_path)
    state = _fresh_state()
    _write(Path(cfg["paths"]["candidate_events_path"]),
           [_candidate("AAA"), _candidate("BBB")])
    v2.consume_candidate_events(
        state, cfg,
        quote_supplier=lambda sym: _quote(symbol_status=None),
        submit_supplier=lambda sym, qty: {
            "_http_status": 200, "data": {"order_id": f"P-{sym}"}},
        today_iso="2026-05-18", now_utc=_NOW,
    )
    assert state["halt_status_unavailable_logged_on"] == "2026-05-18"
