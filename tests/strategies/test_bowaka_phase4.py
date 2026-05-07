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


def test_reconcile_clears_expired_child_ids_for_rebracket(
    strategy_module, cfg_with_paths, tmp_path,
):
    """An actual_fill position whose OCO children expired at session
    close (DAY TIF) used to sit naked because the next tick's
    submit_pending_oco_children skipped it (children non-empty,
    pointing at canceled IDs). reconcile must now clear those IDs so
    the next tick re-attaches a fresh OCO bracket. Without this fix
    overnight gap risk has no broker-side stop."""
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "BLDP": {
            "parent_order_id": "P-1",
            "child_order_ids": {"target": "T-EXPIRED", "stop": "S-EXPIRED"},
            "qty": 100, "entry_price": 5.00,
            "entry_timestamp": "2026-05-07T13:30:00+00:00",
            "status": "filled",
            "venue_code": "XNAS",
            "bracket_pricing_mode": "actual_fill",
            "target_pct": 0.15, "stop_pct": 0.08,
        }
    }
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    summary_path = Path(cfg_with_paths["paths"]["daily_summary_path"])

    # Mock has to differentiate ?status=open (returns empty — the
    # children are canceled so NOT in open list) from ?status=all
    # (returns the canceled rows so reconcile can read the native
    # status).
    canceled_rows = [
        {"id": "T-EXPIRED", "status": "canceled", "native_status": "canceled"},
        {"id": "S-EXPIRED", "status": "canceled", "native_status": "canceled"},
    ]

    def orders_h(req):
        is_open_query = b"status=open" in req.url.query
        return httpx.Response(200, json={
            "data": {"orders": [] if is_open_query else canceled_rows}
        })

    routes = {
        ("GET", "/api/v2/positions"): lambda r: httpx.Response(200, json={
            "data": {"positions": [
                {"canonical_symbol": "BLDP", "quantity": "100"},
            ]}
        }),
        ("GET", "/api/v2/orders"): orders_h,
    }
    http = strategy_module.make_http_client("http://x", transport=_make_handler(routes))
    summary = strategy_module.reconcile_at_startup(
        state, http, "k", state_path=state_path, summary_path=summary_path,
    )
    pos = state["open_positions"]["BLDP"]
    # Child ID slots cleared so the next submit_pending_oco_children
    # tick re-attaches.
    assert pos["child_order_ids"]["target"] == ""
    assert pos["child_order_ids"]["stop"] == ""
    # Reconcile-side audit fields populated.
    assert pos["child_status_at_recon"]["target"] == "canceled"
    assert pos["child_status_at_recon"]["stop"] == "canceled"
    assert "BLDP" in summary.get("rebracket_pending", [])


def test_reconcile_does_not_clear_for_legacy_candidate_close_mode(
    strategy_module, cfg_with_paths, tmp_path,
):
    """Legacy candidate_close positions had their bracket atomically
    submitted with the parent; we don't try to re-bracket them. The
    reconcile clear-and-rebracket only applies to actual_fill mode."""
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "BLDP": {
            "parent_order_id": "P-1",
            "child_order_ids": {"target": "T-EXPIRED", "stop": "S-EXPIRED"},
            "qty": 100, "entry_price": 5.00,
            "entry_timestamp": "2026-05-07T13:30:00+00:00",
            "status": "filled",
            "venue_code": "XNAS",
            "bracket_pricing_mode": "candidate_close",   # legacy mode
        }
    }
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    summary_path = Path(cfg_with_paths["paths"]["daily_summary_path"])
    canceled_rows = [
        {"id": "T-EXPIRED", "status": "canceled", "native_status": "canceled"},
        {"id": "S-EXPIRED", "status": "canceled", "native_status": "canceled"},
    ]

    def orders_h(req):
        is_open_query = b"status=open" in req.url.query
        return httpx.Response(200, json={
            "data": {"orders": [] if is_open_query else canceled_rows}
        })

    routes = {
        ("GET", "/api/v2/positions"): lambda r: httpx.Response(200, json={
            "data": {"positions": [{"canonical_symbol": "BLDP", "quantity": "100"}]}
        }),
        ("GET", "/api/v2/orders"): orders_h,
    }
    http = strategy_module.make_http_client("http://x", transport=_make_handler(routes))
    strategy_module.reconcile_at_startup(
        state, http, "k", state_path=state_path, summary_path=summary_path,
    )
    pos = state["open_positions"]["BLDP"]
    # Legacy mode: IDs preserved, no auto re-bracket.
    assert pos["child_order_ids"]["target"] == "T-EXPIRED"
    assert pos["child_order_ids"]["stop"] == "S-EXPIRED"


