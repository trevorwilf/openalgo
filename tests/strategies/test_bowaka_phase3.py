"""Phase 3 — Exits: time-stop, signal-fade, position closures.

Includes the parity test that pins the deliberate feature-math
duplication between bowaka_prefilter.py's compute_features (multi-
ticker) and bowaka_strategy.py's compute_features_single (one ticker).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------- helpers


def _route(handlers: dict):
    def handler(req):
        key = (req.method, req.url.path)
        h = handlers.get(key)
        if h is None:
            return httpx.Response(404, json={"error": {"code": "no_route"}})
        return h(req) if callable(h) else h
    return httpx.MockTransport(handler)


def _orders_list(rows):
    def h(req):
        return httpx.Response(200, json={"data": {"orders": rows, "count": len(rows)}})
    return h


def _bars_handler(bars: list[dict]):
    def h(req):
        return httpx.Response(200, json={"data": {
            "instrument": {"venue_code": "XNAS", "canonical_symbol": "X"},
            "interval": "1d",
            "bars": bars,
        }})
    return h


def _new_order_resp(oid="EXIT-1"):
    def h(req):
        return httpx.Response(200, json={"data": {"order_id": oid, "id": oid, "status": "NEW"}})
    return h


def _delete_handler(status=200):
    def h(req):
        return httpx.Response(status, json={})
    return h


def _filled_pos(strategy_module, ticker="AAPL", qty=10, entry_iso="2026-05-04T13:30:00+00:00",
                target_id="T-1", stop_id="S-1"):
    return {
        "parent_order_id": "P-1",
        "child_order_ids": {"target": target_id, "stop": stop_id},
        "qty": qty,
        "entry_price": 100.0,
        "entry_timestamp": entry_iso,
        "entry_features": {"rvol": 2.0},
        "status": "filled",
        "venue_code": "XNAS",
        "target_price": 115.0,
        "stop_price": 92.0,
    }


# ---------------------------------------------------------------- time-stop


def test_trading_days_since_friday_to_monday(strategy_module):
    # Friday 2026-05-01 entry, Monday 2026-05-04 today: 1 trading day.
    days = strategy_module.trading_days_since(
        "2026-05-01T13:30:00+00:00", date(2026, 5, 4),
    )
    assert days == 1


def test_trading_days_since_three_trading_days(strategy_module):
    # Friday 2026-05-01 entry, Wednesday 2026-05-06 today: 3 trading days.
    days = strategy_module.trading_days_since(
        "2026-05-01T13:30:00+00:00", date(2026, 5, 6),
    )
    assert days == 3


def test_time_stop_skips_recent_entry(strategy_module, cfg_with_paths, tmp_path):
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "AAPL": _filled_pos(strategy_module, entry_iso="2026-05-04T13:30:00+00:00"),
    }
    state_path = Path(cfg_with_paths["paths"]["state_path"])

    transport = _route({})  # no http calls expected
    http = strategy_module.make_http_client("http://x", transport=transport)

    out = strategy_module.run_time_stop_pass(
        cfg_with_paths, state, http, "k",
        today_et=date(2026, 5, 5), state_path=state_path,
    )
    assert out == []
    assert state["open_positions"]["AAPL"]["status"] == "filled"


def test_time_stop_triggers_at_max_hold_trading_days(
    strategy_module, cfg_with_paths, tmp_path,
):
    state = strategy_module.blank_state()
    # Friday 2026-05-01 entry, today Wednesday 2026-05-06 → 3 trading days.
    state["open_positions"] = {
        "AAPL": _filled_pos(strategy_module, entry_iso="2026-05-01T13:30:00+00:00"),
    }
    state_path = Path(cfg_with_paths["paths"]["state_path"])

    cancels: list[str] = []
    sells: list[dict] = []

    def cancel_h(req):
        cancels.append(req.url.path)
        return httpx.Response(200, json={})

    def sell_h(req):
        sells.append(json.loads(req.content))
        return httpx.Response(200, json={"data": {"order_id": "EX-1", "id": "EX-1"}})

    def handler(req):
        if req.method == "DELETE" and req.url.path.startswith("/api/v2/orders/"):
            return cancel_h(req)
        if req.method == "POST" and req.url.path == "/api/v2/orders":
            return sell_h(req)
        return httpx.Response(404)

    http = strategy_module.make_http_client(
        "http://x", transport=httpx.MockTransport(handler),
    )

    out = strategy_module.run_time_stop_pass(
        cfg_with_paths, state, http, "k",
        today_et=date(2026, 5, 6), state_path=state_path,
    )
    assert out == ["AAPL"]
    assert state["open_positions"]["AAPL"]["status"] == "exiting"
    assert state["open_positions"]["AAPL"]["exit_reason"] == "time_stop"
    # Both children canceled, then a market sell submitted.
    assert any("/T-1" in p for p in cancels)
    assert any("/S-1" in p for p in cancels)
    assert sells and sells[0]["order_type"] == "MARKET"
    assert sells[0]["side"] == "SELL"
    assert sells[0]["time_in_force"] == "DAY"


def test_trigger_time_stop_keeps_filled_when_sell_returns_4xx(
    strategy_module, cfg_with_paths, tmp_path,
):
    """Item 7 regression: a 4xx from /api/v2/orders does NOT raise from
    submit_market_sell — it returns the parsed body with
    ``_http_status``. trigger_time_stop must inspect that status and
    leave pos['status']='filled' so the next pass can retry. The bug
    used to mark the position as 'exiting' regardless, locking out
    every subsequent retry."""
    state = strategy_module.blank_state()
    pos = _filled_pos(strategy_module, entry_iso="2026-05-01T13:30:00+00:00")
    state["open_positions"] = {"AAPL": pos}
    state_path = Path(cfg_with_paths["paths"]["state_path"])

    def handler(req):
        if req.method == "DELETE":
            return httpx.Response(200, json={})
        if req.method == "POST" and req.url.path == "/api/v2/orders":
            return httpx.Response(
                422,
                json={"error": {"code": "broker_error",
                                 "message": "alpaca trade halted"}},
            )
        return httpx.Response(404)

    http = strategy_module.make_http_client(
        "http://x", transport=httpx.MockTransport(handler),
    )
    strategy_module.trigger_time_stop(
        "AAPL", pos, cfg_with_paths, http, "k",
        state=state, state_path=state_path,
    )
    # State invariant: still 'filled' so the next pass retries the
    # exit. Without the Item 7 fix this would now read 'exiting' with
    # an empty exit_order_id.
    assert state["open_positions"]["AAPL"]["status"] == "filled"
    assert "exit_reason" not in state["open_positions"]["AAPL"]
    assert "exit_order_id" not in state["open_positions"]["AAPL"]


def test_trigger_time_stop_keeps_filled_when_sell_accepted_but_no_order_id(
    strategy_module, cfg_with_paths, tmp_path,
):
    """Edge case: 200 OK but the body has no order_id (broker / proxy
    bug). Treat the same as a rejection — don't mutate state."""
    state = strategy_module.blank_state()
    pos = _filled_pos(strategy_module)
    state["open_positions"] = {"AAPL": pos}
    state_path = Path(cfg_with_paths["paths"]["state_path"])

    def handler(req):
        if req.method == "DELETE":
            return httpx.Response(200, json={})
        if req.method == "POST" and req.url.path == "/api/v2/orders":
            return httpx.Response(200, json={"data": {}})
        return httpx.Response(404)

    http = strategy_module.make_http_client(
        "http://x", transport=httpx.MockTransport(handler),
    )
    strategy_module.trigger_time_stop(
        "AAPL", pos, cfg_with_paths, http, "k",
        state=state, state_path=state_path,
    )
    assert state["open_positions"]["AAPL"]["status"] == "filled"


