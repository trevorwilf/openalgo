#!/usr/bin/env python3
"""
bowaka_prefilter.py — Daily US small/microcap "in-play" prefilter.

Runs once after US market close, builds a candidate list for the next
session, and writes it to a JSON file that an OpenAlgo /python strategy
reads at session open. See README.md for the cron setup and file
contract.

Pipeline:
  1. Acquire universe   - Alpaca assets endpoint, cached weekly.
  2. Fetch daily bars   - Alpaca Market Data API (IEX feed on free tier),
                          batched at 100 symbols/call.
  3. Compute features   - RVOL, ATR%, RangeExpansion, CloseLocation,
                          EMA distance + slope. Vectorized via groupby.
  4. Apply filters      - Universe gates (price, ADV) + signal gates.
  5. Write output       - Ranked JSON candidates, plus diagnostic CSV.

Auth:
  Set ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY in the environment.
  Paper-trading keys are fine for the prefilter — it only reads data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AssetClass, AssetStatus
from alpaca.trading.requests import GetAssetsRequest

LOG = logging.getLogger("bowaka_prefilter")


# ---------------------------------------------------------------- config

def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def config_hash(cfg: dict) -> str:
    """Stable short hash so the strategy can detect a stale candidates
    file from a different config."""
    blob = json.dumps(cfg, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:8]


def setup_logging(cfg: dict) -> None:
    log_cfg = cfg.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO").upper())
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if path := log_cfg.get("file"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path))
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )


# -------------------------------------------------------------- universe

def load_or_refresh_universe(
    trading_client: TradingClient,
    cache_path: Path,
    refresh_days: int,
    allowed_exchanges: set[str],
) -> list[str]:
    """Active, tradable US-equity symbols. Cached to disk, refreshed
    after `refresh_days` to keep API load reasonable."""
    if cache_path.exists():
        age_days = (time.time() - cache_path.stat().st_mtime) / 86400.0
        if age_days < refresh_days:
            with open(cache_path) as f:
                cached = json.load(f)
            LOG.info(
                "Universe loaded from cache: %d symbols (age %.1f days)",
                len(cached["symbols"]),
                age_days,
            )
            return cached["symbols"]

    LOG.info("Refreshing universe from Alpaca assets endpoint")
    req = GetAssetsRequest(
        asset_class=AssetClass.US_EQUITY,
        status=AssetStatus.ACTIVE,
    )
    assets = trading_client.get_all_assets(req)
    symbols: list[str] = []
    for a in assets:
        if not a.tradable:
            continue
        exch = a.exchange.value if hasattr(a.exchange, "value") else str(a.exchange)
        if exch not in allowed_exchanges:
            continue
        # Heuristic warrant/unit/right filter — these names commonly
        # have noisy data and aren't what the strategy targets.
        # The downstream price + ADV gate catches most of the rest.
        nm = (a.name or "").upper()
        if any(tag in nm for tag in (" WARRANT", " UNIT", " RIGHT", " PREFERRED")):
            continue
        symbols.append(a.symbol)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(
            {"symbols": symbols,
             "refreshed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
            f,
        )
    LOG.info("Universe: %d symbols cached to %s", len(symbols), cache_path)
    return symbols


# ------------------------------------------------------------------ bars

def fetch_daily_bars(
    data_client: StockHistoricalDataClient,
    symbols: list[str],
    lookback_calendar_days: int,
    feed: str,
    batch_size: int,
) -> pd.DataFrame:
    """Daily OHLCV bars for `symbols`, returned as a multi-index DF
    (symbol, timestamp). Failures are per-batch — one bad batch doesn't
    fail the run."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_calendar_days)
    feed_enum = DataFeed[feed.upper()]

    n_batches = (len(symbols) + batch_size - 1) // batch_size
    all_frames: list[pd.DataFrame] = []
    n_failed_batches = 0

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i : i + batch_size]
        batch_idx = i // batch_size + 1
        try:
            request = StockBarsRequest(
                symbol_or_symbols=batch,
                timeframe=TimeFrame.Day,
                start=start,
                end=end,
                feed=feed_enum,
            )
            resp = data_client.get_stock_bars(request)
            df = resp.df
            if df is not None and not df.empty:
                all_frames.append(df)
            LOG.debug(
                "Batch %d/%d: %d symbols, %d bars",
                batch_idx, n_batches, len(batch), 0 if df is None else len(df),
            )
        except Exception as e:
            n_failed_batches += 1
            LOG.warning("Batch %d/%d failed (%s..%s): %s",
                        batch_idx, n_batches, batch[0], batch[-1], e)

    if n_failed_batches:
        LOG.warning("%d/%d batches failed", n_failed_batches, n_batches)
    if not all_frames:
        return pd.DataFrame()
    out = pd.concat(all_frames)
    LOG.info(
        "Fetched %d bars across %d symbols",
        len(out), out.index.get_level_values(0).nunique(),
    )
    return out