def test_submit_oco_children_correctly_parses_alpaca_oco_response(
    strategy_module, cfg_with_paths, tmp_path,
):
    """Alpaca OCO native response has ``id`` for the limit (the
    parent / take-profit) and a single leg for the stop. The previous
    parser stamped both target_id and stop_id to legs[0] (the stop),
    so when the stop fired poll_fills double-counted it. Verify the
    fix: target_id = native.id, stop_id = legs[0].id."""
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "BLDP": {
            "parent_order_id": "P-1",
            "child_order_ids": {"target": "", "stop": ""},
            "qty": 100,
            "entry_price": 5.00,
            "status": "filled",
            "venue_code": "XNAS",
            "bracket_pricing_mode": "actual_fill",
            "target_pct": 0.15, "stop_pct": 0.08,
            "link_id": "BOWAKA-BLDP-1",
        }
    }

    def handler(req):
        # Alpaca-style OCO response: parent IS the limit; legs[0] is the stop.
        return httpx.Response(200, json={
            "data": {"native_response": {
                "id": "LIMIT-ID-PARENT",
                "order_type": "limit",
                "legs": [
                    {"id": "STOP-ID-CHILD", "order_type": "stop"},
                ],
            }}
        })

    http = strategy_module.make_http_client(
        "http://x", transport=httpx.MockTransport(handler),
    )
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    pos = state["open_positions"]["BLDP"]
    strategy_module.submit_oco_children(
        "BLDP", pos, cfg_with_paths, http, "k",
        state=state, state_path=state_path,
    )
    cids = state["open_positions"]["BLDP"]["child_order_ids"]
    assert cids["target"] == "LIMIT-ID-PARENT"
    assert cids["stop"] == "STOP-ID-CHILD"
    # The two MUST be different — that was the bug symptom.
    assert cids["target"] != cids["stop"]


def test_reconcile_walks_broker_when_state_is_empty(
    strategy_module, cfg_with_paths, tmp_path,
):
    """Item 6 regression: an EMPTY local state must still fetch broker
    positions so an untracked broker position (e.g., user moved
    state.json aside) surfaces as a warning. The runbook documents
    this exact behavior — and the function used to early-return on
    empty state, contradicting it."""
    state = strategy_module.blank_state()
    assert not state.get("open_positions")
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    summary_path = Path(cfg_with_paths["paths"]["daily_summary_path"])

    routes = {
        ("GET", "/api/v2/positions"): lambda r: httpx.Response(200, json={"data": {"positions": [
            {"canonical_symbol": "GHOST", "quantity": "10"},
        ]}}),
        ("GET", "/api/v2/orders"): lambda r: httpx.Response(200, json={"data": {"orders": []}}),
    }
    http = strategy_module.make_http_client("http://x", transport=_make_handler(routes))
    summary = strategy_module.reconcile_at_startup(
        state, http, "k", state_path=state_path, summary_path=summary_path,
    )
    assert "GHOST" in summary["untracked"], (
        "fresh state must surface broker positions as untracked "
        "warnings; runbook documents this and Item 6 fix removes "
        "the early-return that masked it"
    )
    assert "GHOST" not in state["open_positions"]