def test_time_stop_skips_weekend_correctly(strategy_module, cfg_with_paths):
    """Friday entry, Monday at 09:30 → 1 trading day, NOT 3 calendar days; no exit."""
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "AAPL": _filled_pos(strategy_module, entry_iso="2026-05-01T13:30:00+00:00"),
    }
    state_path = Path(cfg_with_paths["paths"]["state_path"])

    transport = _route({})  # no calls expected
    http = strategy_module.make_http_client("http://x", transport=transport)

    out = strategy_module.run_time_stop_pass(
        cfg_with_paths, state, http, "k",
        today_et=date(2026, 5, 4), state_path=state_path,
    )
    assert out == []


def test_time_stop_cancel_idempotent_when_one_child_already_filled(
    strategy_module, cfg_with_paths,
):
    """If target already filled (cancel returns 404), market sell still goes."""
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "AAPL": _filled_pos(strategy_module, entry_iso="2026-05-01T13:30:00+00:00"),
    }
    state_path = Path(cfg_with_paths["paths"]["state_path"])

    sells: list[dict] = []

    def handler(req):
        if req.method == "DELETE" and req.url.path == "/api/v2/orders/T-1":
            return httpx.Response(404, json={})  # already filled
        if req.method == "DELETE" and req.url.path == "/api/v2/orders/S-1":
            return httpx.Response(200, json={})
        if req.method == "POST" and req.url.path == "/api/v2/orders":
            sells.append(json.loads(req.content))
            return httpx.Response(200, json={"data": {"order_id": "EX-1"}})
        return httpx.Response(404)

    http = strategy_module.make_http_client(
        "http://x", transport=httpx.MockTransport(handler),
    )
    strategy_module.run_time_stop_pass(
        cfg_with_paths, state, http, "k",
        today_et=date(2026, 5, 6), state_path=state_path,
    )
    assert sells, "market sell should still go through despite one cancel-404"


