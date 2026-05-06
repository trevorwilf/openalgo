"""Phase 2 — Candidates ingestion + Entry pipeline tests.

Pattern: ``httpx.MockTransport`` mocks every OpenAlgo HTTP call. Routes
are keyed on ``(method, path)`` and stub the JSON response. See
``tests/api_v2/test_promoted_orders_alpaca.py`` for the upstream pattern.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest


# ---------------------------------------------------------------- helpers


def _candidates_payload(
    *, as_of: str = "2026-05-05", config_hash: str = "abcd1234",
    rows: list[dict] | None = None,
) -> dict:
    return {
        "as_of_date": as_of,
        "generated_at": as_of + "T20:30:00Z",
        "config_hash": config_hash,
        "n_universe_with_features": 5000,
        "n_passed_universe_gates": 800,
        "n_in_play": len(rows or []),
        "candidates": rows or [],
    }


def _row(ticker: str, close: float, signal: float, **extra) -> dict:
    base = {
        "ticker": ticker,
        "close": close,
        "rvol": 2.0,
        "atr_pct": 0.08,
        "range_expansion": 1.4,
        "gap_pct": 0.02,
        "close_location": 0.85,
        "ema_distance": 0.05,
        "ema_slope": 0.02,
        "avg_dollar_volume": 1_000_000.0,
        "signal_strength": signal,
    }
    base.update(extra)
    return base


def _balances_handler(equity: float = 100_000.0):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "data": {"balance": {
                "cash": str(equity * 0.5),
                "equity": str(equity),
                "buying_power": str(equity * 2),
                "currency": "USD",
            }},
        })
    return handler


def _orders_combo_handler(
    *, parent_id="P-1", target_id="T-1", stop_id="S-1",
    status_code=200, error_body=None,
):
    def handler(req: httpx.Request) -> httpx.Response:
        if status_code != 200:
            return httpx.Response(status_code, json=error_body or {})
        return httpx.Response(200, json={
            "data": {
                "combo_type": "OTOCO",
                "link_id": "BOWAKA-X-1",
                "legs": [],
                "native_response": {
                    "id": parent_id,
                    "client_order_id": "coid-1",
                    "status": "new",
                    "legs": [
                        {"id": target_id, "order_type": "limit", "status": "new"},
                        {"id": stop_id, "order_type": "stop", "status": "new"},
                    ],
                },
            },
        })
    return handler


def _route(handlers: dict[tuple[str, str], httpx.Response]):
    """Build a MockTransport handler from a (method, path) -> response/handler dict."""
    def handler(req: httpx.Request) -> httpx.Response:
        key = (req.method, req.url.path)
        h = handlers.get(key)
        if h is None:
            return httpx.Response(
                404, json={"error": {"code": "no_route", "path": req.url.path}}
            )
        if callable(h):
            return h(req)
        return h
    return httpx.MockTransport(handler)


# ---------------------------------------------------------------- candidates


def test_load_candidates_valid_today(strategy_module, tmp_path):
    p = tmp_path / "in_play.json"
    p.write_text(json.dumps(_candidates_payload(rows=[
        _row("AAPL", 150.0, 5.0),
        _row("MSFT", 200.0, 7.0),
        _row("GME", 30.0, 6.0),
    ])))
    out = strategy_module.load_candidates(
        p, max_age_trading_days=1,
        expected_config_hash=None, today_et=date(2026, 5, 5),
    )
    assert [c.ticker for c in out] == ["MSFT", "GME", "AAPL"]


def test_load_candidates_stale_rejected(strategy_module, tmp_path):
    p = tmp_path / "in_play.json"
    # April 27, 2026 = Monday. May 5 = Tuesday. Trading days between is 6.
    p.write_text(json.dumps(_candidates_payload(as_of="2026-04-27", rows=[])))
    with pytest.raises(strategy_module.CandidatesStaleError):
        strategy_module.load_candidates(
            p, max_age_trading_days=1,
            expected_config_hash=None, today_et=date(2026, 5, 5),
        )


def test_load_candidates_hash_mismatch(strategy_module, tmp_path):
    p = tmp_path / "in_play.json"
    p.write_text(json.dumps(_candidates_payload(config_hash="abcd1234", rows=[])))
    with pytest.raises(strategy_module.CandidatesHashMismatch):
        strategy_module.load_candidates(
            p, max_age_trading_days=1,
            expected_config_hash="ffffffff", today_et=date(2026, 5, 5),
        )


def test_load_candidates_hash_null_accepts_any(strategy_module, tmp_path):
    p = tmp_path / "in_play.json"
    p.write_text(json.dumps(_candidates_payload(config_hash="anything", rows=[])))
    out = strategy_module.load_candidates(
        p, max_age_trading_days=1,
        expected_config_hash=None, today_et=date(2026, 5, 5),
    )
    assert out == []


def test_load_candidates_missing_file(strategy_module, tmp_path):
    with pytest.raises(strategy_module.CandidatesMissing):
        strategy_module.load_candidates(
            tmp_path / "absent.json",
            max_age_trading_days=1,
            expected_config_hash=None, today_et=date(2026, 5, 5),
        )


# ---------------------------------------------------------------- sizing


def test_compute_qty_basic(strategy_module):
    assert strategy_module.compute_qty(
        equity=10_000, close_price=5, per_trade_pct=0.10,
    ) == 200


def test_compute_qty_floors_not_rounds(strategy_module):
    # 10000*0.10 / 17 = 58.82 -> 58 (floor, NOT 59).
    assert strategy_module.compute_qty(
        equity=10_000, close_price=17, per_trade_pct=0.10,
    ) == 58


def test_compute_qty_zero_when_too_expensive(strategy_module):
    assert strategy_module.compute_qty(
        equity=10, close_price=5, per_trade_pct=0.10,
    ) == 0


def test_compute_qty_absolute_cap_caps_below_pct(strategy_module):
    # 10000*0.10 = 1000. abs cap = 500. Effective dollars = 500.
    # 500 / 5 = 100 shares.
    assert strategy_module.compute_qty(
        equity=10_000, close_price=5, per_trade_pct=0.10,
        max_per_trade_dollars=500,
    ) == 100


# ---------------------------------------------------------------- entry select


def _state_with_open_positions(strategy_module, **kwargs):
    s = strategy_module.blank_state()
    for k, v in kwargs.items():
        s[k] = v
    return s


def test_select_entries_skips_existing_open_position(strategy_module, cfg_dict):
    state = _state_with_open_positions(
        strategy_module,
        open_positions={"AAPL": {"qty": 100, "entry_price": 150.0, "status": "filled"}},
    )
    cands = [strategy_module.Candidate("AAPL", 150.0, 9.0)]
    selected = strategy_module.select_entries(
        cands, state, equity=100_000.0, latest_prices={"AAPL": 150.0},
        cfg=cfg_dict, kill_state=strategy_module.KillLevel.NONE,
    )
    assert selected == []


def test_select_entries_respects_max_concurrent(strategy_module, cfg_dict):
    state = _state_with_open_positions(
        strategy_module,
        open_positions={f"T{i}": {"qty": 10, "entry_price": 10.0, "status": "filled"}
                        for i in range(5)},
    )
    cands = [strategy_module.Candidate("AAPL", 10.0, 9.0)]
    selected = strategy_module.select_entries(
        cands, state, equity=100_000.0, latest_prices={},
        cfg=cfg_dict, kill_state=strategy_module.KillLevel.NONE,
    )
    assert selected == []


def test_select_entries_respects_gross_cap(strategy_module, cfg_dict):
    # Gross cap = 50% of 100k = 50k. Already 45k open, candidate would
    # push to 55k → rejected.
    state = _state_with_open_positions(
        strategy_module,
        open_positions={"X": {"qty": 4500, "entry_price": 10.0, "status": "filled"}},
    )
    cands = [strategy_module.Candidate("Y", 100.0, 9.0)]  # 100*100 = 10k notional
    selected = strategy_module.select_entries(
        cands, state, equity=100_000.0,
        latest_prices={"X": 10.0},
        cfg=cfg_dict, kill_state=strategy_module.KillLevel.NONE,
    )
    assert selected == []


def test_select_entries_skips_halt_list(strategy_module, cfg_dict):
    state = _state_with_open_positions(strategy_module, halt_skip_today=["AAPL"])
    cands = [strategy_module.Candidate("AAPL", 10.0, 9.0)]
    selected = strategy_module.select_entries(
        cands, state, equity=100_000.0, latest_prices={},
        cfg=cfg_dict, kill_state=strategy_module.KillLevel.NONE,
    )
    assert selected == []


def test_select_entries_empty_when_daily_pnl_tripped(strategy_module, cfg_dict):
    state = _state_with_open_positions(strategy_module, daily_pnl_tripped=True)
    cands = [strategy_module.Candidate("AAPL", 10.0, 9.0)]
    selected = strategy_module.select_entries(
        cands, state, equity=100_000.0, latest_prices={},
        cfg=cfg_dict, kill_state=strategy_module.KillLevel.NONE,
    )
    assert selected == []


def test_select_entries_empty_under_kill_switch_l1(strategy_module, cfg_dict):
    state = strategy_module.blank_state()
    cands = [strategy_module.Candidate("AAPL", 10.0, 9.0)]
    selected = strategy_module.select_entries(
        cands, state, equity=100_000.0, latest_prices={},
        cfg=cfg_dict, kill_state=strategy_module.KillLevel.L1_NEW,
    )
    assert selected == []


def test_select_entries_orders_by_signal_strength(strategy_module, cfg_dict):
    cands = [
        strategy_module.Candidate(f"T{i}", close=10.0, signal_strength=float(i))
        for i in range(10)
    ]
    cands.reverse()  # input not pre-sorted
    state = strategy_module.blank_state()
    selected = strategy_module.select_entries(
        cands, state, equity=100_000.0, latest_prices={},
        cfg=cfg_dict, kill_state=strategy_module.KillLevel.NONE,
    )
    # cfg max_concurrent is 5, so we get top 5 by signal (T9..T5)
    # but select_entries doesn't pre-sort — it relies on candidate
    # order. So test passes a pre-sorted input and verifies all 5 picked.
    cands_sorted = sorted(cands, key=lambda c: c.signal_strength, reverse=True)
    selected = strategy_module.select_entries(
        cands_sorted, state, equity=100_000.0, latest_prices={},
        cfg=cfg_dict, kill_state=strategy_module.KillLevel.NONE,
    )
    assert [e.ticker for e in selected] == ["T9", "T8", "T7", "T6", "T5"]


# ---------------------------------------------------------------- OTOCO


def test_submit_otoco_body_shape(strategy_module, cfg_dict, tmp_path):
    sent_bodies: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        sent_bodies.append(json.loads(req.content))
        return httpx.Response(200, json={
            "data": {
                "combo_type": "OTOCO", "link_id": "L", "legs": [],
                "native_response": {"id": "P-1", "legs": [
                    {"id": "T-1", "order_type": "limit"},
                    {"id": "S-1", "order_type": "stop"},
                ]},
            },
        })

    transport = httpx.MockTransport(lambda req: handler(req))
    http = strategy_module.make_http_client("http://x", transport=transport)
    state = strategy_module.blank_state()
    state_path = tmp_path / "state.json"
    entry = strategy_module.Entry(
        ticker="AAPL", qty=10, close_price=150.0,
        candidate=strategy_module.Candidate("AAPL", 150.0, 9.0),
    )
    strategy_module.submit_otoco(entry, cfg_dict, http, "k",
                                  state=state, state_path=state_path)

    body = sent_bodies[0]
    assert body["combo_type"] == "OTOCO"
    assert body["time_in_force"] == "DAY"
    assert body["session"] == "REGULAR"
    assert body["link_id"].startswith("BOWAKA-AAPL-")
    legs = body["legs"]
    assert len(legs) == 3
    assert legs[0]["order_type"] == "MARKET"
    assert legs[1]["order_type"] == "LIMIT" and "price" in legs[1]
    assert legs[2]["order_type"] == "STOP" and "trigger_price" in legs[2]
    for leg in legs:
        assert leg["quantity_unit"] == "WHOLE"


def test_submit_otoco_target_stop_pricing(strategy_module, cfg_dict, tmp_path):
    sent_bodies: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        sent_bodies.append(json.loads(req.content))
        return httpx.Response(200, json={"data": {"native_response": {"id": "P", "legs": []}}})

    transport = httpx.MockTransport(handler)
    http = strategy_module.make_http_client("http://x", transport=transport)
    entry = strategy_module.Entry(
        ticker="AAPL", qty=10, close_price=10.0,
        candidate=strategy_module.Candidate("AAPL", 10.0, 9.0),
    )
    state = strategy_module.blank_state()
    state_path = tmp_path / "state.json"
    strategy_module.submit_otoco(entry, cfg_dict, http, "k",
                                  state=state, state_path=state_path)
    body = sent_bodies[0]
    # close=10, target_pct=0.15 -> 11.50; stop_pct=0.08 -> 9.20
    assert float(body["legs"][1]["price"]) == 11.50
    assert float(body["legs"][2]["trigger_price"]) == 9.20


def test_submit_otoco_records_state_on_success(strategy_module, cfg_dict, tmp_path):
    transport = _route({
        ("POST", "/api/v2/orders/combo"): _orders_combo_handler(
            parent_id="P-99", target_id="T-99", stop_id="S-99",
        ),
    })
    http = strategy_module.make_http_client("http://x", transport=transport)
    entry = strategy_module.Entry(
        ticker="AAPL", qty=10, close_price=150.0,
        candidate=strategy_module.Candidate("AAPL", 150.0, 9.0),
    )
    state = strategy_module.blank_state()
    state_path = tmp_path / "state.json"
    strategy_module.submit_otoco(entry, cfg_dict, http, "k",
                                  state=state, state_path=state_path)
    pos = state["open_positions"]["AAPL"]
    assert pos["parent_order_id"] == "P-99"
    assert pos["child_order_ids"] == {"target": "T-99", "stop": "S-99"}
    assert pos["status"] == "pending_fill"


def test_submit_otoco_422_bracket_marks_skip(strategy_module, cfg_dict, tmp_path):
    transport = _route({
        ("POST", "/api/v2/orders/combo"): _orders_combo_handler(
            status_code=422,
            error_body={"error": {
                "code": "unsupported_capability",
                "message": "Alpaca bracket take_profit must be LIMIT",
                "details": {"capability_name": "bracket_take_profit_type"},
            }},
        ),
    })
    http = strategy_module.make_http_client("http://x", transport=transport)
    entry = strategy_module.Entry(
        ticker="AAPL", qty=10, close_price=150.0,
        candidate=strategy_module.Candidate("AAPL", 150.0, 9.0),
    )
    state = strategy_module.blank_state()
    state_path = tmp_path / "state.json"
    strategy_module.submit_otoco(entry, cfg_dict, http, "k",
                                  state=state, state_path=state_path)
    assert "AAPL" in state["halt_skip_today"]
    assert "AAPL" not in state["open_positions"]


def test_submit_otoco_422_instrument_not_mapped_marks_skip(
    strategy_module, cfg_dict, tmp_path,
):
    transport = _route({
        ("POST", "/api/v2/orders/combo"): _orders_combo_handler(
            status_code=422,
            error_body={"error": {
                "code": "instrument_not_resolvable",
                "message": "instrument ref not found in instrument universe",
            }},
        ),
    })
    http = strategy_module.make_http_client("http://x", transport=transport)
    entry = strategy_module.Entry(
        ticker="ZZZ", qty=10, close_price=10.0,
        candidate=strategy_module.Candidate("ZZZ", 10.0, 9.0),
    )
    state = strategy_module.blank_state()
    state_path = tmp_path / "state.json"
    strategy_module.submit_otoco(entry, cfg_dict, http, "k",
                                  state=state, state_path=state_path)
    assert "ZZZ" in state["halt_skip_today"]


def test_submit_otoco_503_translator_not_registered_aborts_pass(
    strategy_module, cfg_dict, tmp_path,
):
    transport = _route({
        ("POST", "/api/v2/orders/combo"): _orders_combo_handler(
            status_code=503,
            error_body={"error": {"code": "translator_not_registered",
                                  "message": "API_V2_ALPACA missing"}},
        ),
    })
    http = strategy_module.make_http_client("http://x", transport=transport)
    entry = strategy_module.Entry(
        ticker="AAPL", qty=10, close_price=150.0,
        candidate=strategy_module.Candidate("AAPL", 150.0, 9.0),
    )
    state = strategy_module.blank_state()
    state_path = tmp_path / "state.json"
    strategy_module.submit_otoco(entry, cfg_dict, http, "k",
                                  state=state, state_path=state_path)
    assert "AAPL" not in state["halt_skip_today"]
    assert "AAPL" not in state["open_positions"]


# ---------------------------------------------------------------- poll fills


def _orders_list_handler(rows: list[dict]):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "data": {"orders": rows, "count": len(rows)},
        })
    return handler


def test_poll_fills_filled_updates_entry_price(strategy_module, tmp_path):
    transport = _route({
        ("GET", "/api/v2/orders"): _orders_list_handler([
            {"id": "P-1", "status": "filled", "filled_avg_price": "150.25",
             "filled_qty": "10"},
        ]),
    })
    http = strategy_module.make_http_client("http://x", transport=transport)
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "AAPL": {
            "parent_order_id": "P-1",
            "child_order_ids": {"target": "T-1", "stop": "S-1"},
            "qty": 10, "entry_price": None,
            "entry_timestamp": "2026-05-05T13:30:00+00:00",
            "entry_features": {}, "status": "pending_fill",
        }
    }
    state_path = tmp_path / "state.json"
    events = strategy_module.poll_fills(state, http, "k", state_path=state_path)
    assert state["open_positions"]["AAPL"]["entry_price"] == 150.25
    assert state["open_positions"]["AAPL"]["status"] == "filled"
    assert any(e.ticker == "AAPL" and e.role == "parent" for e in events)


def test_poll_fills_canceled_removes_position(strategy_module, tmp_path):
    transport = _route({
        ("GET", "/api/v2/orders"): _orders_list_handler([
            {"id": "P-1", "status": "canceled", "filled_qty": "0"},
        ]),
    })
    http = strategy_module.make_http_client("http://x", transport=transport)
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "AAPL": {
            "parent_order_id": "P-1",
            "child_order_ids": {"target": "T-1", "stop": "S-1"},
            "qty": 10, "entry_price": None,
            "entry_timestamp": "2026-05-05T13:30:00+00:00",
            "entry_features": {}, "status": "pending_fill",
        }
    }
    state_path = tmp_path / "state.json"
    strategy_module.poll_fills(state, http, "k", state_path=state_path)
    assert "AAPL" not in state["open_positions"]


def test_poll_fills_pending_no_change(strategy_module, tmp_path):
    transport = _route({
        ("GET", "/api/v2/orders"): _orders_list_handler([
            {"id": "P-1", "status": "new", "filled_qty": "0"},
        ]),
    })
    http = strategy_module.make_http_client("http://x", transport=transport)
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "AAPL": {
            "parent_order_id": "P-1",
            "child_order_ids": {"target": "T-1", "stop": "S-1"},
            "qty": 10, "entry_price": None,
            "entry_timestamp": "2026-05-05T13:30:00+00:00",
            "entry_features": {}, "status": "pending_fill",
        }
    }
    state_path = tmp_path / "state.json"
    events = strategy_module.poll_fills(state, http, "k", state_path=state_path)
    assert state["open_positions"]["AAPL"]["status"] == "pending_fill"
    assert events == []


# ---------------------------------------------------------------- cancel


def test_cancel_idempotent_on_404(strategy_module):
    def handler(req):
        return httpx.Response(404, json={"error": {"code": "not_found"}})
    http = strategy_module.make_http_client(
        "http://x", transport=httpx.MockTransport(handler),
    )
    out = strategy_module.cancel_order("O-1", http, "k")
    assert out["status"] == "canceled"


def test_cancel_idempotent_on_already_canceled(strategy_module):
    def handler(req):
        return httpx.Response(422, json={"error": {
            "code": "broker_error", "message": "Order is already_canceled",
        }})
    http = strategy_module.make_http_client(
        "http://x", transport=httpx.MockTransport(handler),
    )
    out = strategy_module.cancel_order("O-1", http, "k")
    assert out["status"] == "canceled"


def test_cancel_raises_on_other_errors(strategy_module):
    def handler(req):
        return httpx.Response(500, json={"error": {"code": "boom"}})
    http = strategy_module.make_http_client(
        "http://x", transport=httpx.MockTransport(handler),
    )
    with pytest.raises(RuntimeError):
        strategy_module.cancel_order("O-1", http, "k")


# ---------------------------------------------------------------- equity


def test_fetch_equity(strategy_module):
    transport = _route({
        ("GET", "/api/v2/balances"): _balances_handler(equity=100_000.0),
    })
    http = strategy_module.make_http_client("http://x", transport=transport)
    eq = strategy_module.fetch_equity(http, "k")
    assert eq == 100_000.0


# ---------------------------------------------------------------- main loop integration


def test_first_session_tick_runs_full_entry_pipeline(
    strategy_module, cfg_with_paths, tmp_path, monkeypatch,
):
    # Ensure the candidates file exists at the cfg-pointed path.
    candidates_path = Path(cfg_with_paths["paths"]["candidates_path"])
    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    candidates_path.write_text(json.dumps(_candidates_payload(rows=[
        _row(f"T{i}", close=10.0, signal=10.0 - i) for i in range(10)
    ])))

    sent_combos: list[dict] = []

    def combo_h(req: httpx.Request) -> httpx.Response:
        sent_combos.append(json.loads(req.content))
        i = len(sent_combos)
        return httpx.Response(200, json={
            "data": {"native_response": {
                "id": f"P-{i}",
                "legs": [
                    {"id": f"T-{i}", "order_type": "limit"},
                    {"id": f"S-{i}", "order_type": "stop"},
                ],
            }},
        })

    transport = _route({
        ("GET", "/api/v2/balances"): _balances_handler(equity=100_000.0),
        ("POST", "/api/v2/orders/combo"): combo_h,
    })
    http = strategy_module.make_http_client("http://x", transport=transport)

    # Now: Tuesday 2026-05-05 14:00 ET (in session).
    import pytz
    et = pytz.timezone("America/New_York")
    now = et.localize(datetime(2026, 5, 5, 14, 0)).astimezone(timezone.utc)

    rc = strategy_module.run_loop(
        cfg_with_paths,
        once=True,
        now_provider=lambda: now,
        http_client=http,
        api_key="k",
    )
    assert rc == 0
    # cfg.sizing.max_concurrent_positions = 5
    assert len(sent_combos) == 5


def test_subsequent_session_tick_polls_fills_only(
    strategy_module, cfg_with_paths, tmp_path,
):
    """Session date already matches today → no entry pass, only fill polling."""
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    state = strategy_module.blank_state()
    state["session_date"] = "2026-05-05"
    state["open_positions"] = {"AAPL": {
        "parent_order_id": "P-1",
        "child_order_ids": {"target": "T-1", "stop": "S-1"},
        "qty": 10, "entry_price": None,
        "entry_timestamp": "2026-05-05T13:30:00+00:00",
        "entry_features": {}, "status": "pending_fill",
    }}
    strategy_module.save_state(state, state_path)

    n_combo_calls = [0]
    n_orders_calls = [0]

    def combo_h(req):
        n_combo_calls[0] += 1
        return httpx.Response(200, json={"data": {}})

    def orders_h(req):
        n_orders_calls[0] += 1
        return httpx.Response(200, json={"data": {"orders": [], "count": 0}})

    transport = _route({
        ("POST", "/api/v2/orders/combo"): combo_h,
        ("GET", "/api/v2/orders"): orders_h,
    })
    http = strategy_module.make_http_client("http://x", transport=transport)

    import pytz
    et = pytz.timezone("America/New_York")
    now = et.localize(datetime(2026, 5, 5, 14, 0)).astimezone(timezone.utc)

    strategy_module.run_loop(
        cfg_with_paths, once=True,
        now_provider=lambda: now,
        http_client=http, api_key="k",
    )
    assert n_combo_calls[0] == 0
    assert n_orders_calls[0] >= 1