def test_reconcile_empty_state_no_broker_positions_is_clean_fresh_start(
    strategy_module, cfg_with_paths, tmp_path,
):
    """Empty state + no broker positions → genuine fresh start (no
    warnings)."""
    state = strategy_module.blank_state()
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
    assert summary["untracked"] == []
    assert summary["closed_externally"] == []


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


def test_kill_switch_l3_cancels_pending_parents(
    strategy_module, cfg_with_paths, tmp_path,
):
    """Item 8 (#4) regression: L3 used to ignore pending positions
    entirely and just exit code 99 with broker orders still live.
    L3 must mirror L2's pending-cancel logic before exiting."""
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "GHOST": {
            "parent_order_id": "P-LIVE",
            "child_order_ids": {"target": "T-1", "stop": "S-1"},
            "qty": 10, "entry_price": None, "status": "pending_fill",
            "venue_code": "XNAS",
        }
    }
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    cancel_calls: list[str] = []

    def cancel_h(req):
        cancel_calls.append(req.url.path)
        return httpx.Response(200, json={})

    http = strategy_module.make_http_client(
        "http://x",
        transport=_make_handler({
            ("DELETE", "/api/v2/orders/"): cancel_h,
        }),
    )
    out = strategy_module.execute_kill_l3(
        state, cfg_with_paths, http, "k", state_path=state_path,
    )
    assert "GHOST" in out
    # Children + parent all canceled (3 calls: target, stop, parent).
    assert len(cancel_calls) == 3
    assert any("/T-1" in p for p in cancel_calls)
    assert any("/S-1" in p for p in cancel_calls)
    assert any("/P-LIVE" in p for p in cancel_calls)


def test_poll_fills_canonical_status_for_target_child(
    strategy_module, tmp_path,
):
    """Item 8 (#6) regression: a child fill that arrives with
    ``canonical_status=FILLED`` but ``status`` set to a translator-
    specific raw value (e.g. ``done``) used to be missed because the
    target/stop branches only checked the raw status. The canonical
    check now applies to children + exits too."""
    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json={
            "data": {"orders": [
                {"id": "T-1", "status": "done", "canonical_status": "FILLED",
                 "filled_avg_price": "115.00", "filled_qty": "10"},
            ], "count": 1},
        })
    )
    http = strategy_module.make_http_client("http://x", transport=transport)
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "AAPL": {
            "parent_order_id": "P-1",
            "child_order_ids": {"target": "T-1", "stop": "S-1"},
            "qty": 10, "entry_price": 100.0, "status": "filled",
            "venue_code": "XNAS",
        }
    }
    events = strategy_module.poll_fills(
        state, http, "k", state_path=tmp_path / "state.json",
    )
    # Target child is recorded as filled even though native status
    # was "done" rather than the canonical "filled".
    assert events
    target_ev = next(e for e in events if e.role == "target")
    assert target_ev.status == "FILLED"
    pos = state["open_positions"]["AAPL"]
    assert "target" in (pos.get("filled_children") or {})


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