# ---------------------------------------------------------------- features parity


def _synthetic_bars_one_ticker(n=40, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    highs = closes + np.abs(rng.normal(0.4, 0.15, n))
    lows = closes - np.abs(rng.normal(0.4, 0.15, n))
    opens = closes + rng.normal(0, 0.2, n)
    volumes = (rng.uniform(800_000, 1_500_000, n)).astype(int)
    timestamps = pd.date_range("2026-03-01", periods=n, freq="B")
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": volumes,
    })


def test_signal_fade_features_match_prefilter(strategy_module, cfg_with_paths):
    """Feed both implementations the same synthetic bars and assert the
    feature dict matches within float tolerance. This pins the
    deliberate duplication; any drift breaks this test.

    Skipped when ``alpaca`` is not installed (CI without the prefilter's
    runtime deps); operationally the prefilter requires alpaca-py so
    this test exercises the parity in any environment that can run the
    prefilter.
    """
    pytest.importorskip("alpaca")
    import sys as _sys
    bars = _synthetic_bars_one_ticker(n=60, seed=42)

    # Strategy single-ticker version.
    feats_strategy = strategy_module.compute_features_single(bars, cfg_with_paths)

    # Prefilter multi-ticker version.
    prefilter_dir = (
        Path(__file__).resolve().parents[2] / "strategies" / "scripts"
    )
    if str(prefilter_dir) not in _sys.path:
        _sys.path.insert(0, str(prefilter_dir))
    import bowaka_prefilter as bp

    # Prefilter expects a multi-index DataFrame keyed by ('symbol', 'timestamp')
    # with lowercase OHLCV columns. Reshape our synthetic input to match.
    bars_for_prefilter = bars.copy()
    bars_for_prefilter["symbol"] = "AAPL"
    bars_for_prefilter = bars_for_prefilter.set_index(["symbol", "timestamp"])
    pre_cfg = {
        "indicators": cfg_with_paths["indicators"],
    }
    feats_pre_df = bp.compute_features(bars_for_prefilter, pre_cfg)
    feats_pre = feats_pre_df.iloc[0].to_dict()

    for k in ("close", "rvol", "atr_pct", "range_expansion",
              "close_location", "ema_distance", "ema_slope",
              "avg_dollar_volume", "gap_pct"):
        a = feats_strategy.get(k)
        b = feats_pre.get(k)
        if a is None or b is None or pd.isna(b):
            assert (a is None and (b is None or pd.isna(b))), \
                f"feature {k} mismatch in nullness: strategy={a} prefilter={b}"
        else:
            assert abs(a - b) < 1e-9, f"feature {k} mismatch: {a} vs {b}"


# ---------------------------------------------------------------- signal-fade


def _passing_bars():
    """Bars whose latest row passes every gate in cfg.signal_gates.

    Gates: rvol>=1.5, atr_pct>=0.06, range_expansion>=1.25,
    close_location>=0.60, ema_distance>=0, ema_slope>=0.

    Strategy: 30 prior bars with close ~10, daily range = 1.0 (so ATR ≈
    1.0 → atr_pct ≈ 0.10 — passes 0.06), volume = 500k. Final bar:
    close = 11.7, range = 2.0 (range_expansion ≈ 1.87), close at 85% of
    range, volume = 5M (rvol ≈ 10), price above EMA, EMA rising.
    """
    n = 30
    closes = np.linspace(9.5, 10.5, n)  # gentle rise → ema slope > 0
    highs = closes + 0.5
    lows = closes - 0.5
    opens = closes - 0.05
    volumes = np.full(n, 500_000)
    closes[-1] = 11.7
    highs[-1] = 12.0
    lows[-1] = 10.0
    opens[-1] = 10.5
    volumes[-1] = 5_000_000
    timestamps = pd.date_range("2026-04-01", periods=n, freq="B")
    return [
        {"ts": ts.isoformat(), "open": str(opens[i]), "high": str(highs[i]),
         "low": str(lows[i]), "close": str(closes[i]),
         "volume": str(int(volumes[i]))}
        for i, ts in enumerate(timestamps)
    ]