# -------------------------------------------------------------- features

def compute_features(bars_df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Per-symbol Bowaka-like features, returning the latest row per
    symbol (one row = one symbol, indexed by symbol)."""
    if bars_df.empty:
        return pd.DataFrame()

    lookback = int(cfg["indicators"]["lookback_days"])
    atr_n = int(cfg["indicators"]["atr_days"])
    ema_n = int(cfg["indicators"]["ema_days"])
    slope_lb = int(cfg["indicators"]["ema_slope_lookback"])

    df = bars_df.reset_index()
    # alpaca-py returns lowercase OHLCV columns and a 'symbol' / 'timestamp' index
    df = df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    g = df.groupby("symbol", sort=False)

    df["dollar_volume"] = df["close"] * df["volume"]
    df["avg_dollar_volume"] = g["dollar_volume"].transform(
        lambda s: s.shift(1).rolling(lookback).mean()
    )
    df["avg_volume"] = g["volume"].transform(
        lambda s: s.shift(1).rolling(lookback).mean()
    )
    df["rvol"] = df["volume"] / df["avg_volume"]

    df["prev_close"] = g["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - df["prev_close"]).abs(),
            (df["low"] - df["prev_close"]).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["atr"] = tr.groupby(df["symbol"]).transform(lambda s: s.rolling(atr_n).mean())
    df["atr_pct"] = df["atr"] / df["close"]

    df["gap_pct"] = df["open"] / df["prev_close"] - 1.0
    df["range_expansion"] = (df["high"] - df["low"]) / df["atr"]

    rng = (df["high"] - df["low"]).replace(0, np.nan)
    df["close_location"] = ((df["close"] - df["low"]) / rng).fillna(0.5)

    df["ema"] = g["close"].transform(lambda s: s.ewm(span=ema_n, adjust=False).mean())
    df["ema_distance"] = df["close"] / df["ema"] - 1.0
    df["ema_lagged"] = df.groupby("symbol")["ema"].shift(slope_lb)
    df["ema_slope"] = df["ema"] / df["ema_lagged"] - 1.0

    latest = df.groupby("symbol", sort=False).tail(1).set_index("symbol")
    return latest


# --------------------------------------------------------------- filters

def apply_filters(features_df: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, dict]:
    """Apply universe + signal gates. Returns (passing_df, counts_dict)."""
    U = cfg["universe"]
    S = cfg["signals"]
    n_total = len(features_df)
    df = features_df.copy()

    # Universe gates
    df = df[df["close"].between(U["price_min"], U["price_max"], inclusive="both")]
    if (mn := U.get("avg_dollar_volume_min")) is not None:
        df = df[df["avg_dollar_volume"] >= mn]
    if (mx := U.get("avg_dollar_volume_max")) is not None:
        df = df[df["avg_dollar_volume"] <= mx]
    n_passed_universe = len(df)

    # Signal gates — every threshold is a >= check (the YAML uses null
    # to disable a gate)
    gate_specs = [
        ("rvol_min", "rvol"),
        ("atr_pct_min", "atr_pct"),
        ("range_expansion_min", "range_expansion"),
        ("close_location_min", "close_location"),
        ("ema_distance_min", "ema_distance"),
        ("ema_slope_min", "ema_slope"),
    ]
    for cfg_key, col in gate_specs:
        thr = S.get(cfg_key)
        if thr is not None:
            df = df[df[col] >= thr]

    df["signal_strength"] = (
        df["rvol"].fillna(0)
        + df["range_expansion"].fillna(0)
        + df["ema_distance"].fillna(0) * 10
        + df["ema_slope"].fillna(0) * 10
    )
    df = df.sort_values("signal_strength", ascending=False)

    counts = {
        "n_universe_with_features": n_total,
        "n_passed_universe_gates": n_passed_universe,
        "n_in_play": len(df),
    }
    LOG.info(
        "Filter funnel: %d -> %d (universe gates) -> %d (signal gates)",
        n_total, n_passed_universe, len(df),
    )
    return df, counts


# ---------------------------------------------------------------- output

def write_output(
    candidates: pd.DataFrame, counts: dict, cfg: dict, cfg_hash: str
) -> None:
    out_path = Path(cfg["output"]["candidates_path"])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    feature_cols = [
        "close", "rvol", "atr_pct", "range_expansion", "gap_pct",
        "close_location", "ema_distance", "ema_slope",
        "avg_dollar_volume", "signal_strength",
    ]
    rows: list[dict] = []
    for sym, row in candidates.iterrows():
        d = {"ticker": sym}
        for c in feature_cols:
            v = row.get(c)
            d[c] = None if v is None or pd.isna(v) else float(v)
        rows.append(d)

    now_utc = datetime.now(timezone.utc)
    payload = {
        "as_of_date": now_utc.date().isoformat(),
        "generated_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "config_hash": cfg_hash,
        **counts,
        "candidates": rows,
    }
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)
    LOG.info("Wrote %d candidates -> %s", len(rows), out_path)

    if diag := cfg["output"].get("diagnostic_csv"):
        Path(diag).parent.mkdir(parents=True, exist_ok=True)
        candidates.to_csv(diag)
        LOG.info("Wrote diagnostic CSV -> %s", diag)


# ------------------------------------------------------------------ main

def main() -> int:
    parser = argparse.ArgumentParser(description="Bowaka-like daily prefilter")
    parser.add_argument("--config", required=True, help="Path to YAML config")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run pipeline but skip writing output files",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg)
    cfg_hash = config_hash(cfg)
    LOG.info("Starting prefilter (config_hash=%s)", cfg_hash)

    api_key = os.environ.get("ALPACA_API_KEY_ID")
    secret = os.environ.get("ALPACA_API_SECRET_KEY")
    if not api_key or not secret:
        LOG.error(
            "ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY must be set in env"
        )
        return 2

    trading_client = TradingClient(api_key, secret, paper=cfg["alpaca"]["paper"])
    data_client = StockHistoricalDataClient(api_key, secret)

    universe = load_or_refresh_universe(
        trading_client,
        cache_path=Path(cfg["universe"]["cache_path"]),
        refresh_days=int(cfg["universe"]["refresh_days"]),
        allowed_exchanges=set(cfg["universe"]["allowed_exchanges"]),
    )
    if not universe:
        LOG.error("Empty universe; aborting")
        return 3

    bars = fetch_daily_bars(
        data_client,
        symbols=universe,
        lookback_calendar_days=int(cfg["bars"]["lookback_calendar_days"]),
        feed=cfg["alpaca"]["feed"],
        batch_size=int(cfg["bars"]["batch_size"]),
    )
    if bars.empty:
        LOG.error("No bars returned; aborting (not overwriting prior output)")
        return 4

    features = compute_features(bars, cfg)
    candidates, counts = apply_filters(features, cfg)

    if args.dry_run:
        LOG.info("Dry run: not writing output. Top 10 candidates:\n%s",
                 candidates.head(10)[["close", "rvol", "atr_pct", "signal_strength"]])
        return 0

    write_output(candidates, counts, cfg, cfg_hash)
    return 0


if __name__ == "__main__":
    sys.exit(main())