def test_daily_summary_count_opened_walks_jsonl_entries(
    strategy_module, cfg_with_paths, tmp_path,
):
    """Item 8 (#8) regression: count_opened must reflect actual
    entries opened during the session — including intraday round-
    trips — not the current open_positions length."""
    state = strategy_module.blank_state()
    # Carryover position from yesterday (must NOT be counted as opened today).
    state["open_positions"] = {
        "OLD": {"parent_order_id": "P-OLD", "qty": 10, "entry_price": 50.0,
                "status": "filled",
                "entry_timestamp": "2026-05-04T13:30:00+00:00"}
    }
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    summary_path = Path(cfg_with_paths["paths"]["daily_summary_path"])
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    today_iso = "2026-05-05"
    # Three opens today: AAPL (still open), MSFT (round-tripped — also has a
    # closure record), GOOG (still open).
    for rec in [
        {"record_type": "opened", "ticker": "AAPL", "qty": 10,
         "entry_price": 100.0,
         "entry_timestamp": today_iso + "T13:30:00+00:00"},
        {"record_type": "opened", "ticker": "MSFT", "qty": 5,
         "entry_price": 200.0,
         "entry_timestamp": today_iso + "T13:31:00+00:00"},
        {"record_type": "opened", "ticker": "GOOG", "qty": 1,
         "entry_price": 1000.0,
         "entry_timestamp": today_iso + "T13:32:00+00:00"},
        # Intraday round-trip: MSFT closes target_hit.
        {"record_type": "closure", "ticker": "MSFT", "qty": 5,
         "entry_price": 200.0, "exit_price": 230.0,
         "entry_timestamp": today_iso + "T13:31:00+00:00",
         "exit_timestamp": today_iso + "T15:00:00+00:00",
         "realized_pnl": 150.0, "reason": "target_hit"},
        # Yesterday's open (not counted as opened today).
        {"record_type": "opened", "ticker": "OLD", "qty": 10,
         "entry_price": 50.0,
         "entry_timestamp": "2026-05-04T13:30:00+00:00"},
    ]:
        with open(summary_path, "a") as f:
            f.write(json.dumps(rec) + "\n")

    rec = strategy_module.write_session_summary(
        state, cfg_with_paths,
        summary_path=summary_path, state_path=state_path,
        today_iso=today_iso,
    )
    # Three opens today (AAPL, MSFT, GOOG); MSFT round-tripped so it
    # appears in BOTH counts. OLD's open record is yesterday-dated and
    # not counted.
    assert rec["count_opened"] == 3
    assert rec["count_closed"] == 1


def test_process_fill_events_writes_opened_record_on_parent_fill(
    strategy_module, cfg_with_paths, tmp_path,
):
    """Item 8 (#8): when poll_fills emits a parent FILLED event,
    process_fill_events_for_closures appends an ``opened`` jsonl
    record so the daily summary can count today's actual entries."""
    state = strategy_module.blank_state()
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    summary_path = Path(cfg_with_paths["paths"]["daily_summary_path"])
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    state["open_positions"] = {
        "AAPL": {
            "parent_order_id": "P-1",
            "child_order_ids": {"target": "", "stop": ""},
            "qty": 10, "entry_price": 13.00, "status": "filled",
            "entry_timestamp": "2026-05-05T13:30:00+00:00",
            "venue_code": "XNAS", "link_id": "BOWAKA-AAPL-100",
            "entry_features": {"rvol": 2.0},
        }
    }
    parent_filled = strategy_module.FillEvent(
        ticker="AAPL", order_id="P-1", role="parent",
        status="FILLED", filled_qty=10, filled_avg_price=13.00,
        raw={"id": "P-1", "status": "filled", "filled_avg_price": "13.00"},
    )
    strategy_module.process_fill_events_for_closures(
        [parent_filled], state, cfg_with_paths,
        state_path=state_path, summary_path=summary_path,
    )
    lines = summary_path.read_text(encoding="utf-8").splitlines()
    opened = [json.loads(line) for line in lines if line.strip()
              and json.loads(line).get("record_type") == "opened"]
    assert len(opened) == 1
    assert opened[0]["ticker"] == "AAPL"
    assert opened[0]["qty"] == 10
    assert opened[0]["entry_price"] == 13.00
    assert opened[0]["venue_code"] == "XNAS"


# ---------------------------------------------------------------- analytic logging