def _faded_bars():
    """Bars whose latest row fails multiple gates.

    Phase 4 (2026-05-16): signal_fade exits now require a score
    >= 0.5 (3 of 6 gates failed) by default. Single-gate failure no
    longer triggers an exit. This helper collapses the last bar
    enough to break rvol, range_expansion, atr_pct, and
    close_location simultaneously.
    """
    rows = _passing_bars()
    # Make the last bar a flat doji with no volume.
    rows[-1]["volume"] = "1"
    last_close = float(rows[-1]["close"])
    rows[-1]["high"] = str(last_close)
    rows[-1]["low"] = str(last_close)
    rows[-1]["open"] = str(last_close)
    return rows


def _enable_new_signal_fade(cfg: dict) -> None:
    """Phase 4 (2026-05-16): pin the new exits.signal_fade schema so
    the legacy phase3 tests run against the new code path."""
    cfg.setdefault("exits", {})["signal_fade"] = {
        "enabled": True,
        "eval_time": "15:45",
        "telemetry_time": "16:05",
        "score_thresholds": {
            "soft": 0.34, "hard": 0.50, "critical": 0.67,
        },
        "exit_on": ["hard", "critical"],
        "marketable_limit_offset_pct": 0.005,
    }


def test_signal_fade_no_trigger_when_all_gates_pass(
    strategy_module, cfg_with_paths, tmp_path,
):
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "AAPL": _filled_pos(strategy_module, entry_iso="2026-05-04T13:30:00+00:00"),
    }
    state_path = Path(cfg_with_paths["paths"]["state_path"])

    transport = _route({
        ("POST", "/api/v2/bars"): _bars_handler(_passing_bars()),
    })
    http = strategy_module.make_http_client("http://x", transport=transport)

    now = datetime(2026, 5, 5, 20, 5, tzinfo=timezone.utc)  # 16:05 ET
    out = strategy_module.run_signal_fade_pass(
        cfg_with_paths, state, http, "k",
        today_et=date(2026, 5, 5), state_path=state_path, now_utc=now,
    )
    assert out == []
    assert state["open_positions"]["AAPL"]["status"] == "filled"


def test_signal_fade_triggers_when_rvol_drops_below_gate(
    strategy_module, cfg_with_paths, tmp_path,
):
    """Phase 4 (2026-05-16): the trigger is now a HARD-band fade
    score (>= 3 of 6 gates failed), and the exit is a marketable-
    limit DAY SELL, not MARKET+OPG. The behavioral intent — a
    weakened signal at EOD closes the position — is preserved."""
    _enable_new_signal_fade(cfg_with_paths)
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "AAPL": _filled_pos(strategy_module, entry_iso="2026-05-04T13:30:00+00:00"),
    }
    state_path = Path(cfg_with_paths["paths"]["state_path"])

    sells: list[dict] = []

    def handler(req):
        if req.method == "POST" and req.url.path == "/api/v2/bars":
            return httpx.Response(200, json={"data": {"bars": _faded_bars()}})
        if req.method == "POST" and req.url.path == "/api/v2/quotes":
            return httpx.Response(
                200,
                json={"data": [{"bid": 11.5, "ask": 11.6,
                                "venue_code": "XNAS",
                                "canonical_symbol": "AAPL"}]},
            )
        if req.method == "DELETE" and req.url.path.startswith("/api/v2/orders/"):
            return httpx.Response(200, json={})
        if req.method == "POST" and req.url.path == "/api/v2/orders":
            sells.append(json.loads(req.content))
            return httpx.Response(
                200,
                json={"data": {"native_response": {"id": "EX-MKL-1"}}},
            )
        return httpx.Response(404)

    http = strategy_module.make_http_client(
        "http://x", transport=httpx.MockTransport(handler),
    )
    now = datetime(2026, 5, 5, 19, 45, tzinfo=timezone.utc)  # 15:45 ET
    out = strategy_module.run_signal_fade_pass(
        cfg_with_paths, state, http, "k",
        today_et=date(2026, 5, 5), state_path=state_path,
        now_utc=now, mode="exit",
    )
    assert out == ["AAPL"]
    assert state["open_positions"]["AAPL"]["exit_reason"] == "signal_fade"
    # New contract: marketable-limit DAY SELL.
    assert sells, "signal-fade must submit a sell"
    assert sells[0]["order_type"] == "LIMIT"
    assert sells[0]["side"] == "SELL"
    assert sells[0]["time_in_force"] == "DAY"


