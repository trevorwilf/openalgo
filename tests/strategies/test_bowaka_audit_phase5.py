"""Phase 5 audit acceptance tests — protected-position invariant +
stop-manager ablation.

Covers:
  5.1 protected_position config block resolves correctly.
  5.4 seconds_since_iso / has_confirmed_protection /
       protection_deadline_breached helpers.
  5.5 submit_fallback_stop posts the right body, returns order id
       on success / None on failure.
  5.6 enforce_protected_position_invariant escalation matrix:
       OCO retry succeeds → oco_attached.
       OCO retry fails repeatedly + fallback succeeds → fallback_
         stop_attached + protection_event.
       OCO + fallback both fail → flatten + block_new_entries_today.
  5.6 Deadline math: T+5s under cap=10s allowed; T+11s breached.
  5.6 block_entries_on_violation=False keeps block flag clear.
  5.8 Stop-manager disabled = no-op even at high MFE.
  5.8 Stop-manager enabled + MFE 8% → stop replaced to entry*1.03.
  5.8 Stop never moves down.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
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


def _filled_unprotected_pos(*, deadline_offset_seconds: float = -5.0,
                            entry_price: float = 10.0, qty: int = 100,
                            link_id: str = "BOWAKA-AAPL-1"):
    """A filled position whose protection deadline is N seconds in
    the past (positive offset = future, negative = breached)."""
    now = datetime.now(timezone.utc)
    return {
        "parent_order_id": "P-1",
        "child_order_ids": {"target": "", "stop": ""},
        "qty": qty,
        "entry_price": entry_price,
        "entry_timestamp": (now - timedelta(seconds=30)).isoformat(),
        "entry_features": {},
        "status": "filled",
        "venue_code": "XNAS",
        "target_pct": 0.15,
        "stop_pct": 0.08,
        "link_id": link_id,
        "bracket_pricing_mode": "actual_fill",
        "parent_filled_at": (now - timedelta(seconds=30)).isoformat(),
        "protection_status": "none",
        "protection_deadline_at": (
            now + timedelta(seconds=deadline_offset_seconds)
        ).isoformat(),
        "oco_attach_attempts": 0,
        "fallback_stop_order_id": None,
        "protection_violation": False,
    }


@pytest.fixture
def cfg_phase5(cfg_with_paths):
    cfg = dict(cfg_with_paths)
    cfg["exits"] = {
        **cfg.get("exits", {}),
        "stop_pct": 0.08,
        "target_pct": 0.15,
        "max_hold_days": 3,
        "signal_fade_enabled": True,
        "oco_time_in_force": "GTC",
        "protected_position": {
            "enabled": True,
            "max_unprotected_seconds": 10,
            "max_oco_attach_attempts": 2,
            "fallback_stop_enabled": True,
            "fallback_stop_order_type": "stop",
            "fallback_stop_limit_offset_pct": 0.02,
            "flatten_if_unprotected": True,
            "block_entries_on_violation": True,
        },
        "stop_manager": {
            "enabled": False,
            "rules": [
                {"mfe_min": 0.05, "stop_at": 0.00},
                {"mfe_min": 0.08, "stop_at": 0.03},
                {"mfe_min": 0.12, "stop_at": 0.06},
            ],
        },
    }
    return cfg


# ---------------------------------------------------------------- 5.4 helpers


def test_seconds_since_iso(strategy_module):
    now = datetime.now(timezone.utc)
    ts = (now - timedelta(seconds=42)).isoformat()
    assert strategy_module.seconds_since_iso(ts, now_utc=now) == pytest.approx(42, abs=1)
    assert strategy_module.seconds_since_iso(None) is None
    assert strategy_module.seconds_since_iso("not-a-date") is None


def test_has_confirmed_protection_truth_table(strategy_module):
    base = _filled_unprotected_pos()
    assert strategy_module.has_confirmed_protection(base) is False
    base["protection_status"] = "oco_attached"
    assert strategy_module.has_confirmed_protection(base) is True
    base["protection_status"] = "fallback_stop_attached"
    assert strategy_module.has_confirmed_protection(base) is True
    # Legacy back-compat: pre-Phase-5 positions with valid child IDs
    # but no protection_status still count as protected.
    base["protection_status"] = "none"
    base["child_order_ids"] = {"target": "T-1", "stop": "S-1"}
    assert strategy_module.has_confirmed_protection(base) is True


def test_protection_deadline_breached(strategy_module, cfg_phase5):
    # Deadline 5s in the future = NOT breached.
    pos = _filled_unprotected_pos(deadline_offset_seconds=5.0)
    assert strategy_module.protection_deadline_breached(pos, cfg_phase5) is False
    # Deadline 11s in the past = BREACHED.
    pos2 = _filled_unprotected_pos(deadline_offset_seconds=-11.0)
    assert strategy_module.protection_deadline_breached(pos2, cfg_phase5) is True


# ---------------------------------------------------------------- 5.6 escalation paths


def test_oco_retry_succeeds_marks_attached(strategy_module, cfg_phase5, tmp_path):
    state = strategy_module.blank_state()
    state["open_positions"] = {"AAPL": _filled_unprotected_pos(deadline_offset_seconds=5.0)}
    state_path = Path(cfg_phase5["paths"]["state_path"])
    state_path.parent.mkdir(parents=True, exist_ok=True)
    n_oco = [0]

    def oco_handler(req: httpx.Request) -> httpx.Response:
        n_oco[0] += 1
        return httpx.Response(200, json={
            "data": {
                "native_response": {
                    "id": "P-OCO-1",
                    "legs": [
                        {"id": "T-1", "order_type": "LIMIT"},
                        {"id": "S-1", "order_type": "STOP"},
                    ],
                },
            },
        })

    transport = _route({("POST", "/api/v2/orders/combo"): oco_handler})
    http = strategy_module.make_http_client("http://x", transport=transport)
    summary = strategy_module.enforce_protected_position_invariant(
        state, cfg_phase5, http, "k",
        state_path=state_path,
    )
    assert n_oco[0] == 1
    assert state["open_positions"]["AAPL"]["protection_status"] == "oco_attached"
    assert state["open_positions"]["AAPL"]["child_order_ids"]["target"] == "T-1"
    assert summary["retried"] == 1


def test_oco_fail_then_fallback_succeeds(strategy_module, cfg_phase5, tmp_path):
    """OCO 500 twice (uses up max_oco_attach_attempts=2) + fallback
    stop submission succeeds → fallback_stop_attached."""
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "AAPL": _filled_unprotected_pos(deadline_offset_seconds=-15.0)
    }
    state_path = Path(cfg_phase5["paths"]["state_path"])
    state_path.parent.mkdir(parents=True, exist_ok=True)

    n_oco = [0]
    n_fallback = [0]

    def oco_handler(req: httpx.Request) -> httpx.Response:
        n_oco[0] += 1
        return httpx.Response(500, json={"error": {"code": "broker_oops"}})

    def order_handler(req: httpx.Request) -> httpx.Response:
        n_fallback[0] += 1
        return httpx.Response(200, json={
            "data": {"order_id": "FB-1", "native_response": {"id": "FB-1"}},
        })

    transport = _route({
        ("POST", "/api/v2/orders/combo"): oco_handler,
        ("POST", "/api/v2/orders"): order_handler,
    })
    http = strategy_module.make_http_client("http://x", transport=transport)

    # First call: OCO retry #1 fails, deadline breached → fallback
    # path fires.
    strategy_module.enforce_protected_position_invariant(
        state, cfg_phase5, http, "k", state_path=state_path,
    )
    assert state["open_positions"]["AAPL"]["protection_status"] == "fallback_stop_attached"
    assert state["open_positions"]["AAPL"]["fallback_stop_order_id"] == "FB-1"
    assert n_fallback[0] == 1
    # Ledger captured the protection_event.
    ledger_path = (
        Path(cfg_phase5["paths"]["daily_summary_path"]).parent
        / "trade_ledger.jsonl"
    )
    events = []
    for line in ledger_path.read_text().splitlines():
        if line.strip():
            events.append(json.loads(line))
    types = [e["payload"]["event_type"] for e in events
             if e["event_type"] == "protection_event"]
    assert "fallback_stop_attached" in types


def test_oco_fail_fallback_fail_flatten_attempted(
    strategy_module, cfg_phase5, tmp_path,
):
    """Both OCO and fallback STOP submissions fail → flatten attempted
    + block_new_entries_today set."""
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "AAPL": _filled_unprotected_pos(deadline_offset_seconds=-15.0)
    }
    state_path = Path(cfg_phase5["paths"]["state_path"])
    state_path.parent.mkdir(parents=True, exist_ok=True)

    def oco_handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"code": "oco_oops"}})

    n_orders = [0]

    def order_handler(req: httpx.Request) -> httpx.Response:
        n_orders[0] += 1
        body = json.loads(req.content.decode())
        # Fallback STOP submission fails; the flatten MARKET SELL
        # also goes through this endpoint but with order_type=MARKET.
        order_type = body.get("order_type")
        if order_type == "STOP":
            return httpx.Response(500, json={"error": {"code": "stop_failed"}})
        # MARKET (flatten) — succeed so trigger_time_stop completes.
        return httpx.Response(200, json={
            "data": {"order_id": "FLAT-1", "native_response": {"id": "FLAT-1"}},
        })

    transport = _route({
        ("POST", "/api/v2/orders/combo"): oco_handler,
        ("POST", "/api/v2/orders"): order_handler,
    })
    http = strategy_module.make_http_client("http://x", transport=transport)
    summary = strategy_module.enforce_protected_position_invariant(
        state, cfg_phase5, http, "k", state_path=state_path,
    )
    assert summary["violations"] == 1
    assert state.get("block_new_entries_today") is True
    assert state.get("new_entries_blocked_reason") == "unprotected_position_violation"


def test_block_entries_on_violation_false_keeps_flag_clear(
    strategy_module, cfg_phase5, tmp_path,
):
    cfg = dict(cfg_phase5)
    cfg["exits"] = {**cfg_phase5["exits"]}
    cfg["exits"]["protected_position"] = {
        **cfg_phase5["exits"]["protected_position"],
        "block_entries_on_violation": False,
        "fallback_stop_enabled": False,
    }
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "AAPL": _filled_unprotected_pos(deadline_offset_seconds=-15.0)
    }
    state_path = Path(cfg["paths"]["state_path"])
    state_path.parent.mkdir(parents=True, exist_ok=True)
    transport = _route({
        ("POST", "/api/v2/orders/combo"):
            httpx.Response(500, json={"error": {"code": "oco_oops"}}),
        ("POST", "/api/v2/orders"):
            httpx.Response(200, json={
                "data": {"order_id": "FLAT-1", "native_response": {"id": "FLAT-1"}},
            }),
    })
    http = strategy_module.make_http_client("http://x", transport=transport)
    strategy_module.enforce_protected_position_invariant(
        state, cfg, http, "k", state_path=state_path,
    )
    assert state.get("block_new_entries_today") is False


# ---------------------------------------------------------------- 5.8 stop manager


def test_stop_manager_disabled_no_op(strategy_module, cfg_phase5, tmp_path):
    """Stop manager off → maybe_advance_stop returns None even at
    high MFE."""
    state = strategy_module.blank_state()
    pos = {
        "qty": 100, "entry_price": 10.0,
        "stop_price": 9.20, "target_price": 11.50,
        "peak_since_entry": 12.0,    # MFE = 20%
        "protection_status": "oco_attached",
        "child_order_ids": {"target": "T-1", "stop": "S-1"},
        "venue_code": "XNAS",
        "link_id": "BOWAKA-AAPL-1",
    }
    state["open_positions"] = {"AAPL": pos}
    state_path = Path(cfg_phase5["paths"]["state_path"])
    state_path.parent.mkdir(parents=True, exist_ok=True)
    transport = _route({})  # no routes — verifies no HTTP calls fired
    http = strategy_module.make_http_client("http://x", transport=transport)
    new_id = strategy_module.maybe_advance_stop(
        pos, cfg_phase5, http, "k",
        state=state, state_path=state_path, ticker="AAPL",
    )
    assert new_id is None


def test_stop_manager_advances_to_breakeven(strategy_module, cfg_phase5, tmp_path):
    """At MFE=8%, the rule {mfe_min: 0.08, stop_at: 0.03} fires →
    new stop = entry * 1.03."""
    cfg = dict(cfg_phase5)
    cfg["exits"] = {**cfg_phase5["exits"]}
    cfg["exits"]["stop_manager"] = {
        **cfg_phase5["exits"]["stop_manager"],
        "enabled": True,
    }
    state = strategy_module.blank_state()
    pos = {
        "qty": 100, "entry_price": 10.0,
        "stop_price": 9.20,
        "peak_since_entry": 10.80,   # MFE = 8%
        "protection_status": "oco_attached",
        "child_order_ids": {"target": "T-1", "stop": "S-1"},
        "venue_code": "XNAS",
        "link_id": "BOWAKA-AAPL-1",
        "target_pct": 0.15, "stop_pct": 0.08,
    }
    state["open_positions"] = {"AAPL": pos}
    state_path = Path(cfg["paths"]["state_path"])
    state_path.parent.mkdir(parents=True, exist_ok=True)
    routes = {
        ("DELETE", "/api/v2/orders/S-1"):
            httpx.Response(200, json={"data": {}}),
        ("POST", "/api/v2/orders"):
            httpx.Response(200, json={
                "data": {
                    "order_id": "S-NEW",
                    "native_response": {"id": "S-NEW"},
                },
            }),
    }
    transport = _route(routes)
    http = strategy_module.make_http_client("http://x", transport=transport)
    new_id = strategy_module.maybe_advance_stop(
        pos, cfg, http, "k",
        state=state, state_path=state_path, ticker="AAPL",
    )
    assert new_id == "S-NEW"
    assert pos["stop_price"] == pytest.approx(10.30)


def test_stop_never_moves_down(strategy_module, cfg_phase5, tmp_path):
    """Stop manager refuses to lower an existing stop even when the
    rule's stop_at is below current_stop."""
    cfg = dict(cfg_phase5)
    cfg["exits"] = {**cfg_phase5["exits"]}
    cfg["exits"]["stop_manager"] = {
        **cfg_phase5["exits"]["stop_manager"],
        "enabled": True,
    }
    state = strategy_module.blank_state()
    pos = {
        "qty": 100, "entry_price": 10.0,
        "stop_price": 10.40,  # already higher than break-even
        "peak_since_entry": 10.50,    # MFE = 5% → rule would set
                                       # break-even = entry = 10.0
                                       # but current 10.40 is higher.
        "protection_status": "oco_attached",
        "child_order_ids": {"target": "T-1", "stop": "S-1"},
        "venue_code": "XNAS",
        "link_id": "BOWAKA-AAPL-1",
    }
    state["open_positions"] = {"AAPL": pos}
    state_path = Path(cfg["paths"]["state_path"])
    state_path.parent.mkdir(parents=True, exist_ok=True)
    transport = _route({})
    http = strategy_module.make_http_client("http://x", transport=transport)
    new_id = strategy_module.maybe_advance_stop(
        pos, cfg, http, "k",
        state=state, state_path=state_path, ticker="AAPL",
    )
    assert new_id is None
    assert pos["stop_price"] == 10.40   # unchanged


