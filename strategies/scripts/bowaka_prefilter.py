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
from typing import Any

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


# Phase 1.2 — provenance helpers for candidate JSON schema v2.
def stable_hash(obj: Any) -> str:
    """Phase 1.2: full-hex SHA-256 digest with a ``sha256:`` prefix.

    Canonical for ``config_hash`` and ``universe_hash`` in the v2
    candidate-file schema. Distinct from the legacy short
    ``config_hash`` (kept under ``config_hash_short`` for back-compat
    with the strategy's existing handshake comparator).

    JSON serialization uses ``sort_keys=True`` and the compact
    separators so structurally-equivalent inputs hash identically
    regardless of dict ordering or whitespace.
    """
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      default=str).encode()
    return "sha256:" + hashlib.sha256(blob).hexdigest()


# Schema version pinned by Phase 1.2 — strategy fail-closes on a
# mismatch when ``prefilter_handshake.expected_schema_version`` is set.
CANDIDATES_SCHEMA_VERSION: int = 2


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

# Alpaca's listing-exchange code -> ISO 10383 MIC (the venue code the
# OpenAlgo /api/v2 instrument resolution expects). Listed here once so
# the strategy can route NYSE / AMEX / ARCA / BATS candidates to the
# right venue instead of the previous XNAS hardcode.
#
# AMEX folds to XNYS to match OpenAlgo's Alpaca plugin
# (``broker/alpaca/mapping/transform_data.py``) — NYSE American is an
# NYSE subsidiary and Alpaca's quote/bar/order adapters only accept
# {XNAS, XNYS, ARCX, BATS} as canonical venues.
ALPACA_EXCHANGE_TO_MIC: dict[str, str] = {
    "NASDAQ": "XNAS",
    "NYSE":   "XNYS",
    "AMEX":   "XNYS",
    "ARCA":   "ARCX",
    "BATS":   "BATS",
}


