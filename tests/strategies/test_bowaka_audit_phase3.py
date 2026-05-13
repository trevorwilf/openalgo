"""Phase 3 audit acceptance tests — rescreen + circuit breakers.

Covers:
  3.2 ``should_set_rescreen_pending`` truth table.
  3.5 ``update_daily_closure_risk_state`` counters + block trips.
  3.6 Slate-wide block beats every gate (select_entries + rescreen).
  3.7 Block state survives ``save_state(load_state)`` mid-session.
  3.1 Rescreen never fires after a stop with
       ``post_closure_rescreen.enabled=false``.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest


# ---------------------------------------------------------------- helpers


def _route(handlers):
    def handler(req: httpx.Request) -> httpx.Response:
        key = (req.method, req.url.path)
        h = handlers.get(key)
        if h is None:
            return httpx.Response(404, json={"error": {"code": "no_route"}})
        if callable(h):
            return h(req)
        return h
    return httpx.MockTransport(handler)


def _filled_pos(*, qty=100, entry_price=10.0, target_id="T-1", stop_id="S-1",
                entry_trigger="session_open", link_id="BOWAKA-X-1"):
    return {
        "parent_order_id": "P-1",
        "child_order_ids": {"target": target_id, "stop": stop_id},
        "qty": qty,
        "entry_price": entry_price,
        "entry_timestamp": "2026-05-04T13:30:00+00:00",
        "entry_features": {},
        "status": "filled",
        "venue_code": "XNAS",
        "target_price": entry_price * 1.15,
        "stop_price": entry_price * 0.92,
        "target_pct": 0.15,
        "stop_pct": 0.08,
        "entry_trigger": entry_trigger,
        "link_id": link_id,
    }


@pytest.fixture
def cfg_phase3(cfg_with_paths):
    cfg = dict(cfg_with_paths)
    cfg["risk"] = {
        **cfg_with_paths["risk"],
        "max_position_as_adv_frac": 0.03,
        "max_total_entries_per_day": 10,
        "max_stopouts_per_day": None,
        "stop_trading_after_consecutive_stopouts": None,
        "daily_loss_basis": "bankroll",
        "strategy_slice_loss_pct": None,
    }
    cfg["entry"] = {
        **cfg_with_paths.get("entry", {}),
        "bracket_pricing_mode": "actual_fill",
        "intraday_confirmation": {"enabled": False},
        "post_closure_rescreen": {
            "enabled": False,
            "last_entry_time": "14:00",
            "only_after_reasons": None,
            "max_entries_per_day": None,
            "require_day_pnl_nonnegative": None,
            "max_stopouts_today": None,
        },
    }
    return cfg


# ---------------------------------------------------------------- 3.2 truth table


def test_should_set_rescreen_pending_disabled(strategy_module, cfg_phase3):
    state = strategy_module.blank_state()
    cfg = dict(cfg_phase3)
    cfg["entry"]["post_closure_rescreen"]["enabled"] = False
    assert strategy_module.should_set_rescreen_pending("target_hit", state, cfg) is False


def test_should_set_rescreen_pending_no_only_after_reasons_fail_closed(
    strategy_module, cfg_phase3,
):
    """No only_after_reasons list → fail-closed (returns False)."""
    state = strategy_module.blank_state()
    cfg = dict(cfg_phase3)
    cfg["entry"]["post_closure_rescreen"]["enabled"] = True
    cfg["entry"]["post_closure_rescreen"]["only_after_reasons"] = None
    assert strategy_module.should_set_rescreen_pending("target_hit", state, cfg) is False


def test_should_set_rescreen_pending_reason_not_in_allow_list(
    strategy_module, cfg_phase3,
):
    state = strategy_module.blank_state()
    cfg = dict(cfg_phase3)
    cfg["entry"]["post_closure_rescreen"]["enabled"] = True
    cfg["entry"]["post_closure_rescreen"]["only_after_reasons"] = ["target_hit"]
    assert strategy_module.should_set_rescreen_pending("stop_hit", state, cfg) is False
    assert strategy_module.should_set_rescreen_pending("target_hit", state, cfg) is True


def test_should_set_rescreen_pending_require_day_pnl_nonnegative(
    strategy_module, cfg_phase3,
):
    state = strategy_module.blank_state()
    cfg = dict(cfg_phase3)
    cfg["entry"]["post_closure_rescreen"]["enabled"] = True
    cfg["entry"]["post_closure_rescreen"]["only_after_reasons"] = ["target_hit"]
    cfg["entry"]["post_closure_rescreen"]["require_day_pnl_nonnegative"] = True
    state["daily_realized_pnl_strategy"] = -50.0
    assert strategy_module.should_set_rescreen_pending("target_hit", state, cfg) is False
    state["daily_realized_pnl_strategy"] = 0.0
    assert strategy_module.should_set_rescreen_pending("target_hit", state, cfg) is True


def test_should_set_rescreen_pending_max_stopouts_today_caps(
    strategy_module, cfg_phase3,
):
    state = strategy_module.blank_state()
    cfg = dict(cfg_phase3)
    cfg["entry"]["post_closure_rescreen"]["enabled"] = True
    cfg["entry"]["post_closure_rescreen"]["only_after_reasons"] = ["target_hit"]
    cfg["entry"]["post_closure_rescreen"]["max_stopouts_today"] = 1
    state["daily_stopouts_count"] = 1
    assert strategy_module.should_set_rescreen_pending("target_hit", state, cfg) is False
    state["daily_stopouts_count"] = 0
    assert strategy_module.should_set_rescreen_pending("target_hit", state, cfg) is True


def test_should_set_rescreen_pending_max_entries_per_day_caps(
    strategy_module, cfg_phase3,
):
    state = strategy_module.blank_state()
    cfg = dict(cfg_phase3)
    cfg["entry"]["post_closure_rescreen"]["enabled"] = True
    cfg["entry"]["post_closure_rescreen"]["only_after_reasons"] = ["target_hit"]
    cfg["entry"]["post_closure_rescreen"]["max_entries_per_day"] = 1
    state["post_closure_entries_today"] = 1
    assert strategy_module.should_set_rescreen_pending("target_hit", state, cfg) is False
    state["post_closure_entries_today"] = 0
    assert strategy_module.should_set_rescreen_pending("target_hit", state, cfg) is True


# ---------------------------------------------------------------- 3.5 circuit breakers


def test_consecutive_stopouts_block(strategy_module, cfg_phase3, tmp_path):
    """Two stop_hit closures in a row with
    stop_trading_after_consecutive_stopouts=2 → block_new_entries_today
    flips on with reason='consecutive_stopouts'."""
    cfg = dict(cfg_phase3)
    cfg["risk"]["stop_trading_after_consecutive_stopouts"] = 2
    state = strategy_module.blank_state()
    strategy_module.update_daily_closure_risk_state(
        state, cfg, reason="stop_hit", realized_pnl=-50.0,
    )
    assert state["consecutive_stopouts_count"] == 1
    assert state["block_new_entries_today"] is False
    strategy_module.update_daily_closure_risk_state(
        state, cfg, reason="stop_hit", realized_pnl=-50.0,
    )
    assert state["consecutive_stopouts_count"] == 2
    assert state["block_new_entries_today"] is True
    assert state["new_entries_blocked_reason"] == "consecutive_stopouts"


def test_target_resets_consecutive_streak(strategy_module, cfg_phase3):
    cfg = dict(cfg_phase3)
    state = strategy_module.blank_state()
    strategy_module.update_daily_closure_risk_state(
        state, cfg, reason="stop_hit", realized_pnl=-50.0,
    )
    assert state["consecutive_stopouts_count"] == 1
    strategy_module.update_daily_closure_risk_state(
        state, cfg, reason="target_hit", realized_pnl=100.0,
    )
    assert state["consecutive_stopouts_count"] == 0


def test_max_stopouts_per_day_cumulative(strategy_module, cfg_phase3):
    """daily_stopouts_count is cumulative — a target between two stops
    still blocks at the 2nd stop when max_stopouts_per_day=2."""
    cfg = dict(cfg_phase3)
    cfg["risk"]["max_stopouts_per_day"] = 2
    state = strategy_module.blank_state()
    strategy_module.update_daily_closure_risk_state(
        state, cfg, reason="stop_hit", realized_pnl=-50.0,
    )
    strategy_module.update_daily_closure_risk_state(
        state, cfg, reason="target_hit", realized_pnl=100.0,
    )
    assert state["consecutive_stopouts_count"] == 0
    assert state["daily_stopouts_count"] == 1
    assert state["block_new_entries_today"] is False
    strategy_module.update_daily_closure_risk_state(
        state, cfg, reason="stop_hit", realized_pnl=-50.0,
    )
    assert state["daily_stopouts_count"] == 2
    assert state["block_new_entries_today"] is True
    assert state["new_entries_blocked_reason"] == "max_stopouts_per_day"


def test_daily_pnl_tripped_mirrors_block(strategy_module, cfg_phase3, tmp_path):
    """update_daily_pnl tripping daily_loss_pct also flips
    block_new_entries_today."""
    state = strategy_module.blank_state()
    state["daily_pnl_baseline_equity"] = 100_000.0
    cfg = dict(cfg_phase3)
    cfg["risk"]["daily_loss_pct"] = 0.01
    state_path = Path(cfg["paths"]["state_path"])
    state_path.parent.mkdir(parents=True, exist_ok=True)
    strategy_module.update_daily_pnl(
        state, 98_500.0, cfg, state_path=state_path,
    )
    assert state["daily_pnl_tripped"] is True
    assert state["block_new_entries_today"] is True
    assert state["new_entries_blocked_reason"] == "daily_pnl_tripped"


def test_block_survives_save_load_mid_session(
    strategy_module, cfg_phase3, tmp_path,
):
    """Mid-session restart preserves block flags — only
    reset_for_new_session clears them."""
    state = strategy_module.blank_state()
    state["session_date"] = "2026-05-11"
    state["block_new_entries_today"] = True
    state["new_entries_blocked_reason"] = "consecutive_stopouts"
    state_path = Path(cfg_phase3["paths"]["state_path"])
    state_path.parent.mkdir(parents=True, exist_ok=True)
    strategy_module.save_state(state, state_path)
    reloaded = strategy_module.load_state(state_path)
    assert reloaded["block_new_entries_today"] is True
    assert reloaded["new_entries_blocked_reason"] == "consecutive_stopouts"
    # reset_for_new_session for the SAME date should NOT happen in
    # production (the run_loop only resets on session_date change),
    # but if it does it clears the flag — verify.
    strategy_module.reset_for_new_session(reloaded, "2026-05-12", 100_000.0)
    assert reloaded["block_new_entries_today"] is False
    assert reloaded["new_entries_blocked_reason"] is None


# ---------------------------------------------------------------- 3.6 entry gate honors block


def test_select_entries_blocks_when_flag_set(strategy_module, cfg_phase3):
    """A blocked session emits ONE synthetic entry_decision with
    reason='blocked_by_daily_risk' (slate-wide event)."""
    state = strategy_module.blank_state()
    state["block_new_entries_today"] = True
    state["new_entries_blocked_reason"] = "consecutive_stopouts"
    cands = [
        strategy_module.Candidate(f"T{i}", 10.0, 5.0 - i * 0.1,
                                  features={"avg_dollar_volume": 1e7})
        for i in range(4)
    ]
    sel = strategy_module.select_entries(
        cands, state, equity=100_000.0, latest_prices={},
        cfg=cfg_phase3, kill_state=strategy_module.KillLevel.NONE,
    )
    assert sel == []
    ledger_path = (
        Path(cfg_phase3["paths"]["daily_summary_path"]).parent
        / "trade_ledger.jsonl"
    )
    events = []
    for line in ledger_path.read_text().splitlines():
        if not line.strip():
            continue
        events.append(json.loads(line))
    decisions = [e for e in events if e["event_type"] == "entry_decision"]
    assert len(decisions) == 1
    assert decisions[0]["payload"]["reason"] == "blocked_by_daily_risk"


def test_rescreen_blocked_when_flag_set(strategy_module, cfg_phase3, tmp_path):
    """run_post_closure_rescreen no-ops with block flag set; the
    rescreen_pending flag is cleared."""
    state = strategy_module.blank_state()
    state["rescreen_pending"] = True
    state["block_new_entries_today"] = True
    state["new_entries_blocked_reason"] = "consecutive_stopouts"
    cfg = dict(cfg_phase3)
    cfg["entry"]["post_closure_rescreen"]["enabled"] = True
    cfg["entry"]["post_closure_rescreen"]["only_after_reasons"] = ["target_hit"]
    state_path = Path(cfg["paths"]["state_path"])
    state_path.parent.mkdir(parents=True, exist_ok=True)
    submitted = strategy_module.run_post_closure_rescreen(
        cfg, state, state_path, http=None, api_key="k",
        today_et=date(2026, 5, 11),
        kill_state=strategy_module.KillLevel.NONE,
        now_utc=datetime(2026, 5, 11, 17, 30, tzinfo=timezone.utc),
    )
    assert submitted == 0
    assert state["rescreen_pending"] is False


# ---------------------------------------------------------------- 3.1 rescreen disabled by default


def test_stop_hit_does_not_set_rescreen_when_rescreen_disabled(
    strategy_module, cfg_phase3, tmp_path,
):
    """With enabled=false, ``stop_hit`` never sets rescreen_pending.
    The cfg_phase3 fixture starts with enabled=False (audit default)."""
    state = strategy_module.blank_state()
    state["open_positions"] = {"AAPL": _filled_pos(target_id="T-1", stop_id="S-1")}
    state_path = Path(cfg_phase3["paths"]["state_path"])
    summary_path = Path(cfg_phase3["paths"]["daily_summary_path"])
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    ev = strategy_module.FillEvent(
        ticker="AAPL", order_id="S-1", role="stop", status="FILLED",
        filled_qty=100, filled_avg_price=9.20, raw={},
    )
    strategy_module.process_fill_events_for_closures(
        [ev], state, cfg_phase3,
        state_path=state_path, summary_path=summary_path,
    )
    # Closure happened (position dropped) but rescreen_pending stays False.
    assert "AAPL" not in state["open_positions"]
    assert state.get("rescreen_pending", False) is False


def test_strategy_slice_loss_pct_trip(strategy_module, cfg_phase3):
    """When strategy_slice_loss_pct is set, the slice-based trip
    fires when realized PnL crosses -X% of the daily slice."""
    cfg = dict(cfg_phase3)
    cfg["risk"]["strategy_slice_loss_pct"] = 0.025
    cfg["exits"] = {**cfg.get("exits", {}), "max_hold_days": 3}
    state = strategy_module.blank_state()
    # Seed a bankroll with $90,000.
    state["bankroll"] = {"current_dollars": 90_000.0}
    # Daily slice = 90k / 3 = $30,000. 2.5% of slice = $750. Trip on -$800.
    strategy_module.update_daily_closure_risk_state(
        state, cfg, reason="stop_hit", realized_pnl=-800.0,
    )
    assert state["block_new_entries_today"] is True
    assert state["new_entries_blocked_reason"] == "strategy_slice_loss"
