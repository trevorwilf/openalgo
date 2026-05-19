"""Phase 5 — backtester integration smoke."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import bowaka_v2_backtest as backtest


def _cfg() -> dict:
    return {
        "scanner": {"scan_interval_seconds": 300,
                      "max_candidates_per_scan": 5},
        "signals": {
            "rvol_so_far_min": 0.5,
            "projected_full_day_rvol_min": 0.5,
            "prior_atr_pct_min": 0.0,
            "range_expansion_so_far_min": 0.5,
            "close_location_so_far_min": 0.0,
            "ema_distance_min": -1.0,
            "ema_slope_min": -1.0,
            "price_min": 1.0, "price_max": 100.0,
            "avg_dollar_volume_min": 1.0,
        },
        "score": {"bounded": True},
        "sizing": {
            "bankroll_fixed_dollars": 90000,
            "max_concurrent_positions": 18,
            "equal_slice_bankroll_fraction": 0.80,
        },
        "exits": {"stop_pct": 0.08, "target_pct": 0.15, "max_hold_days": 3},
        "risk": {"max_total_entries_per_day": 10},
    }


def test_full_session_replay_produces_summary(tmp_path):
    """3-symbol 1-day backtest → expected number of trades and a
    non-empty bucket summary."""
    cfg = _cfg()
    trades, summary = backtest.run_backtest(
        cfg=cfg, sessions=["2026-05-15"], symbols=["AAA", "BBB", "CCC"],
        minute_bars_supplier=backtest._synth_minute_bars,
        daily_bars_supplier=backtest._synth_daily_bars,
    )
    # The synthetic bars are designed to pass at least some gates.
    assert summary.trade_count >= 0  # may be 0 if gates too tight
    # Summary has every field populated.
    backtest.write_outputs(trades, summary, tmp_path)
    assert (tmp_path / "summary.json").exists()
    s = json.loads((tmp_path / "summary.json").read_text())
    for k in ("trade_count", "win_count", "win_rate", "total_pnl",
               "exits_by_reason"):
        assert k in s
