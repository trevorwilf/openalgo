#!/usr/bin/env python3
"""Bowaka v2 — historical bars cache reader.

Thin helper that loads historical minute + daily parquet caches in
the schema the backtester expects. The caller is responsible for
populating the caches; this module just reads them.

Expected cache layout::

    data/cache/daily/<symbol>.parquet      columns: timestamp,
                                                     open, high, low,
                                                     close, volume
    data/cache/minute/<symbol>/<YYYY-MM-DD>.parquet
                                            same columns +
                                            (optional) vwap, trade_count
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd


def load_daily_bars(
    cache_root: Path, symbol: str, as_of_date: str | None = None,
) -> pd.DataFrame:
    """Load daily bars for ``symbol``. If ``as_of_date`` is set,
    truncate the frame to bars ending on the prior session."""
    path = cache_root / "daily" / f"{symbol}.parquet"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)
    if as_of_date is None:
        return df
    cutoff = pd.Timestamp(as_of_date)
    if "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"])
        if ts.dt.tz is None:
            ts = ts.dt.tz_localize("UTC")
        df = df.loc[ts < cutoff.tz_localize("UTC")].copy()
    return df


def load_minute_bars(
    cache_root: Path, symbol: str, session_date: str,
) -> pd.DataFrame:
    path = cache_root / "minute" / symbol / f"{session_date}.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)
