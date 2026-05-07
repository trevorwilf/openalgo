"""Phase 4 — Risk + Reconciliation: daily P&L circuit breaker, halt
detection, restart reconciliation, full L2/L3 kill switch behavior,
daily summary log, integration smoke."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest


# ---------------------------------------------------------------- helpers


def _filled_pos(qty=10, target_id="T-1", stop_id="S-1",
                entry_iso="2026-05-04T13:30:00+00:00",
                entry_price=100.0):
    return {
        "parent_order_id": "P-1",
        "child_order_ids": {"target": target_id, "stop": stop_id},
        "qty": qty,
        "entry_price": entry_price,
        "entry_timestamp": entry_iso,
        "entry_features": {},
        "status": "filled",
        "venue_code": "XNAS",
        "target_price": 115.0,
        "stop_price": 92.0,
    }


def _make_handler(routes: dict[tuple[str, str], "callable"]):
    def handler(req: httpx.Request) -> httpx.Response:
        # Match by exact path first, then prefix for parameterized.
        key = (req.method, req.url.path)
        if key in routes:
            return routes[key](req)
        for (m, p), fn in routes.items():
            if req.method == m and req.url.path.startswith(p):
                return fn(req)
        return httpx.Response(404, json={"error": {"code": "no_route", "path": req.url.path}})
    return httpx.MockTransport(handler)


# ---------------------------------------------------------------- daily P&L


def test_daily_pnl_trip_at_threshold(strategy_module, cfg_with_paths, tmp_path):
    state = strategy_module.blank_state()
    state["daily_pnl_baseline_equity"] = 100_000.0
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    tripped = strategy_module.update_daily_pnl(
        state, current_equity=96_900.0, cfg=cfg_with_paths,
        state_path=state_path,
    )
    assert tripped is True
    assert state["daily_pnl_tripped"] is True


def test_daily_pnl_no_trip_at_2pct(strategy_module, cfg_with_paths, tmp_path):
    state = strategy_module.blank_state()
    state["daily_pnl_baseline_equity"] = 100_000.0
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    tripped = strategy_module.update_daily_pnl(
        state, current_equity=98_000.0, cfg=cfg_with_paths,
        state_path=state_path,
    )
    assert tripped is False
    assert state.get("daily_pnl_tripped") is False


def test_daily_pnl_no_trip_on_gain(strategy_module, cfg_with_paths, tmp_path):
    state = strategy_module.blank_state()
    state["daily_pnl_baseline_equity"] = 100_000.0
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    tripped = strategy_module.update_daily_pnl(
        state, current_equity=105_000.0, cfg=cfg_with_paths,
        state_path=state_path,
    )
    assert tripped is False


def test_daily_pnl_resets_new_session(strategy_module):
    state = strategy_module.blank_state()
    state["daily_pnl_tripped"] = True
    state["daily_pnl_baseline_equity"] = 100_000.0
    strategy_module.reset_for_new_session(state, "2026-05-06", 105_000.0)
    assert state["daily_pnl_tripped"] is False
    assert state["daily_pnl_baseline_equity"] == 105_000.0


# ---------------------------------------------------------------- reconciliation


def test_reconcile_state_matches_broker_no_changes(
    strategy_module, cfg_with_paths, tmp_path,
):
    state = strategy_module.blank_state()
    state["open_positions"] = {"AAPL": _filled_pos(qty=10)}
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    summary_path = Path(cfg_with_paths["paths"]["daily_summary_path"])

    routes = {
        ("GET", "/api/v2/positions"): lambda r: httpx.Response(200, json={"data": {"positions": [
            {"canonical_symbol": "AAPL", "quantity": "10"},
        ]}}),
        ("GET", "/api/v2/orders"): lambda r: httpx.Response(200, json={"data": {"orders": []}}),
    }
    http = strategy_module.make_http_client("http://x", transport=_make_handler(routes))
    summary = strategy_module.reconcile_at_startup(
        state, http, "k", state_path=state_path, summary_path=summary_path,
    )
    assert summary["closed_externally"] == []
    assert summary["qty_corrected"] == []
    assert state["open_positions"]["AAPL"]["qty"] == 10


def test_reconcile_position_disappeared_externally(
    strategy_module, cfg_with_paths, tmp_path,
):
    state = strategy_module.blank_state()
    state["open_positions"] = {"AAPL": _filled_pos(qty=10)}
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    summary_path = Path(cfg_with_paths["paths"]["daily_summary_path"])

    routes = {
        ("GET", "/api/v2/positions"): lambda r: httpx.Response(200, json={"data": {"positions": []}}),
        ("GET", "/api/v2/orders"): lambda r: httpx.Response(200, json={"data": {"orders": []}}),
    }
    http = strategy_module.make_http_client("http://x", transport=_make_handler(routes))
    summary = strategy_module.reconcile_at_startup(
        state, http, "k", state_path=state_path, summary_path=summary_path,
    )
    assert "AAPL" in summary["closed_externally"]
    assert "AAPL" not in state["open_positions"]
    rec = json.loads(summary_path.read_text().strip())
    assert rec["reason"] == "closed_externally"


def test_reconcile_qty_mismatch_updates_state(
    strategy_module, cfg_with_paths, tmp_path,
):
    state = strategy_module.blank_state()
    state["open_positions"] = {"AAPL": _filled_pos(qty=100)}
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    summary_path = Path(cfg_with_paths["paths"]["daily_summary_path"])

    routes = {
        ("GET", "/api/v2/positions"): lambda r: httpx.Response(200, json={"data": {"positions": [
            {"canonical_symbol": "AAPL", "quantity": "50"},
        ]}}),
        ("GET", "/api/v2/orders"): lambda r: httpx.Response(200, json={"data": {"orders": []}}),
    }
    http = strategy_module.make_http_client("http://x", transport=_make_handler(routes))
    summary = strategy_module.reconcile_at_startup(
        state, http, "k", state_path=state_path, summary_path=summary_path,
    )
    assert "AAPL" in summary["qty_corrected"]
    assert state["open_positions"]["AAPL"]["qty"] == 50


def test_reconcile_warns_on_untracked_broker_position(
    strategy_module, cfg_with_paths, tmp_path,
):
    state = strategy_module.blank_state()
    state["open_positions"] = {"AAPL": _filled_pos(qty=10)}  # state DOES have a tracked position
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    summary_path = Path(cfg_with_paths["paths"]["daily_summary_path"])

    routes = {
        ("GET", "/api/v2/positions"): lambda r: httpx.Response(200, json={"data": {"positions": [
            {"canonical_symbol": "AAPL", "quantity": "10"},
            {"canonical_symbol": "MSFT", "quantity": "20"},  # untracked
        ]}}),
        ("GET", "/api/v2/orders"): lambda r: httpx.Response(200, json={"data": {"orders": []}}),
    }
    http = strategy_module.make_http_client("http://x", transport=_make_handler(routes))
    summary = strategy_module.reconcile_at_startup(
        state, http, "k", state_path=state_path, summary_path=summary_path,
    )
    assert "MSFT" in summary["untracked"]
    assert "MSFT" not in state["open_positions"]  # we don't auto-claim


def test_reconcile_child_order_filled_externally(
    strategy_module, cfg_with_paths, tmp_path,
):
    state = strategy_module.blank_state()
    pos = _filled_pos(qty=10, target_id="T-1", stop_id="S-1")
    state["open_positions"] = {"AAPL": pos}
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    summary_path = Path(cfg_with_paths["paths"]["daily_summary_path"])

    def positions_h(req):
        return httpx.Response(200, json={"data": {"positions": [
            {"canonical_symbol": "AAPL", "quantity": "10"},
        ]}})

    def orders_h(req):
        status = req.url.params.get("status")
        if status == "open":
            # T-1 is no longer open
            return httpx.Response(200, json={"data": {"orders": [
                {"id": "S-1", "status": "new"},
            ]}})
        # status=all
        return httpx.Response(200, json={"data": {"orders": [
            {"id": "T-1", "status": "filled", "filled_qty": "10",
             "filled_avg_price": "115.0"},
            {"id": "S-1", "status": "new"},
        ]}})

    routes = {
        ("GET", "/api/v2/positions"): positions_h,
        ("GET", "/api/v2/orders"): orders_h,
    }
    http = strategy_module.make_http_client("http://x", transport=_make_handler(routes))
    summary = strategy_module.reconcile_at_startup(
        state, http, "k", state_path=state_path, summary_path=summary_path,
    )
    assert any("AAPL:target=" in s for s in summary["child_status_corrected"])


def test_reconcile_pending_signal_fade_filled_overnight(
    strategy_module, cfg_with_paths, tmp_path,
):
    state = strategy_module.blank_state()
    pos = _filled_pos(qty=10)
    pos["status"] = "exiting"
    pos["exit_reason"] = "signal_fade"
    pos["exit_order_id"] = "EX-MOO-1"
    state["open_positions"] = {"AAPL": pos}
    state["pending_signal_fade_exits"] = {
        "AAPL": {"submitted_at": "2026-05-05T20:05:00+00:00", "exit_order_id": "EX-MOO-1"},
    }
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    summary_path = Path(cfg_with_paths["paths"]["daily_summary_path"])

    def positions_h(req):
        return httpx.Response(200, json={"data": {"positions": []}})

    def orders_h(req):
        status = req.url.params.get("status")
        if status == "open":
            return httpx.Response(200, json={"data": {"orders": []}})
        return httpx.Response(200, json={"data": {"orders": [
            {"id": "EX-MOO-1", "status": "filled", "filled_qty": "10",
             "filled_avg_price": "99.5"},
        ]}})

    http = strategy_module.make_http_client("http://x", transport=_make_handler({
        ("GET", "/api/v2/positions"): positions_h,
        ("GET", "/api/v2/orders"): orders_h,
    }))
    summary = strategy_module.reconcile_at_startup(
        state, http, "k", state_path=state_path, summary_path=summary_path,
    )
    # Position closed via signal_fade reconcile path OR via the
    # closed_externally branch (broker has no position). Either yields
    # a closure record; just assert the final state is clean.
    assert "AAPL" not in state["open_positions"]
    lines = summary_path.read_text().strip().splitlines()
    assert lines, "a closure record must have been appended"


# ---------------------------------------------------------------- kill switches


def test_kill_switch_l1_blocks_entries_only(strategy_module, cfg_with_paths):
    state = strategy_module.blank_state()
    cands = [strategy_module.Candidate("AAPL", 10.0, 9.0)]
    sel = strategy_module.select_entries(
        cands, state, equity=100_000.0, latest_prices={},
        cfg=cfg_with_paths, kill_state=strategy_module.KillLevel.L1_NEW,
    )
    assert sel == []


def test_kill_switch_l2_pending_keeps_state_when_cancel_fails(
    strategy_module, cfg_with_paths, tmp_path,
):
    """Regression: L2 used to drop pending positions from state even
    when the parent cancel raised — leaving the broker order live with
    no tracking. The fix retains the position with a cancel_failed
    marker so the next reconcile run can surface it."""
    state = strategy_module.blank_state()
    pending_pos = {
        "parent_order_id": "P-LIVE",
        "child_order_ids": {"target": "T-1", "stop": "S-1"},
        "qty": 10,
        "entry_price": None,
        "status": "pending_fill",
        "venue_code": "XNAS",
    }
    state["open_positions"] = {"GHOST": pending_pos}
    state_path = Path(cfg_with_paths["paths"]["state_path"])

    def cancel_h(req):
        # Simulate a broker that surfaces a real failure for the parent
        # — a 500 with no recognizable terminal-state body, which
        # cancel_order treats as a hard error (raise).
        return httpx.Response(500, json={"error": {"code": "broker_down", "message": "boom"}})

    def sell_h(req):
        return httpx.Response(200, json={"data": {"order_id": "EX-1"}})

    http = strategy_module.make_http_client(
        "http://x",
        transport=_make_handler({
            ("DELETE", "/api/v2/orders/"): cancel_h,
            ("POST", "/api/v2/orders"): sell_h,
        }),
    )
    out = strategy_module.execute_kill_l2(
        state, cfg_with_paths, http, "k", state_path=state_path,
    )
    # GHOST is still in state — NOT silently dropped — with a
    # cancel_failed marker the operator and reconciliation can act on.
    assert "GHOST" in out
    assert "GHOST" in state["open_positions"], (
        "L2 must not pop pending positions when cancel raises — "
        "broker order may still be live"
    )
    pos = state["open_positions"]["GHOST"]
    assert pos["status"] == "cancel_failed"
    assert "parent" in pos.get("cancel_failures", [])
    assert pos.get("cancel_failed_at")


def test_kill_switch_l2_pending_drops_state_when_all_cancels_succeed(
    strategy_module, cfg_with_paths, tmp_path,
):
    """Symmetric case: when every cancel succeeds the pending position
    is removed from state (current healthy behavior preserved)."""
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "GHOST": {
            "parent_order_id": "P-1",
            "child_order_ids": {"target": "T-1", "stop": "S-1"},
            "qty": 10,
            "status": "pending_fill",
            "venue_code": "XNAS",
        }
    }
    state_path = Path(cfg_with_paths["paths"]["state_path"])

    def cancel_h(req):
        return httpx.Response(200, json={})

    def sell_h(req):
        return httpx.Response(200, json={"data": {"order_id": "EX-1"}})

    http = strategy_module.make_http_client(
        "http://x",
        transport=_make_handler({
            ("DELETE", "/api/v2/orders/"): cancel_h,
            ("POST", "/api/v2/orders"): sell_h,
        }),
    )
    strategy_module.execute_kill_l2(
        state, cfg_with_paths, http, "k", state_path=state_path,
    )
    assert "GHOST" not in state["open_positions"]


def test_kill_switch_l2_market_outs_all_positions(
    strategy_module, cfg_with_paths, tmp_path,
):
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "AAPL": _filled_pos(),
        "MSFT": _filled_pos(target_id="T-2", stop_id="S-2"),
    }
    state_path = Path(cfg_with_paths["paths"]["state_path"])

    sells = []

    def cancel_h(req):
        return httpx.Response(200, json={})

    def sell_h(req):
        sells.append(json.loads(req.content))
        return httpx.Response(200, json={"data": {"order_id": f"EX-{len(sells)}"}})

    routes = {
        ("DELETE", "/api/v2/orders/"): cancel_h,
        ("POST", "/api/v2/orders"): sell_h,
    }
    http = strategy_module.make_http_client("http://x", transport=_make_handler(routes))
    out = strategy_module.execute_kill_l2(
        state, cfg_with_paths, http, "k", state_path=state_path,
    )
    assert set(out) == {"AAPL", "MSFT"}
    assert state["kill_switch_state"] == "L2"
    for pos in state["open_positions"].values():
        assert pos["status"] == "exiting"
        assert pos["exit_reason"] == "kill_switch_l2"
    assert len(sells) == 2


def test_kill_switch_l3_immediate_exit(strategy_module, cfg_with_paths, tmp_path):
    state = strategy_module.blank_state()
    state["open_positions"] = {"AAPL": _filled_pos()}
    state_path = Path(cfg_with_paths["paths"]["state_path"])

    sells = []

    def cancel_h(req):
        return httpx.Response(200, json={})

    def sell_h(req):
        sells.append(json.loads(req.content))
        return httpx.Response(200, json={"data": {"order_id": "EX-1"}})

    http = strategy_module.make_http_client("http://x", transport=_make_handler({
        ("DELETE", "/api/v2/orders/"): cancel_h,
        ("POST", "/api/v2/orders"): sell_h,
    }))
    out = strategy_module.execute_kill_l3(
        state, cfg_with_paths, http, "k", state_path=state_path,
    )
    assert "AAPL" in out
    assert state["kill_switch_state"] == "L3"
    assert sells, "L3 should submit market sells"
    assert state["open_positions"]["AAPL"]["exit_reason"] == "kill_switch_l3"


def test_kill_switch_l3_main_loop_returns_99(
    strategy_module, cfg_with_paths, tmp_path,
):
    state = strategy_module.blank_state()
    state["open_positions"] = {"AAPL": _filled_pos()}
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    strategy_module.save_state(state, state_path)
    flag = Path(cfg_with_paths["paths"]["kill_switch_dir"]) / "KILL_HARD.flag"
    flag.write_text("")

    sells = []

    def handler(req):
        if req.method == "DELETE":
            return httpx.Response(200, json={})
        if req.method == "POST" and req.url.path == "/api/v2/orders":
            sells.append(json.loads(req.content))
            return httpx.Response(200, json={"data": {"order_id": "EX-1"}})
        if req.method == "GET" and req.url.path in (
            "/api/v2/positions", "/api/v2/orders", "/api/v2/balances"
        ):
            return httpx.Response(200, json={"data": {
                "positions": [{"canonical_symbol": "AAPL", "quantity": "10"}],
                "orders": [], "count": 0,
                "balance": {"equity": "100000", "cash": "50000"},
            }})
        return httpx.Response(404)

    http = strategy_module.make_http_client(
        "http://x", transport=httpx.MockTransport(handler),
    )
    rc = strategy_module.run_loop(
        cfg_with_paths, once=True,
        now_provider=lambda: datetime(2026, 5, 5, 18, 0, tzinfo=timezone.utc),
        http_client=http, api_key="k",
    )
    assert rc == 99


# ---------------------------------------------------------------- daily summary


def test_daily_summary_written_at_session_end(
    strategy_module, cfg_with_paths, tmp_path,
):
    state = strategy_module.blank_state()
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    summary_path = Path(cfg_with_paths["paths"]["daily_summary_path"])

    # Simulate two prior closures today.
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    today_iso = "2026-05-05"
    for rec in [
        {"record_type": "closure", "ticker": "AAPL", "qty": 10,
         "entry_price": 100.0, "exit_price": 115.0,
         "entry_timestamp": "2026-05-04T13:30:00+00:00",
         "exit_timestamp": today_iso + "T19:30:00+00:00",
         "realized_pnl": 150.0, "reason": "target_hit"},
        {"record_type": "closure", "ticker": "MSFT", "qty": 5,
         "entry_price": 200.0, "exit_price": 192.0,
         "entry_timestamp": "2026-05-04T13:30:00+00:00",
         "exit_timestamp": today_iso + "T19:30:00+00:00",
         "realized_pnl": -40.0, "reason": "stop_hit"},
    ]:
        with open(summary_path, "a") as f:
            f.write(json.dumps(rec) + "\n")

    rec = strategy_module.write_session_summary(
        state, cfg_with_paths,
        summary_path=summary_path, state_path=state_path,
        today_iso=today_iso,
    )
    assert rec["count_closed"] == 2
    assert rec["total_realized_pnl"] == 110.0
    assert rec["by_reason"] == {"target_hit": 1, "stop_hit": 1}
    assert state["summary_written_for_date"] == today_iso


def test_daily_summary_written_only_once_per_day(
    strategy_module, cfg_with_paths, tmp_path,
):
    state = strategy_module.blank_state()
    state["summary_written_for_date"] = "2026-05-05"
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    summary_path = Path(cfg_with_paths["paths"]["daily_summary_path"])

    rec = strategy_module.write_session_summary(
        state, cfg_with_paths,
        summary_path=summary_path, state_path=state_path,
        today_iso="2026-05-05",
    )
    assert rec is None


# ---------------------------------------------------------------- halt


def test_halt_signal_detection(strategy_module):
    assert strategy_module._is_halt_signal({"status": "held"})
    assert strategy_module._is_halt_signal({"native_status": "PENDING_REVIEW"})
    assert strategy_module._is_halt_signal({"status": "rejected", "reject_reason": "Symbol Halted"})
    assert not strategy_module._is_halt_signal({"status": "new"})
    assert not strategy_module._is_halt_signal({"status": "filled"})


# ---------------------------------------------------------------- integration smoke


def test_full_lifecycle_session_smoke(
    strategy_module, cfg_with_paths, tmp_path, monkeypatch,
):
    """Mock everything and advance through one synthetic session.
    Verifies state transitions end-to-end."""
    candidates_path = Path(cfg_with_paths["paths"]["candidates_path"])
    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    candidates_path.write_text(json.dumps({
        "as_of_date": "2026-05-05",
        "config_hash": "abcd1234",
        "candidates": [
            {"ticker": "AAPL", "close": 10.0, "signal_strength": 9.0,
             "rvol": 2.0, "atr_pct": 0.08, "range_expansion": 1.4,
             "close_location": 0.85, "ema_distance": 0.05, "ema_slope": 0.02,
             "avg_dollar_volume": 1_000_000.0, "gap_pct": 0.02},
        ],
    }))

    n_combo = [0]
    n_balances = [0]
    n_orders = [0]

    def handler(req):
        path = req.url.path
        method = req.method
        if method == "GET" and path == "/api/v2/balances":
            n_balances[0] += 1
            return httpx.Response(200, json={"data": {"balance": {"equity": "100000"}}})
        if method == "GET" and path == "/api/v2/positions":
            return httpx.Response(200, json={"data": {"positions": []}})
        if method == "POST" and path == "/api/v2/orders/combo":
            n_combo[0] += 1
            return httpx.Response(200, json={"data": {"native_response": {
                "id": "P-1",
                "legs": [
                    {"id": "T-1", "order_type": "limit"},
                    {"id": "S-1", "order_type": "stop"},
                ],
            }}})
        if method == "GET" and path == "/api/v2/orders":
            n_orders[0] += 1
            return httpx.Response(200, json={"data": {"orders": [], "count": 0}})
        if method == "DELETE":
            return httpx.Response(200, json={})
        if method == "POST" and path == "/api/v2/orders":
            return httpx.Response(200, json={"data": {"order_id": "X"}})
        return httpx.Response(404, json={"error": {"path": path}})

    http = strategy_module.make_http_client(
        "http://x", transport=httpx.MockTransport(handler),
    )

    import pytz
    et = pytz.timezone("America/New_York")
    now = et.localize(datetime(2026, 5, 5, 14, 0)).astimezone(timezone.utc)

    rc = strategy_module.run_loop(
        cfg_with_paths, once=True,
        now_provider=lambda: now,
        http_client=http, api_key="k",
    )
    assert rc == 0
    assert n_combo[0] == 1
    state = strategy_module.load_state(Path(cfg_with_paths["paths"]["state_path"]))
    assert "AAPL" in state["open_positions"]
    assert state["session_date"] == "2026-05-05"
    assert state["daily_pnl_baseline_equity"] == 100_000.0