def test_opened_record_carries_analytic_enrichment(
    strategy_module, cfg_with_paths, tmp_path,
):
    """The opened record carries the enrichment fields the analyst
    needs to tune signal_strength / target / stop / sizing — not just
    ticker+qty+entry_price."""
    state = strategy_module.blank_state()
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    summary_path = Path(cfg_with_paths["paths"]["daily_summary_path"])
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    # Mirror what submit_parent_market_buy stamps on pos.
    state["open_positions"] = {
        "BLDP": {
            "parent_order_id": "P-1",
            "child_order_ids": {"target": "", "stop": ""},
            "qty": 100,
            "entry_price": 5.00,
            "status": "filled",
            "entry_timestamp": "2026-05-07T13:30:00+00:00",
            "venue_code": "XNAS",
            "exchange": "NASDAQ",
            "candidate_close": 4.76,         # prior close
            "signal_strength": 8.5,
            "target_pct": 0.15,
            "stop_pct": 0.08,
            "target_price": 5.75,            # filled by submit_pending_oco_children
            "stop_price": 4.60,
            "bracket_pricing_mode": "actual_fill",
            "equity_at_entry": 100_000.0,
            "entry_features": {"rvol": 2.5, "atr_pct": 0.08},
            "link_id": "BOWAKA-BLDP-100",
            "peak_since_entry": 5.00,
            "trough_since_entry": 5.00,
        }
    }
    parent_ev = strategy_module.FillEvent(
        ticker="BLDP", order_id="P-1", role="parent",
        status="FILLED", filled_qty=100, filled_avg_price=5.00,
        raw={},
    )
    strategy_module.process_fill_events_for_closures(
        [parent_ev], state, cfg_with_paths,
        state_path=state_path, summary_path=summary_path,
    )
    rec = next(
        json.loads(line) for line in summary_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("record_type") == "opened"
    )
    # All the why-bought enrichment fields.
    assert rec["signal_strength"] == 8.5
    assert rec["candidate_close"] == 4.76
    # Gap = (5.00 - 4.76) / 4.76 ≈ 0.0504
    assert abs(rec["gap_at_open_pct"] - (5.00 - 4.76) / 4.76) < 1e-6
    assert rec["target_pct"] == 0.15
    assert rec["stop_pct"] == 0.08
    assert rec["target_price"] == 5.75
    assert rec["stop_price"] == 4.60
    assert rec["bracket_pricing_mode"] == "actual_fill"
    assert rec["equity_at_entry"] == 100_000.0
    assert rec["notional"] == 500.0
    assert abs(rec["notional_pct_of_equity"] - 0.005) < 1e-9
    assert rec["exchange"] == "NASDAQ"
    assert rec["entry_features"] == {"rvol": 2.5, "atr_pct": 0.08}


def test_close_position_carries_mfe_mae_and_hold_duration(
    strategy_module, cfg_with_paths, tmp_path,
):
    """closure record must carry MFE/MAE/hold_days/percent fields so
    the analyst can compute reward-to-risk per signal regime."""
    state = strategy_module.blank_state()
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    summary_path = Path(cfg_with_paths["paths"]["daily_summary_path"])
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    # Position open since 2 trading days ago, peak/trough already
    # recorded by daily_marks ticking through prior sessions.
    today_iso = _to_eastern_today_iso()  # helper below
    state["open_positions"] = {
        "AAPL": {
            "parent_order_id": "P-1",
            "child_order_ids": {"target": "T-1", "stop": "S-1"},
            "qty": 10,
            "entry_price": 100.0,
            "entry_timestamp": "2026-05-04T13:30:00+00:00",
            "status": "filled",
            "venue_code": "XNAS", "exchange": "NASDAQ",
            "candidate_close": 99.0,
            "signal_strength": 9.0,
            "target_pct": 0.15, "stop_pct": 0.08,
            "target_price": 115.0, "stop_price": 92.0,
            "bracket_pricing_mode": "actual_fill",
            "peak_since_entry": 110.0,    # MFE peak
            "trough_since_entry": 95.0,   # MAE trough
            "entry_features": {"rvol": 2.5},
            "link_id": "BOWAKA-AAPL-1",
        }
    }
    rec = strategy_module.close_position(
        "AAPL", state, cfg_with_paths,
        state_path=state_path, summary_path=summary_path,
        exit_price=115.0, reason="target_hit",
    )
    # Excursion math: 10 shares * (peak_or_trough - entry).
    assert rec["mfe_dollar"] == 100.0          # (110 - 100) * 10
    assert rec["mae_dollar"] == -50.0          # (95 - 100) * 10
    assert abs(rec["mfe_pct"] - 0.10) < 1e-9
    assert abs(rec["mae_pct"] + 0.05) < 1e-9
    assert rec["peak_since_entry"] == 110.0
    assert rec["trough_since_entry"] == 95.0
    # entry_to_exit = (115 - 100) / 100 = 0.15
    assert abs(rec["entry_to_exit_pct"] - 0.15) < 1e-9
    # Hold-days >= 1 (entry was 5/4, "today" is later).
    assert isinstance(rec["hold_trading_days"], int)
    assert rec["hold_trading_days"] >= 1
    # Plus the why-bought fields are carried through.
    assert rec["signal_strength"] == 9.0
    assert rec["candidate_close"] == 99.0
    assert rec["target_pct"] == 0.15
    assert rec["bracket_pricing_mode"] == "actual_fill"


