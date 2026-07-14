"""Fix Phase 3 — state-machine recovery.

Covers:
- recover_stuck_exit_pending (live children kept, dead children
  cleared + re-attach eligible, missing stamp = stale, fresh lots
  untouched, no partial clearing),
- consume_candidate_events immediate persistence via ``state_path``,
- roll_session_if_needed direct-call semantics (L1-active ticks),
- execute_kill_l2_v2 exposure restore for pending lots,
- signal-fade stamp set only after a successful eval.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import bowaka_v2_schemas as schemas
import bowaka_v2_strategy as v2


@pytest.fixture(autouse=True)
def _redirect_v2_paths(tmp_path, monkeypatch):
    import bowaka_v2_paths as p
    monkeypatch.setattr(p, "PROTECTION_EVENTS_PATH",
                         tmp_path / "protection_events.jsonl")
    monkeypatch.setattr(p, "V2_LEDGER_PATH",
                         tmp_path / "trade_ledger.jsonl")
    monkeypatch.setattr(p, "V2_DAILY_SUMMARY_PATH",
                         tmp_path / "daily_summary.jsonl")


def _cfg(tmp_path):
    return {
        "paths": {
            "trade_ledger_path": str(tmp_path / "trade_ledger.jsonl"),
            "daily_summary_path": str(tmp_path / "daily_summary.jsonl"),
        },
        "execution": {"default_venue_code": "XNAS"},
        "exits": {"stop_pct": 0.05, "target_pct": 0.10,
                  "max_hold_days": 2, "oco_time_in_force": "GTC"},
        "logging": {"log_protection_state": True},
    }


def _ledger_events(tmp_path) -> list[dict]:
    p = tmp_path / "trade_ledger.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in
            p.read_text(encoding="utf-8").splitlines() if line.strip()]


class FakeOA:
    """oa_client surrogate: scriptable order rows + OCO submits."""

    def __init__(self):
        self.order_rows: dict[str, dict] = {}
        self.oco_calls: list[dict] = []
        self.cancel_calls: list[str] = []
        self.oco_response = {
            "_http_status": 200,
            "data": {"native_response": {
                "id": "OCO-NEW",
                "legs": [
                    {"id": "T-NEW", "order_type": "limit"},
                    {"id": "S-NEW", "order_type": "stop"},
                ],
            }},
        }

    def fetch_order(self, http, api_key, order_id):
        return self.order_rows.get(order_id)

    def fetch_all_orders(self, http, api_key):
        return []

    def cancel_order(self, http, api_key, order_id):
        self.cancel_calls.append(order_id)
        return {"status": "canceled", "order_id": order_id}

    def submit_oco_bracket(self, http, api_key, *, venue_code, symbol,
                            qty, target_price, stop_price, link_id,
                            time_in_force="GTC"):
        self.oco_calls.append({"symbol": symbol, "qty": qty})
        return self.oco_response


_NOW = datetime(2026, 7, 14, 15, 0, tzinfo=timezone.utc)


def _stuck_lot(*, stamp="2026-07-14T14:00:00Z", target="T-1", stop="S-1"):
    return {
        "symbol": "AAA", "qty": 100, "status": "exit_pending",
        "link_id": "L-1", "entry_price": 10.0,
        "entry_timestamp": "2026-07-13T14:00:00Z",
        "recorded_exposure": 1000.0,
        "child_order_ids": {"target": target, "stop": stop},
        "target_price": 11.0, "stop_price": 9.5,
        "exit_reason_pending": "time_stop",
        "exit_pending_at": stamp,
    }


# ---- recover_stuck_exit_pending ------------------------------------------------


def test_recover_keeps_ids_when_children_live(tmp_path):
    cfg = _cfg(tmp_path)
    state = {"open_positions": {"L-1": _stuck_lot()}}
    oa = FakeOA()
    oa.order_rows["T-1"] = {"id": "T-1", "status": "new", "filled_qty": 0}
    oa.order_rows["S-1"] = {"id": "S-1", "status": "new", "filled_qty": 0}
    out = v2.recover_stuck_exit_pending(
        state, cfg, oa_client=oa, api_key="k", http=None, now_utc=_NOW,
    )
    assert out == ["L-1"]
    pos = state["open_positions"]["L-1"]
    assert pos["status"] == "filled"
    assert pos["child_order_ids"] == {"target": "T-1", "stop": "S-1"}
    assert "exit_pending_at" not in pos
    assert "exit_reason_pending" not in pos
    assert any(e["event_type"] == "exit_pending_recovered"
               for e in _ledger_events(tmp_path))


def test_recover_clears_dead_children_and_reattaches(tmp_path):
    cfg = _cfg(tmp_path)
    state = {"open_positions": {"L-1": _stuck_lot()}}
    oa = FakeOA()
    oa.order_rows["T-1"] = {"id": "T-1", "status": "canceled",
                             "filled_qty": 0}
    oa.order_rows["S-1"] = {"_status": "not_found"}
    out = v2.recover_stuck_exit_pending(
        state, cfg, oa_client=oa, api_key="k", http=None, now_utc=_NOW,
    )
    assert out == ["L-1"]
    pos = state["open_positions"]["L-1"]
    assert pos["status"] == "filled"
    assert pos["child_order_ids"] == {"target": "", "stop": ""}
    # The lot is now re-attach eligible — the OCO sweep brackets it.
    attached = v2.submit_pending_oco_children_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert attached == ["AAA"]
    assert pos["child_order_ids"] == {"target": "T-NEW", "stop": "S-NEW"}


def test_recover_missing_stamp_is_stale(tmp_path):
    cfg = _cfg(tmp_path)
    lot = _stuck_lot()
    lot.pop("exit_pending_at")
    state = {"open_positions": {"L-1": lot}}
    oa = FakeOA()
    oa.order_rows["T-1"] = {"id": "T-1", "status": "canceled",
                             "filled_qty": 0}
    oa.order_rows["S-1"] = {"id": "S-1", "status": "canceled",
                             "filled_qty": 0}
    out = v2.recover_stuck_exit_pending(
        state, cfg, oa_client=oa, api_key="k", http=None, now_utc=_NOW,
    )
    assert out == ["L-1"]
    assert state["open_positions"]["L-1"]["status"] == "filled"


def test_recover_leaves_fresh_exit_pending_alone(tmp_path):
    cfg = _cfg(tmp_path)
    # Stamp 30s ago — inside the max_age_s window.
    state = {"open_positions": {
        "L-1": _stuck_lot(stamp="2026-07-14T14:59:30Z"),
    }}
    out = v2.recover_stuck_exit_pending(
        state, cfg, oa_client=FakeOA(), api_key="k", http=None,
        now_utc=_NOW,
    )
    assert out == []
    assert state["open_positions"]["L-1"]["status"] == "exit_pending"


def test_recover_never_clears_subset_when_one_child_live(tmp_path):
    """One dead + one live child: ids stay untouched — a fresh
    full-qty bracket next to a live old leg could oversell."""
    cfg = _cfg(tmp_path)
    state = {"open_positions": {"L-1": _stuck_lot()}}
    oa = FakeOA()
    oa.order_rows["T-1"] = {"id": "T-1", "status": "canceled",
                             "filled_qty": 0}
    oa.order_rows["S-1"] = {"id": "S-1", "status": "new", "filled_qty": 0}
    out = v2.recover_stuck_exit_pending(
        state, cfg, oa_client=oa, api_key="k", http=None, now_utc=_NOW,
    )
    assert out == ["L-1"]
    pos = state["open_positions"]["L-1"]
    assert pos["status"] == "filled"
    assert pos["child_order_ids"] == {"target": "T-1", "stop": "S-1"}


# ---- immediate persistence -----------------------------------------------------


def _make_candidate(symbol: str, rank: int = 1) -> dict:
    return {
        "schema_version": schemas.CANDIDATE_EVENT_SCHEMA_VERSION,
        "strategy": "bowaka_v2",
        "event_type": "candidate_signal",
        "event_id": f"bowaka_v2:2026-05-18:{symbol}:scan",
        "generated_at": "2026-05-18T14:35:00Z",
        "session_date": "2026-05-18",
        "scan_timestamp": "2026-05-18T14:35:00Z",
        "provider": "alpaca", "data_feed": "iex", "bar_interval": "1m",
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
        "candidate_rank": rank,
        "signal_expiry_timestamp": "2026-05-19T00:00:00Z",
    }


def _consumer_cfg(tmp_path, cand_path):
    return {
        "strategy": {"mode": "forming_daily_bar_monitor",
                       "environment": "paper"},
        "paths": {
            "candidate_events_path": str(cand_path),
            "trade_ledger_path": str(tmp_path / "trade_ledger.jsonl"),
            "daily_summary_path": str(tmp_path / "daily_summary.jsonl"),
        },
        "data": {"feed": "iex", "allow_non_sip_for_research_only": True},
        "execution": {
            "default_venue_code": "XNAS", "parent_order_style": "market",
            "quote_gate": {"enabled": False},
            "price_chase_gate": {"enabled": False},
            "halt_gate": {"enabled": False},
        },
        "sizing": {
            "sizing_mode": "equal_slice",
            "bankroll_fixed_dollars": 90000,
            "max_concurrent_positions": 18,
            "equal_slice_bankroll_fraction": 0.80,
            "min_order_notional": 500,
        },
        "risk": {"max_total_entries_per_day": 10,
                   "max_gross_exposure_pct": 0.80},
        "exits": {"stop_pct": 0.08, "target_pct": 0.15,
                    "max_hold_days": 3},
        "logging": {"emit_entry_decisions": False,
                       "emit_rejected_candidates": False,
                       "log_order_execution_quality": False,
                       "log_protection_state": False,
                       "log_shadow_risk_controls": False,
                       "log_counterfactual_entries": False,
                       "log_counterfactual_exits": False},
    }


def test_consume_persists_state_immediately_after_each_submit(tmp_path):
    cand_path = tmp_path / "candidates.jsonl"
    cand_path.write_text(
        json.dumps(_make_candidate("AAA", rank=1)) + "\n"
        + json.dumps(_make_candidate("BBB", rank=2)) + "\n",
        encoding="utf-8",
    )
    state_path = tmp_path / "state.json"
    cfg = _consumer_cfg(tmp_path, cand_path)
    state = {"last_consumed_event_offset": 0, "entered_today": [],
             "daily_entries_count": 0, "open_positions": {}}
    snapshots: list[tuple[str, dict | None]] = []

    def fake_submit(symbol, qty):
        snap = (json.loads(state_path.read_text(encoding="utf-8"))
                if state_path.exists() else None)
        snapshots.append((symbol, snap))
        return {"_http_status": 200, "data": {"order_id": f"P-{symbol}"}}

    s = v2.consume_candidate_events(
        state, cfg,
        quote_supplier=lambda sym: {
            "bid": 8.10, "ask": 8.12, "mid": 8.11, "spread_pct": 0.002,
            "quote_timestamp": "2026-05-18T18:35:00Z",
            "quote_age_seconds": 1, "symbol_status": "ok",
        },
        submit_supplier=fake_submit,
        today_iso="2026-05-18",
        now_utc=datetime(2026, 5, 18, 18, 35, tzinfo=timezone.utc),
        state_path=state_path,
    )
    assert s["accepted"] == 2
    # By BBB's submit, AAA's accepted lot was already ON DISK.
    sym2, snap2 = snapshots[1]
    assert sym2 == "BBB"
    assert snap2 is not None
    assert any(p["symbol"] == "AAA"
               for p in snap2["open_positions"].values())
    assert "AAA" in snap2["entered_today"]
    final = json.loads(state_path.read_text(encoding="utf-8"))
    assert len(final["open_positions"]) == 2


def test_consume_without_state_path_writes_nothing(tmp_path):
    cand_path = tmp_path / "candidates.jsonl"
    cand_path.write_text(
        json.dumps(_make_candidate("AAA")) + "\n", encoding="utf-8",
    )
    cfg = _consumer_cfg(tmp_path, cand_path)
    state = {"last_consumed_event_offset": 0, "entered_today": [],
             "daily_entries_count": 0, "open_positions": {}}
    s = v2.consume_candidate_events(
        state, cfg,
        quote_supplier=lambda sym: {
            "bid": 8.10, "ask": 8.12, "mid": 8.11, "spread_pct": 0.002,
            "quote_timestamp": "2026-05-18T18:35:00Z",
            "quote_age_seconds": 1, "symbol_status": "ok",
        },
        submit_supplier=lambda sym, qty: {
            "_http_status": 200, "data": {"order_id": f"P-{sym}"},
        },
        today_iso="2026-05-18",
        now_utc=datetime(2026, 5, 18, 18, 35, tzinfo=timezone.utc),
    )
    assert s["accepted"] == 1
    assert not (tmp_path / "state.json").exists()


# ---- roll_session_if_needed ----------------------------------------------------


def test_roll_session_resets_counters_directly():
    state = {
        "session_date": "2026-05-15",
        "entered_today": ["AAA", "BBB"],
        "daily_entries_count": 2,
        "daily_realized_pnl_strategy": -420.0,
        "daily_stopout_count": 2,
        "consecutive_stopout_count": 2,
        "scan_accept_counts": {"t1": 2},
        "luld_pauses": {"AAA": "2026-05-15T15:00:00Z"},
        "open_positions": {
            "L-1": {"symbol": "CCC", "qty": 100,
                     "recorded_exposure": 1500.0, "status": "filled"},
        },
        "gross_exposure_dollars": 99999.0,
    }
    rolled = v2.roll_session_if_needed(
        state, datetime(2026, 5, 18, 14, 0, tzinfo=timezone.utc),
        "2026-05-18",
    )
    assert rolled is True
    assert state["session_date"] == "2026-05-18"
    assert state["entered_today"] == []
    assert state["daily_entries_count"] == 0
    assert state["daily_realized_pnl_strategy"] == 0.0
    assert state["daily_stopout_count"] == 0
    # Deliberately NOT reset by rollover (v1 parity).
    assert state["consecutive_stopout_count"] == 2
    assert "scan_accept_counts" not in state
    assert "luld_pauses" not in state
    # Gross exposure recomputed from held lots, not zeroed.
    assert state["gross_exposure_dollars"] == 1500.0


def test_roll_session_first_run_and_same_day_are_noops():
    state: dict = {}
    now = datetime(2026, 5, 18, 14, 0, tzinfo=timezone.utc)
    assert v2.roll_session_if_needed(state, now, "2026-05-18") is False
    assert state["session_date"] == "2026-05-18"
    state["daily_entries_count"] = 3
    assert v2.roll_session_if_needed(state, now, "2026-05-18") is False
    assert state["daily_entries_count"] == 3


# ---- L2 exposure restore -------------------------------------------------------


def test_l2_kill_restores_exposure_for_pending_lots(tmp_path):
    cfg = _cfg(tmp_path)
    state = {
        "gross_exposure_dollars": 1800.0,
        "open_positions": {
            "L-p": {
                "symbol": "AAA", "qty": 80, "status": "pending_fill",
                "parent_order_id": "P-1", "link_id": "L-p",
                "recorded_exposure": 800.0,
                "child_order_ids": {"target": "", "stop": ""},
            },
            "L-f": {
                "symbol": "BBB", "qty": 100, "status": "filled",
                "entry_price": 10.0, "link_id": "L-f",
                "recorded_exposure": 1000.0,
                "child_order_ids": {"target": "T-1", "stop": "S-1"},
            },
        },
    }

    class L2OA(FakeOA):
        def __init__(self):
            super().__init__()
            self.market_sells: list[dict] = []
            self.order_rows["T-1"] = {"id": "T-1", "status": "canceled",
                                       "filled_qty": 0}
            self.order_rows["S-1"] = {"id": "S-1", "status": "canceled",
                                       "filled_qty": 0}

        def submit_market_sell(self, http, api_key, *, venue_code,
                                symbol, qty, time_in_force="DAY"):
            self.market_sells.append({"symbol": symbol, "qty": qty})
            return {"data": {"order_id": "EXIT-1"}, "_http_status": 200}

    oa = L2OA()
    out = v2.execute_kill_l2_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert sorted(out) == ["AAA", "BBB"]
    # Pending lot popped AND its reserved exposure restored.
    assert "L-p" not in state["open_positions"]
    assert state["gross_exposure_dollars"] == 1000.0


# ---- fade stamp on success -----------------------------------------------------


def _fade_cfg(tmp_path):
    cfg = _cfg(tmp_path)
    cfg["exits"]["signal_fade"] = {
        "enabled": True, "active": False,
        "eval_time": "15:45", "telemetry_time": "16:05",
    }
    return cfg


def test_fade_stamp_not_set_when_eval_raises(tmp_path, monkeypatch):
    import pandas as pd
    cfg = _fade_cfg(tmp_path)
    state = {"open_positions": {}}
    now_et = pd.Timestamp("2026-07-14 15:50", tz="America/New_York")

    def boom(*a, **kw):
        raise RuntimeError("bars backend down")

    monkeypatch.setattr(v2, "_signal_fade_eval", boom)
    with pytest.raises(RuntimeError):
        v2.run_signal_fade_pass_v2(
            state, cfg, oa_client=FakeOA(), api_key="k", http=None,
            now_et=now_et,
        )
    assert "signal_fade_evaluated_on" not in state

    # Next tick: eval works — the stamp is set and eval ran once.
    calls = []
    monkeypatch.setattr(
        v2, "_signal_fade_eval",
        lambda *a, **kw: calls.append(kw.get("phase")) or [],
    )
    v2.run_signal_fade_pass_v2(
        state, cfg, oa_client=FakeOA(), api_key="k", http=None,
        now_et=now_et,
    )
    assert state["signal_fade_evaluated_on"] == "2026-07-14"
    assert calls == ["eval"]
