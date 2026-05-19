"""Phase 5 — bucket analysis tests."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import bowaka_v2_bucket_analysis as ba


def test_bucket_assignment_correct():
    df = pd.DataFrame([
        {"adv_at_entry": 200_000, "entry_price": 3.5,
         "spread_bps_at_entry": 5.0, "pnl_pct": 0.10},
        {"adv_at_entry": 750_000, "entry_price": 8.0,
         "spread_bps_at_entry": 60.0, "pnl_pct": -0.05},
        {"adv_at_entry": 25_000_000, "entry_price": 15.0,
         "spread_bps_at_entry": 200.0, "pnl_pct": 0.20},
    ])
    out = ba.assign_buckets(df)
    assert list(out["adv_bucket"]) == ["<250k", "500k_1M", "20M+"]
    assert list(out["price_bucket"]) == ["$2_$5", "$5_$10", "$10_$20"]
    assert list(out["spread_bucket"]) == ["<10bps", "50_100bps", "100bps+"]


def test_expectancy_per_bucket_matches_handcomputed():
    df = pd.DataFrame([
        {"adv_at_entry": 750_000, "entry_price": 8.0,
         "spread_bps_at_entry": 20.0, "pnl_pct": 0.10},
        {"adv_at_entry": 750_000, "entry_price": 8.0,
         "spread_bps_at_entry": 20.0, "pnl_pct": -0.06},
        {"adv_at_entry": 750_000, "entry_price": 8.0,
         "spread_bps_at_entry": 20.0, "pnl_pct": 0.05},
    ])
    df = ba.assign_buckets(df)
    stats = ba.bucket_stats(df, "adv_bucket")
    assert len(stats) == 1
    row = stats.iloc[0]
    assert row["bucket"] == "500k_1M"
    assert row["n_trades"] == 3
    # mean pnl_pct = (0.10 - 0.06 + 0.05) / 3 = 0.03
    assert row["mean_pnl_pct"] == pytest.approx(0.03)
    # 2/3 wins.
    assert row["win_rate"] == pytest.approx(2/3)


def test_analyze_writes_per_bucket_csv(tmp_path):
    df = pd.DataFrame([
        {"adv_at_entry": 200_000, "entry_price": 3.5,
         "spread_bps_at_entry": 5.0, "pnl_pct": 0.10},
        {"adv_at_entry": 25_000_000, "entry_price": 15.0,
         "spread_bps_at_entry": 200.0, "pnl_pct": 0.20},
    ])
    res = ba.analyze(df, tmp_path)
    for col in ("by_adv_bucket", "by_price_bucket", "by_spread_bucket"):
        assert (tmp_path / f"{col}.csv").exists()
    assert (tmp_path / "bucket_summary.json").exists()
    summary = json.loads((tmp_path / "bucket_summary.json").read_text())
    assert "adv_bucket" in summary
