"""Phase 7 audit acceptance tests — liquidity monitor + analysis rewrite.

Covers:
  7.3 run_liquidity_monitor_pass with enabled=False → no-op.
  7.3 Warning / severe / stale classification on quote attributes.
  7.3 action_on_severe_if_profitable="tighten_stop" raises
       NotImplementedError (scaffolded placeholder).
  7.4 build_canonical_trade_table: synthetic ledger → DataFrame
       with the §8.12 columns populated.
  7.4 Each new report dimension produces non-empty output on a
       fixture ledger.
  7.5 --reconcile passes on consistent pair; fails on injected
       mismatch.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
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


def _seed_ledger(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for raw in events:
            ev = {
                "schema_version": 1,
                "event_id": uuid.uuid4().hex,
                "ts": raw.get("ts", "2026-05-11T13:30:00+00:00"),
                **raw,
            }
            f.write(json.dumps(ev) + "\n")


# ---------------------------------------------------------------- 7.3 liquidity monitor


@pytest.fixture
def cfg_liquidity(cfg_with_paths):
    cfg = dict(cfg_with_paths)
    cfg["liquidity_monitor"] = {
        "enabled": True,
        "tick_interval_seconds": 0,
        "stale_quote_seconds": 30,
        "severe_stale_quote_seconds": 60,
        "spread_warning_pct": 0.03,
        "spread_severe_pct": 0.05,
        "consecutive_warning_ticks": 3,
        "action_on_severe_if_profitable": "none",
    }
    return cfg


def _filled_pos(*, qty=100, entry_price=10.0):
    return {
        "parent_order_id": "P-1",
        "child_order_ids": {"target": "T-1", "stop": "S-1"},
        "qty": qty,
        "entry_price": entry_price,
        "entry_timestamp": "2026-05-11T13:30:00+00:00",
        "entry_features": {},
        "status": "filled",
        "venue_code": "XNAS",
        "link_id": "BOWAKA-AAPL-1",
        "protection_status": "oco_attached",
    }


def test_liquidity_monitor_disabled_no_op(strategy_module, cfg_with_paths):
    """enabled=false → returns empty, no HTTP calls."""
    state = strategy_module.blank_state()
    state["open_positions"] = {"AAPL": _filled_pos()}
    cfg = dict(cfg_with_paths)
    cfg["liquidity_monitor"] = {"enabled": False}
    state_path = Path(cfg["paths"]["state_path"])
    state_path.parent.mkdir(parents=True, exist_ok=True)
    transport = _route({})
    http = strategy_module.make_http_client("http://x", transport=transport)
    result = strategy_module.run_liquidity_monitor_pass(
        cfg, state, http, "k", state_path=state_path,
    )
    assert result == []


def test_liquidity_status_classification_ok(strategy_module, cfg_liquidity):
    now = datetime(2026, 5, 12, 14, 30, tzinfo=timezone.utc)
    quote = {
        "bid": 9.99, "ask": 10.01,    # spread 0.2% < warning
        "timestamp": (now - timedelta(seconds=5)).isoformat(),
    }
    status, metrics = strategy_module._classify_liquidity_status(
        quote, cfg_liquidity["liquidity_monitor"], now,
    )
    assert status == "ok"


def test_liquidity_status_classification_warning(strategy_module, cfg_liquidity):
    now = datetime(2026, 5, 12, 14, 30, tzinfo=timezone.utc)
    quote = {
        "bid": 9.8, "ask": 10.2,   # spread (0.4 / 10.0) = 4% > 3% warning
        "timestamp": (now - timedelta(seconds=5)).isoformat(),
    }
    status, _ = strategy_module._classify_liquidity_status(
        quote, cfg_liquidity["liquidity_monitor"], now,
    )
    assert status == "warning"


def test_liquidity_status_classification_severe(strategy_module, cfg_liquidity):
    now = datetime(2026, 5, 12, 14, 30, tzinfo=timezone.utc)
    quote = {
        "bid": 9.5, "ask": 10.5,   # spread (1.0/10.0) = 10% > 5% severe
        "timestamp": (now - timedelta(seconds=5)).isoformat(),
    }
    status, _ = strategy_module._classify_liquidity_status(
        quote, cfg_liquidity["liquidity_monitor"], now,
    )
    assert status == "severe"


def test_liquidity_status_classification_stale(strategy_module, cfg_liquidity):
    """quote age > severe_stale_quote_seconds → stale."""
    now = datetime(2026, 5, 12, 14, 30, tzinfo=timezone.utc)
    quote = {
        "bid": 9.99, "ask": 10.01,
        "timestamp": (now - timedelta(seconds=90)).isoformat(),
    }
    status, _ = strategy_module._classify_liquidity_status(
        quote, cfg_liquidity["liquidity_monitor"], now,
    )
    assert status == "stale"


def test_liquidity_monitor_increments_counters(
    strategy_module, cfg_liquidity, tmp_path,
):
    state = strategy_module.blank_state()
    state["open_positions"] = {"AAPL": _filled_pos()}
    state_path = Path(cfg_liquidity["paths"]["state_path"])
    state_path.parent.mkdir(parents=True, exist_ok=True)

    def quotes_handler(req: httpx.Request) -> httpx.Response:
        # Warning-level spread.
        return httpx.Response(200, json={
            "data": [{
                "instrument": {"canonical_symbol": "AAPL"},
                "quote": {
                    "bid": 9.8, "ask": 10.2,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            }],
        })

    transport = _route({("POST", "/api/v2/quotes"): quotes_handler})
    http = strategy_module.make_http_client("http://x", transport=transport)
    strategy_module.run_liquidity_monitor_pass(
        cfg_liquidity, state, http, "k", state_path=state_path,
    )
    pos = state["open_positions"]["AAPL"]
    assert pos["last_liquidity_status"] == "warning"
    assert pos["liquidity_warning_count"] == 1
    # Ledger event was emitted.
    # Phase 1.2: ledger lives under data/<env>/trade_ledger.jsonl.
    ledger_path = strategy_module._ledger_path(cfg_liquidity)
    events = []
    for line in ledger_path.read_text().splitlines():
        if line.strip():
            events.append(json.loads(line))
    types = {e["event_type"] for e in events}
    assert "liquidity_status" in types


def test_action_on_severe_tighten_stop_raises(
    strategy_module, cfg_liquidity, tmp_path,
):
    cfg = dict(cfg_liquidity)
    cfg["liquidity_monitor"] = {
        **cfg_liquidity["liquidity_monitor"],
        "action_on_severe_if_profitable": "tighten_stop",
        "consecutive_warning_ticks": 1,
    }
    state = strategy_module.blank_state()
    pos = _filled_pos()
    state["open_positions"] = {"AAPL": pos}
    state_path = Path(cfg["paths"]["state_path"])
    state_path.parent.mkdir(parents=True, exist_ok=True)

    def quotes_handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "data": [{
                "instrument": {"canonical_symbol": "AAPL"},
                "quote": {
                    "bid": 11.0, "ask": 11.9,  # spread 7.8% severe, profitable
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            }],
        })
    transport = _route({("POST", "/api/v2/quotes"): quotes_handler})
    http = strategy_module.make_http_client("http://x", transport=transport)
    with pytest.raises(NotImplementedError):
        strategy_module.run_liquidity_monitor_pass(
            cfg, state, http, "k", state_path=state_path,
        )


# ---------------------------------------------------------------- 7.4 build_canonical_trade_table


def test_build_canonical_trade_table_basic(tmp_path):
    import bowaka_analysis as ba
    ledger = tmp_path / "trade_ledger.jsonl"
    today = "2026-05-11"
    _seed_ledger(ledger, [
        # T1 - accepted entry_decision + parent fill + closure (target)
        {"event_type": "entry_decision", "session_date": today,
         "trade_id": "T1", "ticker": "AAPL",
         "payload": {
             "ticker": "AAPL", "decision": "accepted",
             "reason": "accepted",
             "entry_trigger": "session_open",
             "candidate_rank": 1,
             "candidate": {"close": 10.0, "features": {
                 "avg_dollar_volume": 5e6}},
             "sizing": {"avg_dollar_volume": 5e6},
             "venue_code": "XNAS", "exchange": "NASDAQ",
         }},
        {"event_type": "order_fill", "session_date": today,
         "trade_id": "T1", "ticker": "AAPL", "role": "parent",
         "payload": {"filled_avg_price": 10.05, "filled_qty": 100,
                     "entry_trigger": "session_open"}},
        {"event_type": "closure", "session_date": today,
         "trade_id": "T1", "ticker": "AAPL",
         "payload": {"realized_pnl": 100.0, "reason": "target_hit",
                     "entry_timestamp": today + "T13:30:00Z",
                     "exit_timestamp": today + "T14:00:00Z",
                     "exit_price": 11.0, "qty": 100,
                     "entry_trigger": "session_open",
                     "planned_risk_dollars": 200.0,
                     "R_multiple": 0.5, "mfe_pct": 0.10,
                     "mae_pct": -0.02,
                     "hold_trading_days": 0}},
        # T2 - rescreen-triggered loss
        {"event_type": "entry_decision", "session_date": today,
         "trade_id": "T2", "ticker": "MSFT",
         "payload": {
             "ticker": "MSFT", "decision": "accepted",
             "reason": "accepted",
             "entry_trigger": "post_closure_rescreen",
             "candidate_rank": 1,
             "candidate": {"close": 200.0, "features": {
                 "avg_dollar_volume": 1e8}},
             "sizing": {"avg_dollar_volume": 1e8},
             "venue_code": "XNAS",
         }},
        {"event_type": "order_fill", "session_date": today,
         "trade_id": "T2", "ticker": "MSFT", "role": "parent",
         "payload": {"filled_avg_price": 200.0, "filled_qty": 50,
                     "entry_trigger": "post_closure_rescreen"}},
        {"event_type": "closure", "session_date": today,
         "trade_id": "T2", "ticker": "MSFT",
         "payload": {"realized_pnl": -75.0, "reason": "stop_hit",
                     "entry_timestamp": today + "T15:00:00Z",
                     "exit_timestamp": today + "T15:30:00Z",
                     "exit_price": 198.5, "qty": 50,
                     "entry_trigger": "post_closure_rescreen",
                     "planned_risk_dollars": 200.0,
                     "R_multiple": -0.375, "mfe_pct": 0.005,
                     "mae_pct": -0.04,
                     "hold_trading_days": 0}},
    ])
    out = ba.build_canonical_trade_table(ledger)
    assert len(out) == 2
    by_trade = {r["trade_id"]: r for _, r in out.iterrows()}
    assert by_trade["T1"]["realized_pnl"] == 100.0
    assert by_trade["T1"]["entry_trigger"] == "session_open"
    assert by_trade["T2"]["entry_trigger"] == "post_closure_rescreen"


def test_canonical_trade_table_correction_overrides(tmp_path):
    """A correction event replaces the original closure fields."""
    import bowaka_analysis as ba
    ledger = tmp_path / "trade_ledger.jsonl"
    today = "2026-05-11"
    _seed_ledger(ledger, [
        {"event_type": "entry_decision", "session_date": today,
         "trade_id": "T1", "ticker": "AAPL",
         "payload": {"ticker": "AAPL", "decision": "accepted",
                     "reason": "accepted", "entry_trigger": "session_open",
                     "candidate": {"close": 10.0}, "sizing": {}}},
        {"event_type": "closure", "session_date": today,
         "trade_id": "T1", "ticker": "AAPL",
         "payload": {"realized_pnl": 100.0, "reason": "target_hit"}},
        {"event_type": "correction", "session_date": today,
         "trade_id": "T1", "ticker": "AAPL",
         "payload": {"realized_pnl": 95.0, "reason": "stop_hit"}},
    ])
    out = ba.build_canonical_trade_table(ledger)
    assert len(out) == 1
    assert out.iloc[0]["realized_pnl"] == 95.0
    assert out.iloc[0]["reason"] == "stop_hit"


# ---------------------------------------------------------------- 7.4 reports


def _build_table_with_diverse_trades(tmp_path):
    """Seeds a small mixed ledger with multiple ADV buckets,
    triggers, instrument classes, and reasons."""
    import bowaka_analysis as ba
    ledger = tmp_path / "trade_ledger.jsonl"
    today = "2026-05-11"
    events = []
    cases = [
        ("T1", "session_open", "operating_equity",
         5e6, 50.0, "target_hit"),
        ("T2", "session_open", "operating_equity",
         8e5, -30.0, "stop_hit"),
        ("T3", "post_closure_rescreen", "operating_equity",
         3e7, 120.0, "target_hit"),
        ("T4", "session_open", "etf",
         2e8, -10.0, "stop_hit"),
    ]
    for trade_id, trig, cls, adv, pnl, reason in cases:
        events.append({
            "event_type": "entry_decision", "session_date": today,
            "trade_id": trade_id, "ticker": trade_id,
            "payload": {
                "ticker": trade_id, "decision": "accepted",
                "reason": "accepted", "entry_trigger": trig,
                "candidate": {"close": 10.0,
                              "features": {"instrument_class": cls,
                                            "avg_dollar_volume": adv}},
                "sizing": {"avg_dollar_volume": adv},
                "quote": {"bid": 9.99, "ask": 10.01},
            },
        })
        events.append({
            "event_type": "order_fill", "session_date": today,
            "trade_id": trade_id, "ticker": trade_id, "role": "parent",
            "payload": {"filled_avg_price": 10.0, "filled_qty": 100,
                        "entry_trigger": trig},
        })
        events.append({
            "event_type": "closure", "session_date": today,
            "trade_id": trade_id, "ticker": trade_id,
            "payload": {"realized_pnl": pnl, "reason": reason,
                        "entry_trigger": trig,
                        "planned_risk_dollars": 100.0,
                        "R_multiple": pnl / 100.0,
                        "mfe_pct": 0.03, "mae_pct": -0.01,
                        "hold_trading_days": 0,
                        "exit_price": 10.0 + (pnl / 100.0)},
        })
    _seed_ledger(ledger, events)
    return ba.build_canonical_trade_table(ledger)


def test_report_by_entry_trigger(tmp_path):
    import bowaka_analysis as ba
    trades = _build_table_with_diverse_trades(tmp_path)
    out = ba.report_by_entry_trigger(trades)
    assert not out.empty
    rows = out.set_index("entry_trigger")
    assert rows.loc["session_open", "trades"] == 3
    assert rows.loc["post_closure_rescreen", "trades"] == 1


def test_report_by_instrument_class(tmp_path):
    import bowaka_analysis as ba
    trades = _build_table_with_diverse_trades(tmp_path)
    out = ba.report_by_instrument_class(trades)
    assert not out.empty


def test_report_by_adv_tier(tmp_path):
    import bowaka_analysis as ba
    trades = _build_table_with_diverse_trades(tmp_path)
    out = ba.report_by_adv_tier(trades)
    assert not out.empty
    # Each ADV bucket should show up.
    assert "adv_tier" in out.columns


def test_report_by_spread_bucket(tmp_path):
    import bowaka_analysis as ba
    trades = _build_table_with_diverse_trades(tmp_path)
    out = ba.report_by_spread_bucket(trades)
    assert not out.empty


def test_report_mfe_mae_distribution(tmp_path):
    import bowaka_analysis as ba
    trades = _build_table_with_diverse_trades(tmp_path)
    out = ba.report_mfe_mae_distribution(trades)
    assert not out.empty
    assert set(out["metric"]) == {"mfe_pct", "mae_pct"}


def test_report_ex_top_winners(tmp_path):
    import bowaka_analysis as ba
    trades = _build_table_with_diverse_trades(tmp_path)
    out = ba.report_ex_top_winners(trades)
    assert len(out) == 3


def test_report_rescreen_ablation(tmp_path):
    import bowaka_analysis as ba
    trades = _build_table_with_diverse_trades(tmp_path)
    out = ba.report_rescreen_ablation(trades)
    assert len(out) == 3


def test_report_stop_slippage(tmp_path):
    import bowaka_analysis as ba
    trades = _build_table_with_diverse_trades(tmp_path)
    out = ba.report_stop_slippage(trades)
    # Two stop_hit trades in the fixture.
    if not out.empty:
        assert out.iloc[0]["stop_hit_trades"] == 2


# ---------------------------------------------------------------- 7.5 reconcile guard


def test_reconcile_consistent_ledger_summary(tmp_path):
    """When the on-disk session_summary matches the ledger-derived
    expected, reconcile returns no differences."""
    import bowaka_analysis as ba
    import bowaka_strategy as bw

    ledger = tmp_path / "trade_ledger.jsonl"
    summary = tmp_path / "daily_summary.jsonl"
    today = "2026-05-11"
    _seed_ledger(ledger, [
        {"event_type": "order_fill", "session_date": today,
         "trade_id": "T1", "ticker": "AAPL", "role": "parent",
         "payload": {"entry_trigger": "session_open"}},
        {"event_type": "closure", "session_date": today,
         "trade_id": "T1", "ticker": "AAPL",
         "payload": {"realized_pnl": 100.0, "reason": "target_hit",
                     "entry_trigger": "session_open"}},
    ])
    expected = bw.recompute_daily_summary_from_ledger(ledger, today)
    summary.write_text(json.dumps({
        "record_type": "session_summary", "session_date": today,
        **expected,
    }) + "\n")
    result = ba.reconcile_ledger_vs_summary(ledger, summary)
    assert result["differences"] == []
    assert result["matched"] == 1


def test_reconcile_mismatch_reports_difference(tmp_path):
    import bowaka_analysis as ba
    ledger = tmp_path / "trade_ledger.jsonl"
    summary = tmp_path / "daily_summary.jsonl"
    today = "2026-05-11"
    _seed_ledger(ledger, [
        {"event_type": "closure", "session_date": today,
         "trade_id": "T1", "ticker": "AAPL",
         "payload": {"realized_pnl": 100.0, "reason": "target_hit"}},
    ])
    # On-disk summary claims +200 instead of +100 — operator mistake.
    summary.write_text(json.dumps({
        "record_type": "session_summary", "session_date": today,
        "count_opened": 0, "count_closed": 1,
        "total_realized_pnl": 200.0,
    }) + "\n")
    result = ba.reconcile_ledger_vs_summary(ledger, summary)
    assert len(result["differences"]) >= 1
    diffs = result["differences"]
    pnls = [d for d in diffs if d["field"] == "total_realized_pnl"]
    assert pnls and pnls[0]["on_disk"] == 200.0
    assert pnls[0]["expected"] == 100.0
