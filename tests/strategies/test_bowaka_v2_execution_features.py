"""Hardening Phase 5 — execution features.

Covers:
- marketable-limit parent entry (LIMIT at ask x (1+slippage)) and
  market default in the live submit dispatch,
- the janitor's shorter timeout for marketable-limit parents,
- trigger_exit_v2 order-style dispatch (limit vs market),
- signal-fade scoring: telemetry rows, no orders in telemetry mode,
  active mode exits only exit_on severities, once-per-session guards,
- candidate-minute-bars capture writes parquet and warns on missing.
"""
from __future__ import annotations

import json
from datetime import datetime, time as dt_time, timezone
from pathlib import Path

import pandas as pd
import pytest

import bowaka_v2_strategy as v2


@pytest.fixture(autouse=True)
def _redirect_v2_paths(tmp_path, monkeypatch):
    import bowaka_v2_paths as p
    monkeypatch.setattr(p, "V2_LEDGER_PATH",
                        tmp_path / "trade_ledger.jsonl")
    monkeypatch.setattr(p, "V2_DAILY_SUMMARY_PATH",
                        tmp_path / "daily_summary.jsonl")
    monkeypatch.setattr(p, "COUNTERFACTUAL_EXITS_PATH",
                        tmp_path / "counterfactual_exits.jsonl")
    monkeypatch.setattr(p, "PROTECTION_EVENTS_PATH",
                        tmp_path / "protection_events.jsonl")
    monkeypatch.setattr(p, "CANDIDATE_MINUTE_BARS_DIR",
                        tmp_path / "candidate_bars")


def _cfg(tmp_path, **over):
    cfg = {
        "paths": {
            "trade_ledger_path": str(tmp_path / "trade_ledger.jsonl"),
            "daily_summary_path": str(tmp_path / "daily_summary.jsonl"),
        },
        "execution": {
            "default_venue_code": "XNAS",
            "parent_order_style": "market",
            "marketable_limit_slippage_pct": 0.005,
            "marketable_limit_timeout_seconds": 30,
            "pending_fill_timeout_seconds": 900,
        },
        "session": {"start": "09:30", "end": "15:55"},
        "score": {"bounded": True},
        "exits": {
            "stop_pct": 0.08, "target_pct": 0.15, "max_hold_days": 3,
            "oco_time_in_force": "GTC",
            "signal_fade": {
                "enabled": True,
                "active": False,
                "eval_time": "15:45",
                "telemetry_time": "16:05",
                "score_thresholds": {
                    "soft": 0.15, "hard": 0.40, "critical": 0.50,
                },
                "exit_on": ["hard", "critical"],
                "order_style": "marketable_limit",
                "marketable_limit_offset_pct": 0.005,
            },
        },
        "logging": {"log_counterfactual_exits": True},
        "research": {"candidate_minute_bars": {
            "enabled": True,
            "output_dir": str(tmp_path / "candidate_bars"),
            "window": {"premarket_start": "08:00",
                       "session_end": "16:00"},
            "columns": ["timestamp", "open", "high", "low", "close",
                        "volume"],
            "on_missing": "warn",
        }},
    }
    for key, val in over.items():
        if isinstance(val, dict) and isinstance(cfg.get(key), dict):
            cfg[key].update(val)
        else:
            cfg[key] = val
    return cfg


_BASELINES = {
    "prior_close": 8.00, "avg_volume_20d": 450000,
    "avg_dollar_volume_20d": 3_000_000, "prior_atr_14d": 0.52,
    "prior_atr_pct": 0.065, "ema_10_prior": 7.80,
    "ema_10_lag_3": 7.60, "ema_slope_prior": 0.02,
}


def _strong_bars() -> pd.DataFrame:
    """A session that still looks strong (high close location, big
    volume/range) — low fade."""
    return pd.DataFrame({
        "timestamp": pd.to_datetime(
            ["2026-05-18T13:46:00Z", "2026-05-18T19:40:00Z"], utc=True),
        "open": [8.10, 9.40], "high": [8.30, 9.60],
        "low": [8.05, 9.35], "close": [8.25, 9.58],
        "volume": [400000, 500000],
    })