def _to_eastern_today_iso() -> str:
    import pytz
    from datetime import datetime as _dt
    return _dt.now(pytz.timezone("America/New_York")).date().isoformat()


def test_write_daily_marks_writes_one_record_per_filled_position(
    strategy_module, cfg_with_paths, tmp_path,
):
    """write_daily_marks fetches today's bar for each filled position
    and appends a daily_mark record with OHLCV + unrealized P&L +
    excursion + recomputed signals."""
    import pandas as pd
    from datetime import date, datetime, timezone

    state = strategy_module.blank_state()
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    summary_path = Path(cfg_with_paths["paths"]["daily_summary_path"])
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    state["open_positions"] = {
        "AAPL": {
            "parent_order_id": "P-1",
            "child_order_ids": {"target": "T-1", "stop": "S-1"},
            "qty": 10, "entry_price": 100.0,
            "entry_timestamp": "2026-05-04T13:30:00+00:00",
            "status": "filled",
            "venue_code": "XNAS",
            "candidate_close": 99.0,
            "signal_strength": 9.0,
            "target_pct": 0.15, "stop_pct": 0.08,
            "target_price": 115.0, "stop_price": 92.0,
            "bracket_pricing_mode": "actual_fill",
            "peak_since_entry": 102.0,
            "trough_since_entry": 98.0,
            "link_id": "BOWAKA-AAPL-1",
        }
    }
    # Synthesize a bars DF with enough history that compute_features_single
    # produces real numbers (lookback_days=20 in the cfg).
    today = date(2026, 5, 5)
    rows = []
    base = 95.0
    for i in range(30):
        d = pd.Timestamp("2026-04-01") + pd.Timedelta(days=i)
        rows.append({
            "ts": d.isoformat(),
            "open": base + 0.1 * i, "high": base + 0.1 * i + 1.0,
            "low": base + 0.1 * i - 1.0, "close": base + 0.1 * i + 0.5,
            "volume": 1_000_000 + i * 5000,
        })
    # Make today's bar the LAST row with a clear high/low/close so we
    # can assert exact mark values.
    rows.append({
        "ts": today.isoformat() + "T00:00:00",
        "open": 99.5, "high": 105.0, "low": 97.5, "close": 103.0,
        "volume": 5_000_000,
    })
    df = pd.DataFrame(rows)

    # Patch the bars fetcher to avoid network.
    import strategies.scripts.bowaka_strategy as mod  # noqa: F401
    original_fetch = strategy_module.fetch_daily_bars_for_signal_fade

    def _fake_fetch(ticker, venue_code, http, api_key, *, lookback_calendar_days, end):
        out = df.copy()
        out["timestamp"] = pd.to_datetime(out["ts"])
        return out.drop(columns=["ts"]).sort_values("timestamp").reset_index(drop=True)

    strategy_module.fetch_daily_bars_for_signal_fade = _fake_fetch
    try:
        marked = strategy_module.write_daily_marks(
            cfg_with_paths, state, http=None, api_key="k",
            today_et=today,
            summary_path=summary_path, state_path=state_path,
            now_utc=datetime.now(timezone.utc),
        )
    finally:
        strategy_module.fetch_daily_bars_for_signal_fade = original_fetch

    assert marked == ["AAPL"]
    rec = next(
        json.loads(line) for line in summary_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("record_type") == "daily_mark"
    )
    assert rec["ticker"] == "AAPL"
    assert rec["session_date"] == today.isoformat()
    assert rec["mark_price"] == 103.0
    assert rec["high"] == 105.0
    assert rec["low"] == 97.5
    assert rec["volume"] == 5_000_000
    # Unrealized = (103 - 100) * 10 = 30
    assert rec["unrealized_pnl"] == 30.0
    # Peak should expand to today's high (105 > 102), trough stays
    # at the prior 98 (today's 97.5 is BELOW it).
    assert rec["peak_since_entry"] == 105.0
    assert rec["trough_since_entry"] == 97.5
    assert rec["mfe_dollar"] == 50.0   # (105 - 100) * 10
    assert rec["mae_dollar"] == -25.0  # (97.5 - 100) * 10
    # State is updated for the next mark.
    assert state["open_positions"]["AAPL"]["peak_since_entry"] == 105.0
    assert state["open_positions"]["AAPL"]["trough_since_entry"] == 97.5
    # Recomputed features present (we passed enough history).
    assert isinstance(rec.get("current_features"), dict)
    # Per-gate breakdown matches the configured signal_gates.
    gates = rec["signal_fade_gates"]
    for k in ("rvol", "atr_pct", "range_expansion",
              "close_location", "ema_distance", "ema_slope"):
        assert k in gates and "passed" in gates[k]