def test_signal_fade_runs_only_once_per_day(
    strategy_module, cfg_with_paths, tmp_path,
):
    """Phase 4 (2026-05-16): the dedupe marker is now per-mode
    (signal_fade_evaluated_for_date_exit /
     signal_fade_evaluated_for_date_telemetry). Set the matching
    marker so the exit pass short-circuits without fetching bars."""
    _enable_new_signal_fade(cfg_with_paths)
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "AAPL": _filled_pos(strategy_module, entry_iso="2026-05-04T13:30:00+00:00"),
    }
    state["signal_fade_evaluated_for_date_exit"] = "2026-05-05"
    state_path = Path(cfg_with_paths["paths"]["state_path"])

    n_bars_calls = [0]

    def handler(req):
        if req.method == "POST" and req.url.path == "/api/v2/bars":
            n_bars_calls[0] += 1
            return httpx.Response(200, json={"data": {"bars": _passing_bars()}})
        return httpx.Response(404)

    http = strategy_module.make_http_client(
        "http://x", transport=httpx.MockTransport(handler),
    )
    now = datetime(2026, 5, 5, 19, 45, tzinfo=timezone.utc)  # 15:45 ET
    out = strategy_module.run_signal_fade_pass(
        cfg_with_paths, state, http, "k",
        today_et=date(2026, 5, 5), state_path=state_path,
        now_utc=now, mode="exit",
    )
    assert out == []
    assert n_bars_calls[0] == 0  # short-circuited


def test_signal_fade_resets_on_new_session(strategy_module):
    state = strategy_module.blank_state()
    state["signal_fade_evaluated_for_date"] = "2026-05-04"
    strategy_module.reset_for_new_session(state, "2026-05-05", 100_000.0)
    assert "signal_fade_evaluated_for_date" not in state


def test_signal_fade_records_pending_exit(strategy_module, cfg_with_paths, tmp_path):
    """Phase 4 (2026-05-16): the redesigned exit path persists
    exit_order_id + status='exiting' on the position itself via
    replace_protection_with_exit, NOT in
    state['pending_signal_fade_exits'] (which only carried the
    legacy OPG-routed exits)."""
    _enable_new_signal_fade(cfg_with_paths)
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "AAPL": _filled_pos(strategy_module, entry_iso="2026-05-04T13:30:00+00:00"),
    }
    state_path = Path(cfg_with_paths["paths"]["state_path"])

    def handler(req):
        if req.method == "POST" and req.url.path == "/api/v2/bars":
            return httpx.Response(200, json={"data": {"bars": _faded_bars()}})
        if req.method == "POST" and req.url.path == "/api/v2/quotes":
            return httpx.Response(
                200,
                json={"data": [{"bid": 11.5, "ask": 11.6,
                                "venue_code": "XNAS",
                                "canonical_symbol": "AAPL"}]},
            )
        if req.method == "DELETE" and req.url.path.startswith("/api/v2/orders/"):
            return httpx.Response(200, json={})
        if req.method == "POST" and req.url.path == "/api/v2/orders":
            return httpx.Response(
                200,
                json={"data": {"native_response": {"id": "EX-MKL-7"}}},
            )
        return httpx.Response(404)

    http = strategy_module.make_http_client(
        "http://x", transport=httpx.MockTransport(handler),
    )
    now = datetime(2026, 5, 5, 19, 45, tzinfo=timezone.utc)
    strategy_module.run_signal_fade_pass(
        cfg_with_paths, state, http, "k",
        today_et=date(2026, 5, 5), state_path=state_path,
        now_utc=now, mode="exit",
    )
    pos = state["open_positions"]["AAPL"]
    assert pos["exit_order_id"] == "EX-MKL-7"
    assert pos["status"] == "exiting"


# ---------------------------------------------------------------- closures