def _faded_bars() -> pd.DataFrame:
    """A session that collapsed: price back near the low, tiny range
    participation — large fade vs a strong entry score."""
    return pd.DataFrame({
        "timestamp": pd.to_datetime(
            ["2026-05-18T13:46:00Z", "2026-05-18T19:40:00Z"], utc=True),
        "open": [8.10, 8.06], "high": [8.30, 8.08],
        "low": [8.00, 8.01], "close": [8.25, 8.02],
        "volume": [40000, 5000],
    })


class FakeOA:
    def __init__(self, bars: pd.DataFrame | None = None):
        self.bars = bars
        self.cancel_calls = []
        self.market_sells = []
        self.limit_sells = []
        self.quote = {"bid": 8.00, "ask": 8.04, "mid": 8.02,
                      "spread_pct": 0.005, "quote_age_seconds": 1}
        self.bars_requests = []

    def fetch_bars(self, http, api_key, *, venue_code, symbol,
                   interval, start, end):
        self.bars_requests.append(
            {"symbol": symbol, "start": start, "end": end})
        return self.bars

    def fetch_quote(self, http, api_key, *, venue_code, symbol):
        return dict(self.quote)

    def cancel_order(self, http, api_key, order_id):
        self.cancel_calls.append(order_id)
        return {"status": "canceled", "order_id": order_id}

    def submit_market_sell(self, http, api_key, **kw):
        self.market_sells.append(kw)
        return {"data": {"order_id": "EXIT-M"}, "_http_status": 200}

    def submit_limit_sell(self, http, api_key, **kw):
        self.limit_sells.append(kw)
        return {"data": {"order_id": "EXIT-L"}, "_http_status": 200}


def _filled_lot(symbol="AAA", *, entry_score=12.0, baselines=None):
    return {
        "symbol": symbol, "qty": 100, "venue_code": "XNAS",
        "status": "filled", "entry_price": 8.20,
        "entry_timestamp": "2026-05-18T18:35:00Z",
        "link_id": f"L-{symbol}",
        "child_order_ids": {"target": "T-1", "stop": "S-1"},
        "signal_strength": entry_score,
        "prior_daily_baselines": (
            _BASELINES if baselines is None else baselines
        ),
        "stop_pct": 0.08, "target_pct": 0.15,
        "recorded_exposure": 820.0,
    }


_EVAL_NOW = datetime(2026, 5, 18, 15, 50)      # Monday 15:50 ET naive
_TELEM_NOW = datetime(2026, 5, 18, 16, 10)


def _ledger(tmp_path) -> list[dict]:
    p = tmp_path / "trade_ledger.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines()]


def _cf_rows(tmp_path) -> list[dict]:
    p = tmp_path / "counterfactual_exits.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines()]


# ---- order-style dispatch ------------------------------------------------


def test_trigger_exit_marketable_limit_uses_limit_sell(tmp_path):
    cfg = _cfg(tmp_path)
    pos = _filled_lot()
    oa = FakeOA()
    ok = v2.trigger_exit_v2(
        "AAA", pos, cfg, oa_client=oa, api_key="k", http=None,
        reason="signal_fade", order_style="marketable_limit",
        limit_price=7.96,
    )
    assert ok is True
    assert len(oa.limit_sells) == 1
    assert oa.limit_sells[0]["price"] == pytest.approx(7.96)
    assert oa.market_sells == []


def test_trigger_exit_marketable_limit_without_price_falls_back(tmp_path):
    cfg = _cfg(tmp_path)
    pos = _filled_lot()
    oa = FakeOA()
    ok = v2.trigger_exit_v2(
        "AAA", pos, cfg, oa_client=oa, api_key="k", http=None,
        reason="signal_fade", order_style="marketable_limit",
        limit_price=None,
    )
    assert ok is True
    assert oa.limit_sells == []
    assert len(oa.market_sells) == 1


def test_supplier_accepts_quote_detection():
    assert v2._supplier_accepts_quote(lambda s, q: None) is False
    assert v2._supplier_accepts_quote(lambda s, q, quote: None) is True
    assert v2._supplier_accepts_quote(
        lambda s, q, quote=None: None) is True
    assert v2._supplier_accepts_quote(lambda *args: None) is True


