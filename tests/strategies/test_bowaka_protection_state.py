"""Phase 2 — protection state from broker truth + startup repair.

Covers:
* :func:`derive_protection_state` returns the right derived state
  across the cases in the audit report.
* :func:`has_confirmed_protection` no longer trusts the stored
  ``protection_status`` string when no broker snapshot is provided.
* :func:`reconcile_at_startup` recomputes protection_state and emits
  ``startup_repair_triggered`` for the four unprotected positions in
  the captured fixture.
* :func:`replace_protection_with_exit` is atomic: never cancels OCO
  children before the replacement exit is accepted.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import httpx
import pytest

import bowaka_strategy as bw


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
STATE_FIXTURE = FIXTURE_DIR / "state_2026_05_15_unprotected.json"


# ---- derive_protection_state -----------------------------------------


def test_derive_filled_unprotected_when_children_empty_no_exit() -> None:
    pos = {
        "status": "filled",
        "protection_status": "oco_attached",
        "child_order_ids": {"stop": "", "target": ""},
    }
    # No broker_orders provided -> empty dict semantics.
    assert bw.derive_protection_state(pos, {}) == "filled_unprotected"


def test_derive_oco_attached_confirmed_when_both_children_active() -> None:
    pos = {
        "status": "filled",
        "child_order_ids": {"stop": "S-1", "target": "T-1"},
    }
    bo = {
        "S-1": {"status": "new"},
        "T-1": {"status": "accepted"},
    }
    assert bw.derive_protection_state(pos, bo) == "oco_attached_confirmed"


def test_derive_rebracket_pending_when_flag_set() -> None:
    pos = {
        "status": "filled",
        "rebracket_pending": True,
        "child_order_ids": {"stop": "", "target": ""},
    }
    assert bw.derive_protection_state(pos, {}) == "rebracket_pending"


def test_derive_exit_order_accepted_when_exit_live_at_broker() -> None:
    pos = {
        "status": "exiting",
        "exit_order_id": "E-1",
    }
    bo = {"E-1": {"status": "accepted"}}
    assert bw.derive_protection_state(pos, bo) == "exit_order_accepted"


def test_derive_exit_order_pending_when_submitted_but_no_echo() -> None:
    pos = {
        "status": "filled",
        "exit_order_id": "E-1",
        "exit_submitted_at": "2026-05-15T19:30:00+00:00",
    }
    bo = {}  # no broker echo yet
    assert bw.derive_protection_state(pos, bo) == "exit_order_pending"


def test_derive_closed_for_terminal_status() -> None:
    pos = {"status": "closed"}
    assert bw.derive_protection_state(pos, {}) == "closed"


def test_derive_flat_for_flat_status() -> None:
    pos = {"status": "flat"}
    assert bw.derive_protection_state(pos, {}) == "flat"


def test_derive_pending_entry_for_pre_fill_status() -> None:
    for st in ("pending_entry", "submitted", "pending_fill"):
        pos = {"status": st}
        assert bw.derive_protection_state(pos, {}) == "pending_entry", st


def test_derive_fallback_stop_attached_when_fallback_live() -> None:
    pos = {
        "status": "filled",
        "fallback_stop_order_id": "FB-1",
        "child_order_ids": {"stop": "", "target": ""},
    }
    bo = {"FB-1": {"status": "new"}}
    assert (
        bw.derive_protection_state(pos, bo)
        == "fallback_stop_attached_confirmed"
    )


def test_derive_protection_repair_failed_when_marker_set() -> None:
    pos = {
        "status": "filled",
        "protection_repair_failed_at": "2026-05-15T20:00:00+00:00",
        "child_order_ids": {"stop": "", "target": ""},
    }
    assert bw.derive_protection_state(pos, {}) == "protection_repair_failed"


# ---- has_confirmed_protection (the bug fix) --------------------------


def test_has_confirmed_protection_distrusts_stored_string_without_snapshot() -> None:
    """The 2026-05-15 bug: position has protection_status="oco_attached"
    and empty child IDs. Without a broker snapshot we MUST NOT trust
    the stored string."""
    pos = {
        "status": "filled",
        "protection_status": "oco_attached",
        "child_order_ids": {"stop": "", "target": ""},
    }
    assert bw.has_confirmed_protection(pos, broker_orders=None) is False


def test_has_confirmed_protection_trusts_terminal_states_without_snapshot() -> None:
    assert bw.has_confirmed_protection({"status": "closed"}, None) is True
    assert bw.has_confirmed_protection({"status": "flat"}, None) is True


def test_has_confirmed_protection_with_broker_snapshot_oco_live() -> None:
    pos = {
        "status": "filled",
        "child_order_ids": {"stop": "S-1", "target": "T-1"},
    }
    bo = {"S-1": {"status": "new"}, "T-1": {"status": "accepted"}}
    assert bw.has_confirmed_protection(pos, bo) is True


def test_has_confirmed_protection_with_empty_snapshot_unprotected() -> None:
    pos = {
        "status": "filled",
        "child_order_ids": {"stop": "S-1", "target": "T-1"},
    }
    assert bw.has_confirmed_protection(pos, {}) is False


# ---- 2026-05-15 state.json replay (ASPN/ONDS/PCT/QS) -----------------


def _load_fixture_state() -> dict:
    return json.loads(STATE_FIXTURE.read_text())


def test_replay_all_four_positions_derive_to_filled_unprotected() -> None:
    """The four positions in the captured state file are wearing
    ``oco_attached`` with empty child IDs. Each MUST derive to
    ``filled_unprotected``."""
    state = _load_fixture_state()
    for ticker, pos in state["open_positions"].items():
        derived = bw.derive_protection_state(pos, {})
        assert derived == "filled_unprotected", (
            f"{ticker}: expected filled_unprotected, got {derived}; "
            f"pos={pos}"
        )


# ---- reconcile_at_startup startup repair -----------------------------


def _build_http_with_unprotected_positions(state: dict) -> httpx.Client:
    """A stub broker that echoes back the four positions in state but
    reports no open orders — matches the live situation where the OCO
    submits silently failed so nothing was ever attached at the
    broker."""

    positions = []
    for ticker, pos in (state.get("open_positions") or {}).items():
        positions.append({
            "canonical_symbol": ticker,
            "symbol": ticker,
            "ticker": ticker,
            "quantity": str(pos.get("qty") or 0),
            "qty": str(pos.get("qty") or 0),
        })

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/api/v2/positions":
            return httpx.Response(
                200, json={"data": {"positions": positions}},
            )
        if path == "/api/v2/orders":
            return httpx.Response(
                200, json={"data": {"orders": []}},
            )
        return httpx.Response(404, json={"error": "no-route", "path": path})

    return httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://x",
    )


def test_reconcile_at_startup_repairs_unprotected_positions(
    tmp_path, cfg_with_paths, httpx_router,
):
    state = _load_fixture_state()
    # Push the fixture into the cfg's state_path so reconcile can
    # write it back, and replicate the 4-position open_positions
    # dict.
    cfg = copy.deepcopy(cfg_with_paths)
    state_path = Path(cfg["paths"]["state_path"])
    summary_path = Path(cfg["paths"]["daily_summary_path"])
    bw.save_state(state, state_path)
    http = _build_http_with_unprotected_positions(state)
    res = bw.reconcile_at_startup(
        state, http, "k",
        state_path=state_path, summary_path=summary_path, cfg=cfg,
    )
    # All four positions should now have a derived protection_state
    # of filled_unprotected and a startup_repair_triggered marker.
    assert set(res["startup_repair_triggered"]) == {
        "ASPN", "ONDS", "PCT", "QS",
    }
    for ticker in ("ASPN", "ONDS", "PCT", "QS"):
        pos = state["open_positions"][ticker]
        assert pos["protection_state"] == "filled_unprotected", (
            f"{ticker}: {pos}"
        )

    # The ledger has one startup_repair_triggered event per position.
    ledger_path = bw._ledger_path(cfg)
    events = []
    if ledger_path.exists():
        for line in ledger_path.read_text().splitlines():
            if line.strip():
                events.append(json.loads(line))
    triggered = [
        e for e in events
        if e.get("event_type") == "startup_repair_triggered"
    ]
    triggered_tickers = sorted(e["ticker"] for e in triggered)
    assert triggered_tickers == ["ASPN", "ONDS", "PCT", "QS"]


# ---- replace_protection_with_exit atomicity --------------------------


def test_replace_protection_does_not_cancel_children_on_rejection(
    tmp_path, cfg_with_paths,
):
    pos = {
        "link_id": "T-X",
        "status": "filled",
        "child_order_ids": {"stop": "S-1", "target": "T-1"},
        "qty": 10,
        "entry_price": 100.0,
    }
    cancels: list[str] = []

    def submit_callable() -> dict:
        # Simulated rejection — broker returned HTTP 422.
        return {"_http_status": 422, "error": "rejected"}

    def cancel_handler(req: httpx.Request) -> httpx.Response:
        # Track any cancel attempt — the test asserts there is none.
        cancels.append(req.url.path)
        return httpx.Response(200, json={"data": {"order_id": "X"}})

    http = httpx.Client(
        transport=httpx.MockTransport(cancel_handler),
        base_url="http://x",
    )
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    state: bw.State = bw.blank_state()
    state["open_positions"]["X"] = pos
    bw.save_state(state, state_path)

    ok, reason = bw.replace_protection_with_exit(
        "X", pos, cfg_with_paths, http, "k",
        exit_submit_callable=submit_callable,
        state=state, state_path=state_path,
    )
    assert ok is False
    assert reason and "422" in reason
    # Children intact, no cancel issued.
    assert pos["child_order_ids"]["stop"] == "S-1"
    assert pos["child_order_ids"]["target"] == "T-1"
    assert cancels == []


def test_replace_protection_cancels_children_only_after_accepted_exit(
    tmp_path, cfg_with_paths,
):
    pos = {
        "link_id": "T-Y",
        "status": "filled",
        "child_order_ids": {"stop": "S-1", "target": "T-1"},
        "qty": 10,
        "entry_price": 100.0,
    }
    submit_attempts: list[int] = []

    def submit_callable() -> dict:
        submit_attempts.append(1)
        return {
            "_http_status": 200,
            "data": {"native_response": {"id": "EXIT-1"}},
        }

    cancel_calls: list[str] = []

    def cancel_handler(req: httpx.Request) -> httpx.Response:
        # DELETE /api/v2/orders/<id> is the cancel path.
        if req.method == "DELETE":
            cancel_calls.append(req.url.path)
        return httpx.Response(200, json={"data": {}})

    http = httpx.Client(
        transport=httpx.MockTransport(cancel_handler),
        base_url="http://x",
    )
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    state: bw.State = bw.blank_state()
    state["open_positions"]["Y"] = pos
    bw.save_state(state, state_path)

    ok, reason = bw.replace_protection_with_exit(
        "Y", pos, cfg_with_paths, http, "k",
        exit_submit_callable=submit_callable,
        state=state, state_path=state_path,
    )
    assert ok is True
    assert reason is None
    assert pos["exit_order_id"] == "EXIT-1"
    assert pos["status"] == "exiting"
    # At least one cancel attempt landed for each child.
    assert len(cancel_calls) >= 1


def test_replace_protection_with_cancel_failure_keeps_exit_alive(
    tmp_path, cfg_with_paths,
):
    """Per Phase 2.5: even if the post-acceptance cancel attempts
    themselves fail, the replacement exit is left in place. The
    helper does NOT roll back the exit submit."""
    pos = {
        "link_id": "T-Z",
        "status": "filled",
        "child_order_ids": {"stop": "S-1", "target": "T-1"},
        "qty": 10,
        "entry_price": 100.0,
    }

    def submit_callable() -> dict:
        return {
            "_http_status": 200,
            "data": {"native_response": {"id": "EXIT-9"}},
        }

    def cancel_handler(req: httpx.Request) -> httpx.Response:
        # Every cancel fails with 500 — exit must still stick.
        return httpx.Response(500, json={"error": "boom"})

    http = httpx.Client(
        transport=httpx.MockTransport(cancel_handler),
        base_url="http://x",
    )
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    state: bw.State = bw.blank_state()
    state["open_positions"]["Z"] = pos
    bw.save_state(state, state_path)

    ok, _ = bw.replace_protection_with_exit(
        "Z", pos, cfg_with_paths, http, "k",
        exit_submit_callable=submit_callable,
        state=state, state_path=state_path,
    )
    assert ok is True
    assert pos["exit_order_id"] == "EXIT-9"
    assert pos["status"] == "exiting"
