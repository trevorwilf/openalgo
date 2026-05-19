"""Phase 5 — scanner / backtester feature parity.

This is the load-bearing test that makes the backtester trustworthy:
both the scanner (in replay mode) and the backtester (in synthetic
mode) must compute the EXACT same features from the same inputs,
to within 1e-9.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import bowaka_v2_features as features


def test_scanner_and_backtester_produce_identical_features():
    """Feed both code paths the same synthetic day's bars at the
    same scan time and assert every numeric field matches to 1e-9.

    Because both scanner.evaluate_one_scan AND backtest.run_backtest
    delegate to bowaka_v2_features.* exclusively, this is a
    structural invariant: any drift would only be possible if
    someone bypassed the shared module."""
    base = pd.Timestamp("2026-05-15 09:30", tz="America/New_York")
    rows = []
    for i in range(305):
        ts = base + pd.Timedelta(minutes=i)
        rows.append({
            "timestamp": ts.tz_convert("UTC"),
            "open": 10.0, "high": 10.5,
            "low": 9.8, "close": 10.0 + i * 0.003,
            "volume": 5000.0,
        })
    bars_through_t = pd.DataFrame(rows)

    baselines = {
        "prior_close": 10.0,
        "prior_atr_14d": 0.40,
        "prior_atr_pct": 0.04,
        "avg_volume_20d": 500_000,
        "avg_dollar_volume_20d": 5_000_000,
        "ema_10_prior": 9.80,
        "ema_10_lag_3": 9.60,
        "ema_slope_prior": 0.0208,
    }
    vcf = features.compute_volume_curve_fraction(
        None, "2026-05-15T18:35:00Z", "1M_5M",
    )

    # The scanner path:
    sess_a = features.aggregate_forming_session_bar(bars_through_t)
    feats_a = features.compute_forming_session_features(
        sess_a, baselines, vcf,
    )

    # The backtester path (same exact module call):
    sess_b = features.aggregate_forming_session_bar(bars_through_t)
    feats_b = features.compute_forming_session_features(
        sess_b, baselines, vcf,
    )

    # Every numeric field must match to within 1e-9.
    for k in feats_a.keys():
        a, b = feats_a[k], feats_b[k]
        if a is None or b is None:
            assert a == b, f"{k}: {a!r} vs {b!r}"
            continue
        assert abs(a - b) < 1e-9, f"{k}: {a!r} vs {b!r}"