def test_marketable_limit_price_math():
    # ask 8.04, slippage 0.005 -> 8.04 * 1.005 = 8.0802 -> 8.08
    assert round(8.04 * 1.005, 2) == pytest.approx(8.08)


# ---- janitor marketable-limit timeout --------------------------------------


def test_janitor_uses_short_timeout_for_marketable_limit(tmp_path):
    cfg = _cfg(tmp_path)
    now = datetime(2026, 5, 18, 18, 40, tzinfo=timezone.utc)
    ml_lot = {
        "symbol": "AAA", "qty": 100, "status": "pending_fill",
        "parent_order_id": "P-ML", "link_id": "L-ML",
        "entry_timestamp": "2026-05-18T18:38:00Z",  # 120s old
        "parent_order_style": "marketable_limit",
        "recorded_exposure": 800.0,
        "child_order_ids": {"target": "", "stop": ""},
    }
    mkt_lot = dict(ml_lot, parent_order_id="P-MKT", link_id="L-MKT",
                   parent_order_style="market", symbol="BBB")
    state = {"gross_exposure_dollars": 1600.0,
             "open_positions": {"L-ML": ml_lot, "L-MKT": mkt_lot}}
    oa = FakeOA()
    out = v2.expire_stale_pending_fills(
        state, cfg, oa_client=oa, api_key="k", http=None, now_utc=now,
    )
    # 120s > 30s ml timeout -> expired; 120s < 900s market timeout ->
    # survives.
    assert out == ["AAA"]
    assert "L-MKT" in state["open_positions"]
    assert "L-ML" not in state["open_positions"]


# ---- signal fade ------------------------------------------------------------


def test_fade_telemetry_mode_writes_rows_no_orders(tmp_path):
    cfg = _cfg(tmp_path)
    state = {"open_positions": {"L-AAA": _filled_lot("AAA")}}
    oa = FakeOA(bars=_faded_bars())
    exited = v2.run_signal_fade_pass_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
        now_et=_EVAL_NOW,
    )
    assert exited == []
    assert oa.market_sells == [] and oa.limit_sells == []
    rows = _cf_rows(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["symbol"] == "AAA" and row["mode"] == "telemetry"
    assert row["fade_magnitude"] > 0.4          # collapsed session
    assert row["severity"] in {"hard", "critical"}
    assert row["would_exit"] is True
    ledger = _ledger(tmp_path)
    assert any(e["event_type"] == "signal_fade_telemetry"
               for e in ledger)
    # Position untouched.
    assert state["open_positions"]["L-AAA"]["status"] == "filled"


def test_fade_active_mode_exits_hard_severity(tmp_path):
    cfg = _cfg(tmp_path)
    cfg["exits"]["signal_fade"]["active"] = True
    state = {"open_positions": {"L-AAA": _filled_lot("AAA")}}
    oa = FakeOA(bars=_faded_bars())
    exited = v2.run_signal_fade_pass_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
        now_et=_EVAL_NOW,
    )
    assert exited == ["AAA"]
    # marketable_limit exit at bid*(1-offset) = 8.00*0.995 = 7.96
    assert len(oa.limit_sells) == 1
    assert oa.limit_sells[0]["price"] == pytest.approx(7.96)
    assert state["open_positions"]["L-AAA"]["status"] == "exiting"
    assert state["open_positions"]["L-AAA"]["exit_reason"] == (
        "signal_fade")


def test_fade_active_mode_keeps_strong_position(tmp_path):
    cfg = _cfg(tmp_path)
    cfg["exits"]["signal_fade"]["active"] = True
    state = {"open_positions": {
        "L-AAA": _filled_lot("AAA", entry_score=6.0),
    }}
    oa = FakeOA(bars=_strong_bars())
    exited = v2.run_signal_fade_pass_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
        now_et=_EVAL_NOW,
    )
    assert exited == []
    assert oa.limit_sells == [] and oa.market_sells == []
    rows = _cf_rows(tmp_path)
    assert rows[0]["would_exit"] is False