def test_position_closed_on_target_fill(strategy_module, cfg_with_paths, tmp_path):
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "AAPL": _filled_pos(strategy_module),
    }
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    summary_path = Path(cfg_with_paths["paths"]["daily_summary_path"])

    events = [strategy_module.FillEvent(
        ticker="AAPL", order_id="T-1", role="target",
        status="FILLED", filled_qty=10, filled_avg_price=115.5, raw={},
    )]
    strategy_module.process_fill_events_for_closures(
        events, state, cfg_with_paths,
        state_path=state_path, summary_path=summary_path,
    )
    assert "AAPL" not in state["open_positions"]
    rec = json.loads(summary_path.read_text().strip())
    assert rec["reason"] == "target_hit"
    assert rec["realized_pnl"] == pytest.approx((115.5 - 100.0) * 10)


def test_position_closed_on_stop_fill(strategy_module, cfg_with_paths, tmp_path):
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "AAPL": _filled_pos(strategy_module),
    }
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    summary_path = Path(cfg_with_paths["paths"]["daily_summary_path"])

    events = [strategy_module.FillEvent(
        ticker="AAPL", order_id="S-1", role="stop",
        status="FILLED", filled_qty=10, filled_avg_price=92.0, raw={},
    )]
    strategy_module.process_fill_events_for_closures(
        events, state, cfg_with_paths,
        state_path=state_path, summary_path=summary_path,
    )
    rec = json.loads(summary_path.read_text().strip())
    assert rec["reason"] == "stop_hit"
    assert rec["realized_pnl"] == pytest.approx((92.0 - 100.0) * 10)


def test_position_closed_on_time_stop_exit_fill(strategy_module, cfg_with_paths, tmp_path):
    state = strategy_module.blank_state()
    pos = _filled_pos(strategy_module)
    pos["status"] = "exiting"
    pos["exit_reason"] = "time_stop"
    pos["exit_order_id"] = "EX-1"
    state["open_positions"] = {"AAPL": pos}
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    summary_path = Path(cfg_with_paths["paths"]["daily_summary_path"])

    events = [strategy_module.FillEvent(
        ticker="AAPL", order_id="EX-1", role="exit",
        status="FILLED", filled_qty=10, filled_avg_price=98.0, raw={},
    )]
    strategy_module.process_fill_events_for_closures(
        events, state, cfg_with_paths,
        state_path=state_path, summary_path=summary_path,
    )
    rec = json.loads(summary_path.read_text().strip())
    assert rec["reason"] == "time_stop"


def test_position_closed_on_signal_fade_exit_fill(
    strategy_module, cfg_with_paths, tmp_path,
):
    state = strategy_module.blank_state()
    pos = _filled_pos(strategy_module)
    pos["status"] = "exiting"
    pos["exit_reason"] = "signal_fade"
    pos["exit_order_id"] = "EX-MOO-1"
    state["open_positions"] = {"AAPL": pos}
    state["pending_signal_fade_exits"] = {
        "AAPL": {"submitted_at": "2026-05-05T20:05:00+00:00", "exit_order_id": "EX-MOO-1"},
    }
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    summary_path = Path(cfg_with_paths["paths"]["daily_summary_path"])

    events = [strategy_module.FillEvent(
        ticker="AAPL", order_id="EX-MOO-1", role="exit",
        status="FILLED", filled_qty=10, filled_avg_price=99.5, raw={},
    )]
    strategy_module.process_fill_events_for_closures(
        events, state, cfg_with_paths,
        state_path=state_path, summary_path=summary_path,
    )
    rec = json.loads(summary_path.read_text().strip())
    assert rec["reason"] == "signal_fade"
    assert "AAPL" not in state["pending_signal_fade_exits"]


def test_daily_summary_jsonl_append_format(strategy_module, cfg_with_paths, tmp_path):
    """Multiple closures in one day → one jsonl line per closure."""
    state = strategy_module.blank_state()
    state["open_positions"] = {
        "AAPL": _filled_pos(strategy_module, ticker="AAPL"),
        "MSFT": _filled_pos(strategy_module, ticker="MSFT", target_id="T-2", stop_id="S-2"),
    }
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    summary_path = Path(cfg_with_paths["paths"]["daily_summary_path"])

    events = [
        strategy_module.FillEvent("AAPL", "T-1", "target", "FILLED", 10, 115.0, {}),
        strategy_module.FillEvent("MSFT", "S-2", "stop", "FILLED", 10, 92.0, {}),
    ]
    strategy_module.process_fill_events_for_closures(
        events, state, cfg_with_paths,
        state_path=state_path, summary_path=summary_path,
    )
    lines = summary_path.read_text().strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        json.loads(line)  # readable JSON