def test_write_daily_marks_idempotent_per_day(
    strategy_module, cfg_with_paths, tmp_path,
):
    """Second call on the same trading day is a no-op (dedupe via
    state.daily_marks_written_for_date)."""
    import pandas as pd
    from datetime import date, datetime, timezone

    state = strategy_module.blank_state()
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    summary_path = Path(cfg_with_paths["paths"]["daily_summary_path"])
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    state["daily_marks_written_for_date"] = "2026-05-05"

    n_calls = [0]

    def _fake_fetch(*a, **kw):
        n_calls[0] += 1
        return pd.DataFrame()

    original = strategy_module.fetch_daily_bars_for_signal_fade
    strategy_module.fetch_daily_bars_for_signal_fade = _fake_fetch
    try:
        out = strategy_module.write_daily_marks(
            cfg_with_paths, state, http=None, api_key="k",
            today_et=date(2026, 5, 5),
            summary_path=summary_path, state_path=state_path,
            now_utc=datetime.now(timezone.utc),
        )
    finally:
        strategy_module.fetch_daily_bars_for_signal_fade = original
    assert out == []
    assert n_calls[0] == 0  # short-circuited on dedupe


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


# ---------------------------------------------------------------- prefilter handshake


def test_handshake_passes_when_gates_match(
    strategy_module, cfg_with_paths, tmp_path,
):
    """Item 8 (handshake): identical gates + indicators → no error."""
    pf = tmp_path / "bowaka_prefilter.yaml"
    pf.write_text(
        "signals:\n"
        "  rvol_min: 1.5\n"
        "  atr_pct_min: 0.06\n"
        "  range_expansion_min: 1.25\n"
        "  close_location_min: 0.60\n"
        "  ema_distance_min: 0.0\n"
        "  ema_slope_min: 0.0\n"
        "indicators:\n"
        "  lookback_days: 20\n"
        "  atr_days: 14\n"
        "  ema_days: 10\n"
        "  ema_slope_lookback: 3\n"
    )
    cfg = dict(cfg_with_paths)
    cfg["prefilter_handshake"] = {
        **(cfg.get("prefilter_handshake") or {}),
        "prefilter_yaml_path": str(pf),
    }
    strategy_module.verify_prefilter_handshake(cfg)


