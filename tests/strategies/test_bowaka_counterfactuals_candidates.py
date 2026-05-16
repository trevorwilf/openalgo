"""Phase 7 — candidate decisions + counterfactual logging + minute-bar storage.

Covers:
* compute_counterfactuals returns len(ENTRY_SCENARIOS) records.
* A record where the bar path hits the target first reports
  first_touch='target' with pnl_pct = target_pct.
* Path metrics match hand-computed values for a known 3-bar series.
* fetch_and_store_candidate_minute_bars writes a parquet file with
  expected columns and row count.
* shadow_stop_manager appears on intraday_tick events when
  stop_manager.enabled=false.
* Catalyst overrides file load: present entries are accessible;
  absent entries do NOT cause a KeyError.
"""
from __future__ import annotations

import copy
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

import bowaka_strategy as bw
from strategies.scripts import bowaka_counterfactuals as bc  # type: ignore


# ---- compute_counterfactuals ----------------------------------------


def _mk_intraday_bars(prices: list[float], symbol: str = "AAPL",
                      start_et: datetime | None = None) -> pd.DataFrame:
    import pytz
    et = pytz.timezone("America/New_York")
    if start_et is None:
        start_et = et.localize(datetime(2026, 5, 15, 9, 30))
    rows = []
    for i, p in enumerate(prices):
        ts = start_et + timedelta(minutes=i)
        rows.append({
            "timestamp": ts.isoformat(),
            "open": p, "high": p * 1.005, "low": p * 0.995,
            "close": p, "volume": 1000.0,
            "vwap": p, "prior_close": prices[0] if prices else p,
            "symbol": symbol,
        })
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def test_compute_counterfactuals_returns_one_per_scenario() -> None:
    bars = _mk_intraday_bars([10.0] * 60)
    out = bc.compute_counterfactuals(
        {"ticker": "AAPL", "session_date": "2026-05-15"},
        bars, {},
    )
    assert len(out) == len(bc.ENTRY_SCENARIOS)


def test_path_metrics_match_hand_computation() -> None:
    # Entry @ 10. Peak @ 12 (bar 1). Trough @ 9 (bar 2).
    prices = [10.0, 12.0, 9.0]
    bars = _mk_intraday_bars(prices)
    out = bc.compute_counterfactuals(
        {"ticker": "X", "session_date": "2026-05-15"},
        bars, {},
    )
    open_scenario = [r for r in out
                     if r["entry_scenario"] == "session_open_actual"][0]
    pm = open_scenario["path_metrics"]
    # high of bar 0 = 10.05; bar 1 = 12.06; bar 2 = 9.045 -> peak ≈ 12.06.
    assert pm["mfe_pct"] >= 0.20  # entry=10, peak ≈12.06 -> +20.6%
    # bar 0 low ≈ 9.95; bar 1 ≈ 11.94; bar 2 ≈ 8.955 -> trough ≈ 8.955.
    assert pm["mae_pct"] <= -0.10


def test_replay_exit_surface_target_first_reports_pnl() -> None:
    # Prices climb high enough to hit stop_5_target_8 (target @ +8%)
    # before any drawdown.
    prices = [10.0, 10.5, 11.0]
    bars = _mk_intraday_bars(prices)
    out = bc.compute_counterfactuals(
        {"ticker": "Y", "session_date": "2026-05-15"},
        bars, {},
    )
    open_scenario = [r for r in out
                     if r["entry_scenario"] == "session_open_actual"][0]
    surfaces = open_scenario["surfaces"]
    s5_t8 = [s for s in surfaces if s["exit_surface"] == "stop_5_target_8"][0]
    assert s5_t8["first_touch"] == "target"
    assert s5_t8["pnl_pct"] == pytest.approx(0.08)


# ---- fetch_and_store_candidate_minute_bars --------------------------


def test_minute_bar_storage_creates_session_file(
    cfg_with_paths, tmp_path,
) -> None:
    cfg = copy.deepcopy(cfg_with_paths)
    cfg["research"] = {
        "candidate_minute_bars": {
            "enabled": True,
            "output_dir": str(tmp_path / "candidate_bars"),
            "layout": "by_session",
            "window": {"premarket_start": "08:00", "session_end": "16:00"},
            "columns": ["ts", "open", "high", "low", "close", "volume"],
            "on_missing": "warn",
        },
    }
    candidates = [{"ticker": "AAPL", "venue_code": "XNAS"}]

    def supplier(symbol, vc, http, api_key, start, end):
        return _mk_intraday_bars([10.0] * 5, symbol=symbol)

    out_path = bw.fetch_and_store_candidate_minute_bars(
        cfg, candidates, date(2026, 5, 15),
        bars_supplier=supplier,
    )
    assert out_path is not None
    assert out_path.exists()
    df = pd.read_parquet(out_path)
    assert len(df) == 5
    assert "symbol" in df.columns
    assert (df["symbol"] == "AAPL").all()