def load_or_refresh_universe(
    trading_client: TradingClient,
    cache_path: Path,
    refresh_days: int,
    allowed_exchanges: set[str],
) -> tuple[list[str], dict[str, str], dict[str, dict]]:
    """Active, tradable US-equity symbols + their listing exchange.

    Returns ``(symbols, exchanges, asset_meta)`` where
    ``exchanges[symbol]`` is the Alpaca exchange code (``"NASDAQ"``,
    ``"NYSE"``, ...) and ``asset_meta[symbol]`` carries ``{name,
    asset_class}`` so Phase 2.3 can classify leveraged ETPs / ETNs by
    name keyword + asset class.

    Cached to disk, refreshed after ``refresh_days``. Older caches
    without ``asset_meta`` are upgraded in-place — the next run
    rebuilds so classification can run; in the meantime the partial
    cache is returned with an empty meta dict so the strategy
    continues to operate.
    """
    if cache_path.exists():
        age_days = (time.time() - cache_path.stat().st_mtime) / 86400.0
        if age_days < refresh_days:
            with open(cache_path) as f:
                cached = json.load(f)
            cached_symbols = cached.get("symbols") or []
            cached_exchanges = cached.get("exchanges") or {}
            cached_meta = cached.get("asset_meta") or {}
            if cached_symbols and cached_exchanges:
                LOG.info(
                    "Universe loaded from cache: %d symbols (age %.1f days, "
                    "meta=%d entries)",
                    len(cached_symbols), age_days, len(cached_meta),
                )
                return cached_symbols, cached_exchanges, cached_meta
            LOG.info(
                "Universe cache missing 'exchanges' map (age %.1f days); "
                "rebuilding so per-candidate venue_code can be emitted",
                age_days,
            )

    LOG.info("Refreshing universe from Alpaca assets endpoint")
    req = GetAssetsRequest(
        asset_class=AssetClass.US_EQUITY,
        status=AssetStatus.ACTIVE,
    )
    assets = trading_client.get_all_assets(req)
    symbols: list[str] = []
    exchanges: dict[str, str] = {}
    asset_meta: dict[str, dict] = {}
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
        exchanges[a.symbol] = exch
        # Phase 2.3: stash the Alpaca-side name and asset_class so
        # classify_instrument can read them downstream. Lower-case
        # the asset_class to match Alpaca's enum-value conventions.
        ac = a.asset_class.value if hasattr(a.asset_class, "value") else str(a.asset_class)
        asset_meta[a.symbol] = {
            "name": a.name or "",
            "asset_class": (ac or "").lower(),
        }

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(
            {"symbols": symbols,
             "exchanges": exchanges,
             "asset_meta": asset_meta,
             "refreshed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
            f,
        )
    LOG.info(
        "Universe: %d symbols cached to %s (asset_meta=%d entries)",
        len(symbols), cache_path, len(asset_meta),
    )
    return symbols, exchanges, asset_meta


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


# Phase 2.3 — instrument classification.
INSTRUMENT_CLASSES = {
    "operating_equity", "leveraged_etp", "inverse_etp", "etn",
    "etf", "preferred", "warrant", "unit", "right",
}


def classify_instrument(
    symbol: str, asset_meta: dict, cfg: dict,
) -> dict:
    """Classify a US-equity symbol per Report §8.10.

    Returns ``{instrument_class, eligible_for_bowaka_equity_bucket,
    classification_reason}``. The classifier reads:
      * ``asset_meta["name"]`` — Alpaca's instrument name (case
        insensitive substring match against ``instrument_rules.
        name_keywords.<bucket>``).
      * ``cfg["instrument_rules"]["ticker_blocklist"]`` — exact ticker
        match (anything here is leveraged_etp).
      * ``asset_meta["asset_class"]`` — Alpaca's class (``us_equity``
        is operating equity by default; ``etf`` is downgraded to its
        own bucket).

    Order matters: blocklist > name-keyword (leveraged > inverse >
    etn) > asset_class default. The first matching rule wins.

    Bowaka's "equity bucket" thesis is built on operating equities —
    leveraged ETPs (e.g. TSLL, SQQQ) and ETNs have decay / path
    dependence that breaks the multi-day stop_pct / target_pct
    geometry. ``eligible_for_bowaka_equity_bucket`` flips to False
    for everything that isn't ``operating_equity``.
    """
    rules = cfg.get("instrument_rules") or {}
    name = str(asset_meta.get("name") or "").upper()
    ticker = (symbol or "").upper()

    block = set((rules.get("ticker_blocklist") or []))
    if ticker in block:
        return {
            "instrument_class": "leveraged_etp",
            "eligible_for_bowaka_equity_bucket": False,
            "classification_reason": "ticker_blocklist",
        }

    kw = rules.get("name_keywords") or {}
    for cls, label in (
        ("leveraged", "leveraged_etp"),
        ("inverse", "inverse_etp"),
        ("etn", "etn"),
    ):
        for token in (kw.get(cls) or []):
            t = str(token).upper().strip()
            if t and t in name:
                return {
                    "instrument_class": label,
                    "eligible_for_bowaka_equity_bucket": False,
                    "classification_reason": f"name_keyword:{cls}:{t}",
                }

    asset_class = str(asset_meta.get("asset_class") or "").lower()
    if asset_class in {"etf", "us_etf"}:
        return {
            "instrument_class": "etf",
            "eligible_for_bowaka_equity_bucket": False,
            "classification_reason": "asset_class:etf",
        }

    # Fall-through: operating equity is the default for tradable
    # US equity that didn't match any exclusion rule.
    return {
        "instrument_class": "operating_equity",
        "eligible_for_bowaka_equity_bucket": True,
        "classification_reason": "default_operating_equity",
    }


# Phase 2.2 — bounded signal_strength score.
def compute_signal_strength(df: pd.DataFrame, cfg: dict) -> pd.Series:
    """Return the ``signal_strength`` column for ``df``.

    ``cfg["score"]["bounded"] == False`` (default) emits the legacy
    unbounded formula — bit-exact parity with pre-Phase-2 selection.
    ``bounded == True`` applies per-component caps and a penalty for
    gaps above ``gap_penalty_above`` (Report §8.2). Both modes live
    here so the unbounded baseline is testable against the bounded
    one on the same fixture.
    """
    score_cfg = cfg.get("score") or {}
    bounded = bool(score_cfg.get("bounded"))
    if not bounded:
        return (
            df["rvol"].fillna(0)
            + df["range_expansion"].fillna(0)
            + df["ema_distance"].fillna(0) * 10
            + df["ema_slope"].fillna(0) * 10
        )

    rvol_cap = float(score_cfg.get("rvol_score_cap") or 5.0)
    range_cap = float(score_cfg.get("range_score_cap") or 2.5)
    edist_cap = float(score_cfg.get("ema_distance_score_cap") or 0.40)
    eslope_cap = float(score_cfg.get("ema_slope_score_cap") or 0.25)
    gap_penalty_above = score_cfg.get("gap_penalty_above")
    gap_penalty_above_f = (
        float(gap_penalty_above) if gap_penalty_above is not None else None
    )

    rvol_term = df["rvol"].fillna(0).clip(upper=rvol_cap)
    range_term = df["range_expansion"].fillna(0).clip(upper=range_cap)
    edist_term = (df["ema_distance"].fillna(0).clip(upper=edist_cap)) * 10
    eslope_term = (df["ema_slope"].fillna(0).clip(upper=eslope_cap)) * 10
    s = rvol_term + range_term + edist_term + eslope_term

    if gap_penalty_above_f is not None and "gap_pct" in df.columns:
        # Subtract (gap_pct - threshold) when gap_pct exceeds the
        # penalty threshold; bigger gaps pay a bigger penalty.
        excess = (df["gap_pct"].fillna(0) - gap_penalty_above_f).clip(lower=0)
        s = s - excess
    return s


def apply_filters(
    features_df: pd.DataFrame, cfg: dict,
    *, asset_meta: dict[str, dict] | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Apply universe + signal gates. Returns (passing_df, counts_dict).

    Phase 2 extensions:
    * ``rvol_max`` / ``range_expansion_max`` / ``gap_pct_max`` reject
      blow-off / exhaustion / gap-and-fade entries when set.
    * ``compute_signal_strength`` is now the only place the score
      formula lives (parity for ``score.bounded=false``, bounded
      formula for ``score.bounded=true``).
    * ``classify_instrument`` is called per-symbol; the resulting
      ``instrument_class`` is attached to each row and rows whose
      class maps to ``action: "exclude"`` are dropped.
    """
    U = cfg["universe"]
    S = cfg["signals"]
    n_total = len(features_df)
    df = features_df.copy()
    asset_meta = asset_meta or {}

    # Universe gates
    df = df[df["close"].between(U["price_min"], U["price_max"], inclusive="both")]
    if (mn := U.get("avg_dollar_volume_min")) is not None:
        df = df[df["avg_dollar_volume"] >= mn]
    if (mx := U.get("avg_dollar_volume_max")) is not None:
        df = df[df["avg_dollar_volume"] <= mx]
    n_passed_universe = len(df)

    # Signal gates — every >= check (the YAML uses null to disable).
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

    # Phase 2.1 — max gates. Symmetric <= checks to the min loop above.
    max_gate_specs = [
        ("rvol_max", "rvol"),
        ("range_expansion_max", "range_expansion"),
        ("gap_pct_max", "gap_pct"),
    ]
    for cfg_key, col in max_gate_specs:
        thr = S.get(cfg_key)
        if thr is not None:
            df = df[df[col] <= float(thr)]

    # Phase 2.2 — bounded / unbounded signal strength.
    df["signal_strength"] = compute_signal_strength(df, cfg)
    df = df.sort_values("signal_strength", ascending=False)

    # Phase 2.3 — instrument classification. Attach to every row and
    # drop those whose class maps to ``action: "exclude"`` in the
    # instrument_rules. The dropped rows surface in the diagnostic CSV
    # via the ``excluded_reason`` column attached just-in-time before
    # write_output's CSV dump.
    rules = cfg.get("instrument_rules") or {}
    cls_records: list[dict] = []
    for sym in df.index.tolist():
        meta = asset_meta.get(sym, {}) or {}
        cls_records.append(classify_instrument(sym, meta, cfg))
    df["instrument_class"] = [r["instrument_class"] for r in cls_records]
    df["eligible_for_bowaka_equity_bucket"] = [
        r["eligible_for_bowaka_equity_bucket"] for r in cls_records
    ]
    df["classification_reason"] = [r["classification_reason"] for r in cls_records]
    # Action-driven exclusions. Rows whose class has action="exclude"
    # are dropped from the candidate file; they remain in the
    # diagnostic CSV (handled by write_output) with an excluded_reason.
    class_to_action: dict[str, str] = {}
    for cls_key, label in (
        ("leveraged_etp", "leveraged_etp"),
        ("inverse_etp", "inverse_etp"),
        ("etn", "etn"),
    ):
        action = ((rules.get(cls_key) or {}).get("action") or "").lower()
        if action:
            class_to_action[label] = action
    excluded_mask = df["instrument_class"].map(
        lambda c: class_to_action.get(c) == "exclude",
    ).fillna(False)
    excluded_df = df[excluded_mask].copy()
    df = df[~excluded_mask]

    n_in_play = len(df)
    counts = {
        "n_universe_with_features": n_total,
        "n_passed_universe_gates": n_passed_universe,
        "n_in_play": n_in_play,
        "n_excluded_by_instrument_class": len(excluded_df),
    }
    LOG.info(
        "Filter funnel: %d -> %d (universe gates) -> %d (signal gates+max+class)",
        n_total, n_passed_universe, n_in_play,
    )
    # Stash the excluded rows on the dataframe attribute so
    # write_output can persist them to the diagnostic CSV with an
    # ``excluded_reason`` column without changing the function
    # signature. Pandas attrs survive copy(), so this is safe.
    df.attrs["excluded_by_instrument_class"] = excluded_df
    return df, counts


# ---------------------------------------------------------------- output

def write_output(
    candidates: pd.DataFrame,
    counts: dict,
    cfg: dict,
    cfg_hash: str,
    *,
    exchanges: dict[str, str] | None = None,
    as_of_date_override: str | None = None,
    universe_symbols: list[str] | None = None,
    latest_bar_timestamp: str | None = None,
) -> None:
    out_path = Path(cfg["output"]["candidates_path"])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    exchanges = exchanges or {}

    feature_cols = [
        "close", "rvol", "atr_pct", "range_expansion", "gap_pct",
        "close_location", "ema_distance", "ema_slope",
        "avg_dollar_volume", "signal_strength",
    ]
    rows: list[dict] = []
    for sym, row in candidates.iterrows():
        # Stamp the listing exchange + ISO 10383 MIC the strategy will
        # use for /api/v2 instrument resolution. None when the universe
        # cache predates the venue-routing format — strategy falls back
        # to its default_venue_code for those rows.
        exch = exchanges.get(sym)
        d = {
            "ticker": sym,
            "exchange": exch,
            "venue_code": ALPACA_EXCHANGE_TO_MIC.get(exch) if exch else None,
        }
        for c in feature_cols:
            v = row.get(c)
            d[c] = None if v is None or pd.isna(v) else float(v)
        # Phase 2.3 — surface instrument-class fields into each
        # candidate record so the strategy-side defense in
        # select_entries can reject leveraged ETPs that slipped past
        # the universe build.
        if "instrument_class" in row.index:
            d["instrument_class"] = row.get("instrument_class")
        if "eligible_for_bowaka_equity_bucket" in row.index:
            d["eligible_for_bowaka_equity_bucket"] = bool(
                row.get("eligible_for_bowaka_equity_bucket")
            )
        if "classification_reason" in row.index:
            d["classification_reason"] = row.get("classification_reason")
        rows.append(d)

    now_utc = datetime.now(timezone.utc)
    # Phase 1.2: candidate JSON schema v2. Adds explicit provenance
    # so the strategy can fail-closed on feed / schema / config
    # mismatch instead of silently trading on the wrong tape. The
    # legacy short ``config_hash`` (8-hex) stays in the payload
    # under the existing key so the strategy's existing handshake
    # comparator keeps working; the new full sha256 lives under
    # ``config_hash_full`` and the v2 ``config_hash`` field now
    # carries the full-hex form. The strategy's load_candidates
    # reads ``config_hash`` first (full form, v2 contract) and
    # falls back to ``config_hash_short`` (8-hex, legacy) when the
    # short form is what's pinned in ``expected_config_hash``.
    full_config_hash = stable_hash(cfg)
    universe_hash = stable_hash(sorted(universe_symbols or []))
    feed = (cfg.get("alpaca") or {}).get("feed") or "iex"
    payload = {
        "schema_version": CANDIDATES_SCHEMA_VERSION,
        "strategy": "bowaka",
        "generated_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "as_of_date": as_of_date_override or now_utc.date().isoformat(),
        "provider": "alpaca",
        "data_feed": feed,
        "bar_timeframe": "1D",
        # v2 contract: ``config_hash`` is the full sha256:<hex> form.
        # ``config_hash_short`` keeps the legacy 8-hex form for the
        # strategy's existing prefilter-handshake comparator until
        # operators pin the new full form.
        "config_hash": full_config_hash,
        "config_hash_short": cfg_hash,
        "universe_hash": universe_hash,
        "latest_bar_timestamp": latest_bar_timestamp,
        **counts,
        "candidates": rows,
    }
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)
    LOG.info(
        "Wrote %d candidates -> %s (schema=%d, feed=%s)",
        len(rows), out_path, CANDIDATES_SCHEMA_VERSION, feed,
    )

    if diag := cfg["output"].get("diagnostic_csv"):
        Path(diag).parent.mkdir(parents=True, exist_ok=True)
        # Phase 2.3 — include rows excluded by instrument class so
        # operators can audit the leveraged-ETP drops post-run. The
        # excluded set is stashed on the dataframe by apply_filters.
        excluded_df = (
            candidates.attrs.get("excluded_by_instrument_class")
            if hasattr(candidates, "attrs") else None
        )
        out_df = candidates.copy()
        out_df["excluded_reason"] = None
        if excluded_df is not None and not excluded_df.empty:
            excluded_with_reason = excluded_df.copy()
            excluded_with_reason["excluded_reason"] = (
                excluded_with_reason["classification_reason"]
                if "classification_reason" in excluded_with_reason.columns
                else "instrument_class"
            )
            out_df = pd.concat([out_df, excluded_with_reason], axis=0)
        out_df.to_csv(diag)
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

    universe, exchanges, asset_meta = load_or_refresh_universe(
        trading_client,
        cache_path=Path(cfg["universe"]["cache_path"]),
        refresh_days=int(cfg["universe"]["refresh_days"]),
        allowed_exchanges=set(cfg["universe"]["allowed_exchanges"]),
    )
    if not universe:
        LOG.error("Empty universe; aborting")
        return 3

    # Phase 2.4 — exclude_otc redundancy check: every symbol's
    # listing exchange must be in allowed_exchanges. Anything else
    # is a code-level invariant violation.
    if (cfg.get("universe") or {}).get("exclude_otc"):
        allowed = set(cfg["universe"]["allowed_exchanges"])
        sneak_in = [s for s, e in exchanges.items() if e not in allowed]
        if sneak_in:
            LOG.error(
                "exclude_otc invariant violated: %d symbols carry a "
                "non-allowed listing exchange (sample=%s)",
                len(sneak_in), sneak_in[:5],
            )
            raise RuntimeError("exclude_otc invariant violated")

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

    # Item 8 (Critical #5): derive as_of_date from the latest bar
    # timestamp (in NYSE-Eastern time) rather than the wall-clock run
    # date. Holiday / weekend / data-lag runs would otherwise stamp
    # today as as_of even though the bars are from an earlier session
    # — load_candidates would then accept stale data.
    try:
        ts_index = bars.index.get_level_values("timestamp")
        latest_bar_ts = ts_index.max()
        as_of_date_override = (
            pd.Timestamp(latest_bar_ts)
              .tz_convert("America/New_York")
              .date()
              .isoformat()
        )
        # Phase 1.2: full ISO8601 UTC timestamp of the latest bar
        # for the v2 schema. Distinct from ``as_of_date`` which is
        # the NYSE date that bar belongs to.
        latest_bar_iso = (
            pd.Timestamp(latest_bar_ts).tz_convert("UTC").isoformat()
        )
        LOG.info(
            "as_of_date derived from latest bar timestamp: %s",
            as_of_date_override,
        )
    except Exception as e:
        LOG.warning(
            "could not derive as_of_date from bars (%s); falling back to run date",
            e,
        )
        as_of_date_override = None
        latest_bar_iso = None

    features = compute_features(bars, cfg)
    candidates, counts = apply_filters(features, cfg, asset_meta=asset_meta)

    if args.dry_run:
        LOG.info("Dry run: not writing output. Top 10 candidates:\n%s",
                 candidates.head(10)[["close", "rvol", "atr_pct", "signal_strength"]])
        return 0

    write_output(
        candidates, counts, cfg, cfg_hash,
        exchanges=exchanges,
        as_of_date_override=as_of_date_override,
        universe_symbols=universe,
        latest_bar_timestamp=latest_bar_iso,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
