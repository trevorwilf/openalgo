"""Phase 4 — signal-fade redesign (15:45 hold-thesis exit, 16:05
telemetry, atomic marketable-limit SELL).

Covers:
* _validate_exit_combination rejects market+OPG (the 2026-05-15 bug).
* compute_fade_score is the weighted-average of failed gates.
* fade_score_to_band maps to {hold|soft|hard|critical}.
* run_signal_fade_pass(mode="telemetry") never submits.
* run_signal_fade_pass(mode="exit") with band=soft does NOT exit.
* run_signal_fade_pass(mode="exit") with band=hard submits a
  marketable-limit SELL BEFORE cancelling OCO children.
* On HTTP 422 rejection of the replacement, OCO children stay live.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pandas as pd
import pytest

import bowaka_strategy as bw


# ---- _validate_exit_combination --------------------------------------


def test_validate_exit_combination_rejects_market_opg() -> None:
    with pytest.raises(ValueError, match="invalid order_type/time_in_force"):
        bw._validate_exit_combination("market", "OPG")


def test_validate_exit_combination_accepts_market_day() -> None:
    bw._validate_exit_combination("market", "DAY")  # no exception


def test_validate_exit_combination_accepts_limit_day() -> None:
    bw._validate_exit_combination("limit", "DAY")  # no exception


def test_submit_market_sell_rejects_opg_before_io() -> None:
    """The submit helper must raise BEFORE any HTTP I/O."""

    def handler(req: httpx.Request) -> httpx.Response:
        # If we get here, the validator failed to short-circuit.
        return httpx.Response(200, json={"data": {}})

    http = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://x",
    )
    with pytest.raises(ValueError, match="invalid order_type/time_in_force"):
        bw.submit_market_sell(
            "X", qty=10, http=http, api_key="k",
            venue_code="XNAS", time_in_force="OPG",
        )


# ---- compute_fade_score ----------------------------------------------


def _cfg_for_scoring() -> dict:
    return {
        "signal_gates": {
            "rvol_min": 1.5,
            "atr_pct_min": 0.06,
            "range_expansion_min": 1.25,
            "close_location_min": 0.60,
            "ema_distance_min": 0.0,
            "ema_slope_min": 0.0,
        },
        "exits": {"signal_fade": {
            "score_thresholds": {
                "soft": 0.34, "hard": 0.50, "critical": 0.67,
            },
        }},
    }


def test_fade_score_zero_when_all_gates_pass() -> None:
    cfg = _cfg_for_scoring()
    feats = {
        "rvol": 2.0, "atr_pct": 0.08, "range_expansion": 1.5,
        "close_location": 0.7, "ema_distance": 0.02, "ema_slope": 0.01,
    }
    score, gates = bw.compute_fade_score(feats, cfg)
    assert score == 0.0
    assert all(v is False for v in gates.values())


def test_fade_score_one_when_all_gates_fail() -> None:
    cfg = _cfg_for_scoring()
    feats = {
        "rvol": 1.0, "atr_pct": 0.04, "range_expansion": 1.0,
        "close_location": 0.3, "ema_distance": -0.02, "ema_slope": -0.01,
    }
    score, gates = bw.compute_fade_score(feats, cfg)
    assert score == pytest.approx(1.0)
    assert all(v is True for v in gates.values())


def test_fade_score_partial_gates_fail() -> None:
    cfg = _cfg_for_scoring()
    # 3 of 6 gates fail -> score = 0.5
    feats = {
        "rvol": 1.0,                # FAIL
        "atr_pct": 0.04,            # FAIL
        "range_expansion": 1.0,     # FAIL
        "close_location": 0.7,      # pass
        "ema_distance": 0.02,       # pass
        "ema_slope": 0.01,          # pass
    }
    score, _ = bw.compute_fade_score(feats, cfg)
    assert score == pytest.approx(0.5)


def test_fade_score_to_band() -> None:
    cfg = _cfg_for_scoring()
    assert bw.fade_score_to_band(0.0, cfg) == "hold"
    assert bw.fade_score_to_band(0.34, cfg) == "soft"
    assert bw.fade_score_to_band(0.50, cfg) == "hard"
    assert bw.fade_score_to_band(0.67, cfg) == "critical"
    assert bw.fade_score_to_band(0.90, cfg) == "critical"
    assert bw.fade_score_to_band(0.33, cfg) == "hold"


# ---- run_signal_fade_pass two-phase ---------------------------------


def _make_bars_df(close: float, n: int = 25) -> pd.DataFrame:
    """Synthetic daily bars for a position."""
    rows = []
    for i in range(n):
        rows.append({
            "open": close, "high": close * 1.01,
            "low": close * 0.99, "close": close,
            "volume": 1_000_000, "ts": f"2026-05-{1+i:02d}T20:00:00Z",
        })
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["ts"])
    return df.drop(columns=["ts"]).sort_values("timestamp").reset_index(drop=True)


def _cfg_with_signal_fade(cfg_with_paths: dict, *, enabled: bool,
                          exit_on: list[str] | None = None) -> dict:
    import copy
    cfg = copy.deepcopy(cfg_with_paths)
    cfg.setdefault("signal_gates", {}).update({
        "rvol_min": 1.5, "atr_pct_min": 0.06,
        "range_expansion_min": 1.25, "close_location_min": 0.60,
        "ema_distance_min": 0.0, "ema_slope_min": 0.0,
    })
    cfg.setdefault("indicators", {}).update({
        "lookback_days": 20, "atr_days": 14, "ema_days": 10,
        "ema_slope_lookback": 3,
    })
    cfg.setdefault("exits", {})["signal_fade"] = {
        "enabled": enabled,
        "eval_time": "15:45",
        "telemetry_time": "16:05",
        "score_thresholds": {
            "soft": 0.34, "hard": 0.50, "critical": 0.67,
        },
        "exit_on": exit_on or ["hard", "critical"],
        "order_style": "marketable_limit",
        "time_in_force": "DAY",
        "marketable_limit_offset_pct": 0.005,
        "score_weights": None,
    }
    return cfg


def _seed_position(cfg: dict, ticker: str = "AAPL", qty: int = 10,
                    entry_price: float = 100.0) -> tuple[bw.State, Path]:
    state = bw.blank_state()
    state["open_positions"][ticker] = {
        "status": "filled",
        "qty": qty,
        "entry_price": entry_price,
        "venue_code": "XNAS",
        "child_order_ids": {"target": "T-1", "stop": "S-1"},
        "protection_status": "oco_attached",
        "link_id": f"BOWAKA-{ticker}-1",
    }
    state_path = Path(cfg["paths"]["state_path"])
    state_path.parent.mkdir(parents=True, exist_ok=True)
    bw.save_state(state, state_path)
    return state, state_path


def _all_gates_fail_bars() -> pd.DataFrame:
    """Build a synthetic bar series whose features fail every gate."""
    # Flat series at 100 -> rvol=1, atr_pct=0, range_expansion=0,
    # close_location ill-defined, ema_distance=0, ema_slope=0.
    rows = []
    for i in range(25):
        rows.append({
            "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0,
            "volume": 1_000_000, "ts": f"2026-05-{1+i:02d}T20:00:00Z",
        })
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["ts"])
    return df.drop(columns=["ts"]).sort_values("timestamp").reset_index(drop=True)


def _all_gates_pass_bars() -> pd.DataFrame:
    """Build a synthetic bar series with strong momentum across
    every gate. Volume rises sharply on the last bar to push rvol >
    1.5, and the close gaps up to push every gate above its
    threshold."""
    rows = []
    for i in range(24):
        rows.append({
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
            "volume": 1_000_000, "ts": f"2026-05-{1+i:02d}T20:00:00Z",
        })
    # Last bar: big breakout with massive rvol.
    rows.append({
        "open": 105.0, "high": 110.0, "low": 105.0, "close": 109.0,
        "volume": 3_000_000, "ts": "2026-05-25T20:00:00Z",
    })
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["ts"])
    return df.drop(columns=["ts"]).sort_values("timestamp").reset_index(drop=True)


def test_telemetry_mode_never_submits(cfg_with_paths, monkeypatch) -> None:
    cfg = _cfg_with_signal_fade(cfg_with_paths, enabled=True)
    state, state_path = _seed_position(cfg)

    submitted: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST" and req.url.path == "/api/v2/orders":
            submitted.append(req.content.decode("utf-8"))
        if req.method == "POST" and req.url.path == "/api/v2/quotes":
            return httpx.Response(
                200,
                json={"data": [{
                    "bid": 99.0, "ask": 99.5,
                    "venue_code": "XNAS", "canonical_symbol": "AAPL",
                }]},
            )
        return httpx.Response(200, json={"data": {}})

    http = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://x",
    )
    bars = _all_gates_fail_bars()
    monkeypatch.setattr(
        bw, "fetch_daily_bars_for_signal_fade",
        lambda *a, **k: bars,
    )
    from datetime import date as _date, datetime as _dt, timezone as _tz
    res = bw.run_signal_fade_pass(
        cfg, state, http, "k",
        today_et=_date(2026, 5, 15), state_path=state_path,
        now_utc=_dt(2026, 5, 15, 20, 5, tzinfo=_tz.utc),
        mode="telemetry",
    )
    assert res == []
    assert submitted == []
    # Ledger has score + telemetry events for AAPL.
    ledger = bw._ledger_path(cfg)
    events = [
        json.loads(l) for l in ledger.read_text().splitlines() if l.strip()
    ]
    scores = [e for e in events if e["event_type"] == "signal_fade_score"]
    telems = [e for e in events if e["event_type"] == "signal_fade_telemetry"]
    assert len(scores) == 1 and scores[0]["payload"]["mode"] == "telemetry"
    assert len(telems) == 1


def test_exit_mode_soft_band_does_not_submit(
    cfg_with_paths, monkeypatch,
) -> None:
    cfg = _cfg_with_signal_fade(cfg_with_paths, enabled=True)
    state, state_path = _seed_position(cfg)

    submitted: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST" and req.url.path == "/api/v2/orders":
            submitted.append(req.content.decode("utf-8"))
        return httpx.Response(200, json={"data": {}})

    http = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://x",
    )

    # Force the score function to return band=soft.
    monkeypatch.setattr(
        bw, "compute_fade_score",
        lambda f, c: (0.4, {"a": True, "b": True}),
    )
    monkeypatch.setattr(
        bw, "fetch_daily_bars_for_signal_fade",
        lambda *a, **k: _all_gates_fail_bars(),
    )
    from datetime import date as _date, datetime as _dt, timezone as _tz
    res = bw.run_signal_fade_pass(
        cfg, state, http, "k",
        today_et=_date(2026, 5, 15), state_path=state_path,
        now_utc=_dt(2026, 5, 15, 19, 45, tzinfo=_tz.utc),
        mode="exit",
    )
    assert res == []
    assert submitted == []


def test_exit_mode_hard_band_submits_marketable_limit_before_cancel(
    cfg_with_paths, monkeypatch,
) -> None:
    cfg = _cfg_with_signal_fade(cfg_with_paths, enabled=True)
    state, state_path = _seed_position(cfg)

    seq: list[tuple[str, str]] = []  # (method, path)

    def handler(req: httpx.Request) -> httpx.Response:
        seq.append((req.method, req.url.path))
        if req.method == "POST" and req.url.path == "/api/v2/quotes":
            return httpx.Response(
                200, json={"data": [{"bid": 99.0, "ask": 99.5}]},
            )
        if req.method == "POST" and req.url.path == "/api/v2/orders":
            return httpx.Response(
                200, json={"data": {"native_response": {"id": "EXIT-1"}}},
            )
        if req.method == "DELETE":
            return httpx.Response(200, json={"data": {}})
        return httpx.Response(404, json={"error": "no-route"})

    http = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://x",
    )

    monkeypatch.setattr(
        bw, "compute_fade_score",
        lambda f, c: (0.6, {"a": True}),
    )
    monkeypatch.setattr(
        bw, "fetch_daily_bars_for_signal_fade",
        lambda *a, **k: _all_gates_fail_bars(),
    )
    from datetime import date as _date, datetime as _dt, timezone as _tz
    res = bw.run_signal_fade_pass(
        cfg, state, http, "k",
        today_et=_date(2026, 5, 15), state_path=state_path,
        now_utc=_dt(2026, 5, 15, 19, 45, tzinfo=_tz.utc),
        mode="exit",
    )
    assert res == ["AAPL"]
    # POST /api/v2/orders (the replacement exit) must come BEFORE
    # any DELETE on a child order — atomic replacement.
    post_orders_idx = next(
        i for i, (m, p) in enumerate(seq)
        if m == "POST" and p == "/api/v2/orders"
    )
    delete_idx = next(
        (i for i, (m, _p) in enumerate(seq) if m == "DELETE"),
        None,
    )
    if delete_idx is not None:
        assert post_orders_idx < delete_idx

    # Ledger events:
    # replacement_exit_submitted -> replacement_exit_accepted ->
    # child_cancel_requested(s).
    ledger = bw._ledger_path(cfg)
    events = [
        json.loads(l) for l in ledger.read_text().splitlines() if l.strip()
    ]
    types_in_order = [
        e["event_type"] for e in events
        if e["event_type"].startswith(("replacement_exit_", "child_cancel_"))
    ]
    submit_i = types_in_order.index("replacement_exit_submitted")
    accept_i = types_in_order.index("replacement_exit_accepted")
    assert submit_i < accept_i
    if "child_cancel_requested" in types_in_order:
        cancel_i = types_in_order.index("child_cancel_requested")
        assert accept_i < cancel_i


def test_exit_mode_hard_band_rejected_keeps_oco_intact(
    cfg_with_paths, monkeypatch,
) -> None:
    cfg = _cfg_with_signal_fade(cfg_with_paths, enabled=True)
    state, state_path = _seed_position(cfg)

    cancel_paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "DELETE":
            cancel_paths.append(req.url.path)
        if req.method == "POST" and req.url.path == "/api/v2/quotes":
            return httpx.Response(
                200, json={"data": [{"bid": 99.0, "ask": 99.5}]},
            )
        if req.method == "POST" and req.url.path == "/api/v2/orders":
            return httpx.Response(
                422, json={"error": "rejected"},
            )
        return httpx.Response(200, json={"data": {}})

    http = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://x",
    )

    monkeypatch.setattr(
        bw, "compute_fade_score",
        lambda f, c: (0.6, {"a": True}),
    )
    monkeypatch.setattr(
        bw, "fetch_daily_bars_for_signal_fade",
        lambda *a, **k: _all_gates_fail_bars(),
    )
    from datetime import date as _date, datetime as _dt, timezone as _tz
    res = bw.run_signal_fade_pass(
        cfg, state, http, "k",
        today_et=_date(2026, 5, 15), state_path=state_path,
        now_utc=_dt(2026, 5, 15, 19, 45, tzinfo=_tz.utc),
        mode="exit",
    )
    assert res == []  # exit did not land
    # OCO children intact — no cancel issued.
    assert cancel_paths == []
    pos = state["open_positions"]["AAPL"]
    assert pos["child_order_ids"]["target"] == "T-1"
    assert pos["child_order_ids"]["stop"] == "S-1"
    # Ledger has a replacement_exit_rejected event.
    ledger = bw._ledger_path(cfg)
    events = [
        json.loads(l) for l in ledger.read_text().splitlines() if l.strip()
    ]
    assert any(
        e["event_type"] == "replacement_exit_rejected" for e in events
    )