def test_handshake_raises_on_signal_gate_drift(
    strategy_module, cfg_with_paths, tmp_path,
):
    pf = tmp_path / "bowaka_prefilter.yaml"
    pf.write_text(
        "signals:\n"
        "  rvol_min: 2.0\n"  # strategy expects 1.5
        "  atr_pct_min: 0.06\n"
        "  range_expansion_min: 1.25\n"
        "  close_location_min: 0.60\n"
        "  ema_distance_min: 0.0\n"
        "  ema_slope_min: 0.0\n"
        "indicators:\n"
        "  lookback_days: 20\n"
        "  atr_days: 14\n"
        "  ema_days: 10\n"
        "  ema_slope_lookback: 3\n"
    )
    cfg = dict(cfg_with_paths)
    cfg["prefilter_handshake"] = {
        **(cfg.get("prefilter_handshake") or {}),
        "prefilter_yaml_path": str(pf),
    }
    with pytest.raises(strategy_module.HandshakeMismatch, match="rvol_min"):
        strategy_module.verify_prefilter_handshake(cfg)


def test_handshake_raises_on_indicator_window_drift(
    strategy_module, cfg_with_paths, tmp_path,
):
    pf = tmp_path / "bowaka_prefilter.yaml"
    pf.write_text(
        "signals:\n"
        "  rvol_min: 1.5\n"
        "  atr_pct_min: 0.06\n"
        "  range_expansion_min: 1.25\n"
        "  close_location_min: 0.60\n"
        "  ema_distance_min: 0.0\n"
        "  ema_slope_min: 0.0\n"
        "indicators:\n"
        "  lookback_days: 30\n"  # strategy expects 20
        "  atr_days: 14\n"
        "  ema_days: 10\n"
        "  ema_slope_lookback: 3\n"
    )
    cfg = dict(cfg_with_paths)
    cfg["prefilter_handshake"] = {
        **(cfg.get("prefilter_handshake") or {}),
        "prefilter_yaml_path": str(pf),
    }
    with pytest.raises(strategy_module.HandshakeMismatch, match="lookback_days"):
        strategy_module.verify_prefilter_handshake(cfg)


def test_handshake_skips_when_prefilter_yaml_missing(
    strategy_module, cfg_with_paths, tmp_path,
):
    """Missing prefilter yaml → log warning, don't fail (don't break
    operators who relocated files)."""
    cfg = dict(cfg_with_paths)
    cfg["prefilter_handshake"] = {
        **(cfg.get("prefilter_handshake") or {}),
        "prefilter_yaml_path": str(tmp_path / "nonexistent.yaml"),
    }
    strategy_module.verify_prefilter_handshake(cfg)  # no raise


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
    n_get_orders = [0]
    n_post_orders = [0]

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
                "id": "P-OCO",
                "legs": [
                    {"id": "T-OCO", "order_type": "limit"},
                    {"id": "S-OCO", "order_type": "stop"},
                ],
            }}})
        if method == "GET" and path == "/api/v2/orders":
            n_get_orders[0] += 1
            return httpx.Response(200, json={"data": {"orders": [], "count": 0}})
        if method == "DELETE":
            return httpx.Response(200, json={})
        if method == "POST" and path == "/api/v2/orders":
            n_post_orders[0] += 1
            return httpx.Response(200, json={"data": {"native_response": {"id": "P-1"}}})
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
    # Item 4 (actual_fill default): the first session tick posts a
    # MARKET BUY parent to /api/v2/orders. The /api/v2/orders/combo
    # OCO bracket only fires on a later tick once poll_fills records
    # the fill — which doesn't happen in this single-tick smoke test.
    assert n_post_orders[0] == 1
    assert n_combo[0] == 0
    state = strategy_module.load_state(Path(cfg_with_paths["paths"]["state_path"]))
    assert "AAPL" in state["open_positions"]
    assert state["open_positions"]["AAPL"]["bracket_pricing_mode"] == "actual_fill"
    assert state["session_date"] == "2026-05-05"
    assert state["daily_pnl_baseline_equity"] == 100_000.0