def test_minute_bar_storage_disabled_by_default(cfg_with_paths) -> None:
    # No research.candidate_minute_bars block.
    out_path = bw.fetch_and_store_candidate_minute_bars(
        cfg_with_paths, [{"ticker": "X"}], date(2026, 5, 15),
    )
    assert out_path is None


# ---- shadow_stop_manager on intraday_tick ---------------------------


def test_intraday_tick_emits_shadow_stop_manager(
    cfg_with_paths, tmp_path,
) -> None:
    cfg = copy.deepcopy(cfg_with_paths)
    cfg["exits"] = {
        **cfg.get("exits", {}),
        "stop_manager": {
            "enabled": False,
            "rules": [
                {"mfe_min": 0.05, "stop_at": 0.0},   # to breakeven
                {"mfe_min": 0.08, "stop_at": 0.03},  # lock 3
            ],
        },
    }
    pos = {
        "status": "filled",
        "link_id": "BOWAKA-X-1",
        "qty": 10,
        "entry_price": 100.0,
        "stop_price": 92.0,
        "target_price": 115.0,
        "peak_since_entry": 105.5,   # >5% MFE
        "trough_since_entry": 99.0,
    }
    quote = {
        "bid": 105.0, "ask": 105.1, "last": 105.05,
        "bid_size": 100, "ask_size": 100,
        "timestamp": "2026-05-15T15:00:00Z",
        "metadata": {
            "open": 100.0, "high": 105.5, "low": 99.0,
            "close": 105.0, "volume": 1_000_000, "prev_close": 99.0,
        },
    }
    bw.emit_intraday_tick(
        cfg, pos=pos, ticker="X", quote=quote,
        now_utc=datetime(2026, 5, 15, 19, 0, tzinfo=timezone.utc),
    )
    # The intraday_tick goes to the per-trade log under data/trades/.
    # Read it back and check the shadow_stop_manager payload.
    trade_log = bw._trade_log_path(cfg, "BOWAKA-X-1")
    assert trade_log is not None and trade_log.exists()
    lines = [
        json.loads(l) for l in trade_log.read_text().splitlines() if l.strip()
    ]
    ticks = [r for r in lines if r.get("record_type") == "intraday_tick"]
    assert ticks
    sh = ticks[0].get("shadow_stop_manager")
    assert sh is not None
    # MFE crossed +5% so the would-have-moved flag is True (rule
    # would move stop to breakeven = 100.0 > current 92.0).
    assert sh["would_have_moved_stop"] is True
    assert sh["rule_triggered"] is not None


# ---- catalyst overrides ---------------------------------------------


def test_catalyst_overrides_load_missing_file_returns_empty(
    cfg_with_paths,
) -> None:
    out = bw.load_catalyst_overrides(cfg_with_paths)
    assert out == {}


def test_catalyst_overrides_load_present_entries(
    cfg_with_paths, tmp_path,
) -> None:
    base = bw._ledger_base_dir(cfg_with_paths)
    env = bw._strategy_environment(cfg_with_paths)
    over_dir = base / env
    over_dir.mkdir(parents=True, exist_ok=True)
    path = over_dir / "catalyst_overrides.jsonl"
    rows = [
        {"session_date": "2026-05-15", "symbol": "PCT",
         "catalyst_bucket": "earnings_surprise",
         "top_news_headline": "PCT beats Q1"},
        {"session_date": "2026-05-15", "symbol": "ONDS",
         "catalyst_bucket": "fda_approval"},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    out = bw.load_catalyst_overrides(cfg_with_paths)
    assert ("2026-05-15", "PCT") in out
    assert ("2026-05-15", "ONDS") in out
    assert out[("2026-05-15", "PCT")]["catalyst_bucket"] == "earnings_surprise"
    # Absent key is just a dict miss, no KeyError raised here.
    assert out.get(("2026-05-15", "ASPN")) is None