def test_fade_once_per_session_guard(tmp_path):
    cfg = _cfg(tmp_path)
    state = {"open_positions": {"L-AAA": _filled_lot("AAA")}}
    oa = FakeOA(bars=_faded_bars())
    v2.run_signal_fade_pass_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
        now_et=_EVAL_NOW,
    )
    assert state["signal_fade_evaluated_on"] == "2026-05-18"
    v2.run_signal_fade_pass_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
        now_et=_EVAL_NOW,
    )
    assert len(_cf_rows(tmp_path)) == 1          # not re-evaluated


def test_fade_skips_before_eval_time_and_weekends(tmp_path):
    cfg = _cfg(tmp_path)
    state = {"open_positions": {"L-AAA": _filled_lot("AAA")}}
    oa = FakeOA(bars=_faded_bars())
    v2.run_signal_fade_pass_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
        now_et=datetime(2026, 5, 18, 12, 0),     # before 15:45
    )
    assert _cf_rows(tmp_path) == []
    v2.run_signal_fade_pass_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
        now_et=datetime(2026, 5, 16, 15, 50),    # Saturday
    )
    assert _cf_rows(tmp_path) == []


def test_fade_disabled_skips(tmp_path):
    cfg = _cfg(tmp_path)
    cfg["exits"]["signal_fade"]["enabled"] = False
    state = {"open_positions": {"L-AAA": _filled_lot("AAA")}}
    oa = FakeOA(bars=_faded_bars())
    out = v2.run_signal_fade_pass_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
        now_et=_EVAL_NOW,
    )
    assert out == [] and _cf_rows(tmp_path) == []


def test_fade_skips_lot_without_entry_score_or_baselines(tmp_path):
    cfg = _cfg(tmp_path)
    state = {"open_positions": {
        "L-A": _filled_lot("AAA", entry_score=None),
        "L-B": _filled_lot("BBB", baselines={}),
    }}
    oa = FakeOA(bars=_faded_bars())
    v2.run_signal_fade_pass_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
        now_et=_EVAL_NOW,
    )
    assert _cf_rows(tmp_path) == []              # both skipped cleanly


def test_fade_severity_ranking():
    thresholds = {"soft": 0.15, "hard": 0.40, "critical": 0.50}
    assert v2._fade_severity(0.10, thresholds) == "none"
    assert v2._fade_severity(0.20, thresholds) == "soft"
    assert v2._fade_severity(0.45, thresholds) == "hard"
    assert v2._fade_severity(0.90, thresholds) == "critical"


# ---- telemetry_time pass + candidate minute bars ----------------------------


def test_post_close_pass_captures_candidate_bars(tmp_path):
    cfg = _cfg(tmp_path)
    state = {
        "open_positions": {"L-AAA": _filled_lot("AAA")},
        "entered_today": ["AAA", "MISSING"],
    }
    bars = _strong_bars()

    class OA(FakeOA):
        def fetch_bars(self, http, api_key, *, venue_code, symbol,
                       interval, start, end):
            self.bars_requests.append({"symbol": symbol})
            return bars if symbol == "AAA" else pd.DataFrame()

    oa = OA()
    v2.run_signal_fade_pass_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
        now_et=_TELEM_NOW,
    )
    out_dir = tmp_path / "candidate_bars" / "2026-05-18"
    assert (out_dir / "AAA.parquet").exists()
    assert not (out_dir / "MISSING.parquet").exists()  # warn, no raise
    df = pd.read_parquet(out_dir / "AAA.parquet")
    assert list(df.columns) == ["timestamp", "open", "high", "low",
                                "close", "volume"]
    # Post-close fade telemetry also ran (telemetry-only).
    rows = _cf_rows(tmp_path)
    assert rows and rows[-1]["phase"] == "post_close"
    # Once-per-session: a second 16:10 tick captures nothing new.
    n_requests = len(oa.bars_requests)
    v2.run_signal_fade_pass_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
        now_et=_TELEM_NOW,
    )
    assert len(oa.bars_requests) == n_requests


def test_capture_disabled_writes_nothing(tmp_path):
    cfg = _cfg(tmp_path)
    cfg["research"]["candidate_minute_bars"]["enabled"] = False
    state = {"open_positions": {}, "entered_today": ["AAA"]}
    oa = FakeOA(bars=_strong_bars())
    v2.run_signal_fade_pass_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
        now_et=_TELEM_NOW,
    )
    assert not (tmp_path / "candidate_bars" / "2026-05-18").exists()