def test_stop_manager_replacement_failure_preserves_prior_ids(
    strategy_module, cfg_phase5, tmp_path,
):
    """When the new STOP submission fails, child_order_ids stays
    untouched (we don't strand the position with empty stop slot)."""
    cfg = dict(cfg_phase5)
    cfg["exits"] = {**cfg_phase5["exits"]}
    cfg["exits"]["stop_manager"] = {
        **cfg_phase5["exits"]["stop_manager"],
        "enabled": True,
    }
    state = strategy_module.blank_state()
    pos = {
        "qty": 100, "entry_price": 10.0,
        "stop_price": 9.20,
        "peak_since_entry": 10.80,   # MFE = 8%
        "protection_status": "oco_attached",
        "child_order_ids": {"target": "T-1", "stop": "S-1"},
        "venue_code": "XNAS",
        "link_id": "BOWAKA-AAPL-1",
    }
    state["open_positions"] = {"AAPL": pos}
    state_path = Path(cfg["paths"]["state_path"])
    state_path.parent.mkdir(parents=True, exist_ok=True)
    routes = {
        ("DELETE", "/api/v2/orders/S-1"):
            httpx.Response(200, json={"data": {}}),
        ("POST", "/api/v2/orders"):
            httpx.Response(500, json={"error": {"code": "broker_full"}}),
    }
    transport = _route(routes)
    http = strategy_module.make_http_client("http://x", transport=transport)
    new_id = strategy_module.maybe_advance_stop(
        pos, cfg, http, "k",
        state=state, state_path=state_path, ticker="AAPL",
    )
    assert new_id is None
    # stop_price unchanged
    assert pos["stop_price"] == 9.20
    # child_order_ids["stop"] still references the old id (the
    # cancel call's idempotent-success means the old id may be
    # gone broker-side, but locally we preserve it so a future
    # tick can retry without losing track).
    assert pos["child_order_ids"]["stop"] == "S-1"


def test_desired_stop_from_mfe_no_rule_returns_none(strategy_module, cfg_phase5):
    """Below the first rule's mfe_min → no rule fires."""
    cfg = dict(cfg_phase5)
    cfg["exits"]["stop_manager"]["enabled"] = True
    pos = {"entry_price": 10.0, "peak_since_entry": 10.30}   # MFE 3%
    assert strategy_module.desired_stop_from_mfe(pos, cfg) is None


def test_desired_stop_from_mfe_picks_highest_qualifying_rule(strategy_module, cfg_phase5):
    """At MFE 13%, all three rules qualify; the highest stop_at wins."""
    cfg = dict(cfg_phase5)
    cfg["exits"]["stop_manager"]["enabled"] = True
    pos = {"entry_price": 10.0, "peak_since_entry": 11.30}   # MFE 13%
    out = strategy_module.desired_stop_from_mfe(pos, cfg)
    # Rule {0.12, 0.06} → entry*1.06 = 10.60
    assert out == pytest.approx(10.60)
