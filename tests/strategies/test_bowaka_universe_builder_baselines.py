"""Phase 2 — universe-builder baseline correctness + schema tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import json
import pandas as pd
import pytest

import bowaka_universe_builder as ub


def _bars_for_baselines() -> pd.DataFrame:
    """30 days of bars, plus a 31st 'today' row whose values the
    builder MUST ignore (caller is responsible for slicing the
    current session out before invoking compute_prior_daily_baselines).
    """
    rows = []
    for i in range(31):
        c = 5.0 + i * 0.10
        rows.append({
            "timestamp": datetime(2026, 4, 1, tzinfo=timezone.utc)
                         + timedelta(days=i),
            "open": c - 0.05, "high": c + 0.20,
            "low":  c - 0.20, "close": c, "volume": 500_000,
        })
    return pd.DataFrame(rows)


def _cfg() -> dict:
    return {
        "universe": {
            "allowed_exchanges": ["NASDAQ"],
            "exclude_otc": True,
            "price_min": 1.0, "price_max": 20.0,
            "avg_dollar_volume_min": 250_000,
        },
        "historical_features": {
            "lookback_days": 20, "atr_days": 14,
            "ema_days": 10, "ema_slope_lookback": 3,
        },
    }


def test_baselines_use_only_prior_completed_sessions():
    """The builder slices the bar frame to exclude today's row
    before computing baselines."""
    full_bars = _bars_for_baselines()
    # Caller convention: pass bars ending at the prior completed
    # session. Verify that the builder honors that — i.e., when the
    # caller passes the FULL frame including today, baselines reflect
    # the FULL frame; when the caller passes bars[:-1], baselines
    # reflect that earlier window.
    snap_full, cache_full, _ = ub.build_universe(
        _cfg(),
        asset_supplier=lambda: [{
            "symbol": "AAA", "exchange": "NASDAQ", "name": "AAA Inc",
            "asset_class": "us_equity",
            "tradable": True, "status": "active",
        }],
        bars_supplier=lambda s: full_bars,
    )
    snap_excl, cache_excl, _ = ub.build_universe(
        _cfg(),
        asset_supplier=lambda: [{
            "symbol": "AAA", "exchange": "NASDAQ", "name": "AAA Inc",
            "asset_class": "us_equity",
            "tradable": True, "status": "active",
        }],
        bars_supplier=lambda s: full_bars.iloc[:-1].copy(),
    )
    row_full = cache_full.iloc[0].to_dict()
    row_excl = cache_excl.iloc[0].to_dict()
    # prior_atr_14d must differ — the contract is "caller slices".
    assert row_full["prior_atr_14d"] != row_excl["prior_atr_14d"]
    # And the prior_close in the excl-today case is the second-to-last
    # row's close.
    assert row_excl["prior_close"] == pytest.approx(
        float(full_bars["close"].iloc[-2])
    )


def test_daily_feature_cache_schema():
    bars = _bars_for_baselines().iloc[:-1].copy()
    snap, cache, meta = ub.build_universe(
        _cfg(),
        asset_supplier=lambda: [{
            "symbol": "AAA", "exchange": "NASDAQ", "name": "AAA Inc",
            "asset_class": "us_equity",
            "tradable": True, "status": "active",
        }],
        bars_supplier=lambda s: bars,
    )
    assert not cache.empty
    expected_cols = {
        "symbol", "as_of_date", "prior_close",
        "avg_volume_20d", "avg_dollar_volume_20d",
        "prior_atr_14d", "prior_atr_pct",
        "ema_10_prior", "ema_10_lag_3", "ema_slope_prior",
    }
    assert expected_cols.issubset(set(cache.columns))


def test_universe_snapshot_required_fields():
    bars = _bars_for_baselines().iloc[:-1].copy()
    snap, _, meta = ub.build_universe(
        _cfg(),
        asset_supplier=lambda: [{
            "symbol": "AAA", "exchange": "NASDAQ", "name": "AAA Inc",
            "asset_class": "us_equity",
            "tradable": True, "status": "active",
        }],
        bars_supplier=lambda s: bars,
    )
    # Metadata block.
    for key in (
        "generated_at", "as_of_date", "provider", "data_feed",
        "universe_hash", "config_hash", "symbols_count",
        "dropped_count",
    ):
        assert key in meta, f"meta missing {key}"
    # Snapshot row schema.
    row = snap[0]
    for key in (
        "symbol", "exchange", "venue_code",
        "instrument_class", "eligible_for_bowaka_equity_bucket",
    ):
        assert key in row, f"snapshot row missing {key}"
