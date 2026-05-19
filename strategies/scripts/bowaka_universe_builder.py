#!/usr/bin/env python3
"""Bowaka v2 — universe builder ("garbage filter").

Replaces ``bowaka_prefilter.py``. Builds the daily-refreshed eligible
U.S. equity universe and writes the prior-daily baseline cache the
scanner reads. Importantly, this layer does NOT apply v2 signal
gates (rvol / range / close_location / ema_*) — those move into
the intraday scanner so the scanner can evaluate the FORMING
session bar against the same universe every minute.

Universe gates applied here (handoff §5.1 + §6 universe block):
- exchange whitelist
- OTC / ETF / ETN / leveraged / inverse / warrant / unit / right /
  preferred exclusions
- ticker blocklist
- price band
- avg_dollar_volume_min / max

Outputs:
- data/bowaka_v2/universe_snapshot.json  — eligible symbols + meta
- data/bowaka_v2/daily_feature_cache.parquet — prior baselines per symbol

CLI:
  python bowaka_universe_builder.py --config bowaka_universe_builder.yaml
  python bowaka_universe_builder.py --config bowaka_universe_builder.yaml --dry-run
  python bowaka_universe_builder.py --config bowaka_universe_builder.yaml --build-curve

The --dry-run flag uses a built-in 2-symbol fixture and skips the
network call so cron / CI can verify the binary boots.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

# Allow the script to be invoked directly without packaging.
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import pandas as pd  # noqa: E402
import yaml  # noqa: E402

import bowaka_v2_features as features  # noqa: E402
import bowaka_v2_paths as paths  # noqa: E402


LOG = logging.getLogger("bowaka_universe_builder")


# ---------------------------------------------------------------- instrument classification


# Phase 2.3 — instrument classification. Copied from the v1
# prefilter so the universe builder can keep the same decisions.
INSTRUMENT_CLASSES = {
    "operating_equity", "leveraged_etp", "inverse_etp", "etn",
    "etf", "preferred", "warrant", "unit", "right",
}


def classify_instrument(
    symbol: str, asset_meta: dict, cfg: dict,
) -> dict:
    """Classify a U.S. equity symbol. Returns
    ``{instrument_class, eligible_for_bowaka_equity_bucket,
    classification_reason}``.

    Order matters: ticker_blocklist > name-keyword match > asset_class
    fallback. Bowaka v2 trades only ``operating_equity`` — everything
    else flips ``eligible_for_bowaka_equity_bucket`` to False.
    """
    rules = cfg.get("instrument_rules") or {}
    name = str(asset_meta.get("name") or "").upper()
    # Pad with single spaces so short whitespace-bracketed tokens
    # like " R " match a standalone R at word boundaries instead of
    # an R embedded in another word (e.g. INDUSTRIES).
    padded_name = " " + name + " "
    ticker = (symbol or "").upper()

    block = set(rules.get("ticker_blocklist") or [])
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
        ("etf", "etf"),
        ("warrant", "warrant"),
        ("unit", "unit"),
        ("right", "right"),
        ("preferred", "preferred"),
    ):
        for token in (kw.get(cls) or []):
            # Don't strip the token — preserve any leading/trailing
            # whitespace that the operator explicitly added for
            # word-boundary semantics (e.g. " R " means the standalone
            # letter R).
            t = str(token).upper()
            if not t:
                continue
            if t in padded_name:
                return {
                    "instrument_class": label,
                    "eligible_for_bowaka_equity_bucket": False,
                    "classification_reason": f"name_keyword:{cls}:{t.strip()}",
                }

    asset_class = str(asset_meta.get("asset_class") or "").lower()
    if asset_class in {"etf", "us_etf"}:
        return {
            "instrument_class": "etf",
            "eligible_for_bowaka_equity_bucket": False,
            "classification_reason": "asset_class:etf",
        }

    return {
        "instrument_class": "operating_equity",
        "eligible_for_bowaka_equity_bucket": True,
        "classification_reason": "default_operating_equity",
    }


# ---------------------------------------------------------------- universe filtering


def _universe_filter(
    asset_meta: dict, cfg: dict,
) -> tuple[bool, str | None]:
    """Apply universe gates ONLY (no signal-strength evaluation).

    Returns ``(keep, drop_reason)``. ``drop_reason`` is None when
    the asset is kept.
    """
    universe = cfg.get("universe") or {}
    symbol = (asset_meta.get("symbol") or "").upper()
    exchange = (asset_meta.get("exchange") or "").upper()
    status = (asset_meta.get("status") or "").lower()
    tradable = bool(asset_meta.get("tradable", True))

    # Tradable / active / shortable.
    if not tradable:
        return False, "not_tradable"
    if status and status not in {"active", "active_tradable"}:
        return False, f"status:{status}"

    # Exchange whitelist + OTC.
    allowed = {e.upper() for e in (universe.get("allowed_exchanges") or [])}
    if allowed and exchange not in allowed:
        return False, f"exchange:{exchange}"
    if universe.get("exclude_otc", True) and exchange in {"OTC", "OTCBB", "OTCM"}:
        return False, "otc"

    # Ticker blocklist.
    block = set((universe.get("ticker_blocklist") or []))
    if symbol in block:
        return False, "ticker_blocklist"

    return True, None


def _instrument_class_drop_reason(
    classification: dict, cfg: dict,
) -> str | None:
    """Return a drop reason if the instrument class is excluded
    per the universe block, else None."""
    universe = cfg.get("universe") or {}
    cls = classification.get("instrument_class")
    map_ = {
        "etf":            "exclude_etf",
        "etn":            "exclude_etn",
        "leveraged_etp":  "exclude_leveraged_etp",
        "inverse_etp":    "exclude_inverse_etp",
        "warrant":        "exclude_warrants",
        "unit":           "exclude_units",
        "right":          "exclude_rights",
        "preferred":      "exclude_preferred",
    }
    key = map_.get(cls)
    if key and universe.get(key, True):
        return f"instrument_class:{cls}"
    return None


def _price_adv_drop_reason(
    asset_meta: dict, baselines: dict, cfg: dict,
) -> str | None:
    universe = cfg.get("universe") or {}
    prior_close = baselines.get("prior_close")
    if prior_close is None:
        return "missing_prior_close"
    p_min = universe.get("price_min")
    p_max = universe.get("price_max")
    if p_min is not None and prior_close < float(p_min):
        return f"price_below_min:{prior_close}<{p_min}"
    if p_max is not None and prior_close > float(p_max):
        return f"price_above_max:{prior_close}>{p_max}"
    adv = baselines.get("avg_dollar_volume_20d")
    adv_min = universe.get("avg_dollar_volume_min")
    adv_max = universe.get("avg_dollar_volume_max")
    if adv_min is not None and (adv is None or adv < float(adv_min)):
        return f"adv_below_min:{adv}<{adv_min}"
    if adv_max is not None and adv is not None and adv > float(adv_max):
        return f"adv_above_max:{adv}>{adv_max}"
    return None


# ---------------------------------------------------------------- build


def _hash(payload: Any) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


def _config_hash(cfg: dict) -> str:
    return _hash(cfg)


def _universe_hash(symbols: list[str]) -> str:
    return _hash(sorted(symbols))


def build_universe(
    cfg: dict,
    *,
    asset_supplier: Callable[[], list[dict]] | None = None,
    bars_supplier: Callable[[str], pd.DataFrame] | None = None,
    today_et: date | None = None,
) -> tuple[list[dict], pd.DataFrame, dict[str, Any]]:
    """Run the universe build pipeline.

    ``asset_supplier`` returns the raw asset list (list of dicts).
    ``bars_supplier`` returns a per-symbol daily-bar DataFrame
    (ending at the prior completed session). These are injection
    points so tests can supply fixtures without network calls.

    Returns ``(snapshot_rows, daily_feature_cache_df, metadata)``.
    """
    if today_et is None:
        today_et = datetime.now(timezone.utc).date()
    if asset_supplier is None or bars_supplier is None:
        raise RuntimeError(
            "asset_supplier and bars_supplier must be provided; "
            "network adapters live in the production wrapper"
        )

    raw_assets = asset_supplier()
    hf_cfg = cfg.get("historical_features") or {}
    atr_n = int(hf_cfg.get("atr_days", 14))
    lookback = int(hf_cfg.get("lookback_days", 20))
    ema_n = int(hf_cfg.get("ema_days", 10))
    ema_slope_lookback = int(hf_cfg.get("ema_slope_lookback", 3))

    snapshot_rows: list[dict] = []
    cache_rows: list[dict] = []
    dropped: dict[str, str] = {}

    for asset in raw_assets:
        symbol = (asset.get("symbol") or "").upper()
        if not symbol:
            continue

        keep, reason = _universe_filter(asset, cfg)
        if not keep:
            dropped[symbol] = reason or "unknown"
            continue

        classification = classify_instrument(symbol, asset, cfg)
        cls_drop = _instrument_class_drop_reason(classification, cfg)
        if cls_drop:
            dropped[symbol] = cls_drop
            continue

        # Fetch prior daily bars + compute baselines.
        try:
            bars = bars_supplier(symbol)
        except Exception as e:
            LOG.warning("bars fetch failed for %s: %s", symbol, e)
            dropped[symbol] = "bars_fetch_error"
            continue
        if bars is None or len(bars) == 0:
            dropped[symbol] = "no_daily_bars"
            continue
        baselines = features.compute_prior_daily_baselines(
            bars,
            atr_n=atr_n, lookback=lookback,
            ema_n=ema_n, ema_slope_lookback=ema_slope_lookback,
        )

        # Price + ADV band check (universe gate, not signal gate).
        drop = _price_adv_drop_reason(asset, baselines, cfg)
        if drop:
            dropped[symbol] = drop
            continue

        venue_code = asset.get("venue_code") or _guess_venue_code(
            asset.get("exchange")
        )

        snapshot_rows.append({
            "symbol": symbol,
            "exchange": asset.get("exchange"),
            "venue_code": venue_code,
            "instrument_class": classification["instrument_class"],
            "eligible_for_bowaka_equity_bucket":
                classification["eligible_for_bowaka_equity_bucket"],
            "classification_reason": classification["classification_reason"],
            "name": asset.get("name"),
        })
        cache_rows.append({
            "symbol": symbol,
            "as_of_date": today_et.isoformat(),
            "prior_close": baselines["prior_close"],
            "avg_volume_20d": baselines["avg_volume_20d"],
            "avg_dollar_volume_20d": baselines["avg_dollar_volume_20d"],
            "prior_atr_14d": baselines["prior_atr_14d"],
            "prior_atr_pct": baselines["prior_atr_pct"],
            "ema_10_prior": baselines["ema_10_prior"],
            "ema_10_lag_3": baselines["ema_10_lag_3"],
            "ema_slope_prior": baselines["ema_slope_prior"],
        })

    snapshot_rows.sort(key=lambda r: r["symbol"])
    symbols = [r["symbol"] for r in snapshot_rows]

    cache_df = pd.DataFrame(cache_rows)
    if not cache_df.empty:
        # Pin column types for downstream consumers.
        for col in (
            "prior_close", "avg_volume_20d", "avg_dollar_volume_20d",
            "prior_atr_14d", "prior_atr_pct",
            "ema_10_prior", "ema_10_lag_3", "ema_slope_prior",
        ):
            if col in cache_df:
                cache_df[col] = pd.to_numeric(cache_df[col], errors="coerce")

    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of_date": today_et.isoformat(),
        "provider": (cfg.get("data") or {}).get("provider", "alpaca"),
        "data_feed": (cfg.get("data") or {}).get("feed", "iex"),
        "universe_hash": _universe_hash(symbols),
        "config_hash": _config_hash(cfg),
        "symbols_count": len(symbols),
        "dropped_count": len(dropped),
        "dropped_breakdown": _topk_breakdown(dropped),
    }
    return snapshot_rows, cache_df, metadata


def _guess_venue_code(exchange: str | None) -> str:
    mapping = {
        "NASDAQ": "XNAS", "NYSE": "XNYS",
        "AMEX": "XASE",  "ARCA": "ARCX", "BATS": "BATS",
    }
    return mapping.get((exchange or "").upper(), "XNAS")


def _topk_breakdown(d: dict[str, str], k: int = 10) -> dict[str, int]:
    from collections import Counter
    return dict(Counter(d.values()).most_common(k))


def write_outputs(
    snapshot_rows: list[dict],
    cache_df: pd.DataFrame,
    metadata: dict,
    cfg: dict,
) -> tuple[Path, Path]:
    """Atomic write: tmpfile + rename, parents pre-created."""
    paths.ensure_dirs()
    snap_path = _resolve_path(cfg, "universe_snapshot_path",
                                paths.UNIVERSE_SNAPSHOT_PATH)
    cache_path = _resolve_path(cfg, "daily_feature_cache_path",
                                  paths.DAILY_FEATURE_CACHE_PATH)
    snap_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    snap_doc = {
        **metadata,
        "symbols": snapshot_rows,
    }
    tmp_snap = snap_path.with_suffix(snap_path.suffix + ".tmp")
    tmp_snap.write_text(json.dumps(snap_doc, indent=2, default=str))
    os.replace(tmp_snap, snap_path)

    if not cache_df.empty:
        tmp_cache = cache_path.with_suffix(cache_path.suffix + ".tmp")
        try:
            cache_df.to_parquet(tmp_cache, index=False)
        except Exception as e:
            LOG.warning("parquet write failed (%s); falling back to jsonl.gz", e)
            tmp_cache = cache_path.with_suffix(".jsonl.gz.tmp")
            cache_path = cache_path.with_suffix(".jsonl.gz")
            cache_df.to_json(tmp_cache, orient="records",
                              lines=True, compression="gzip")
        os.replace(tmp_cache, cache_path)
    else:
        # Touch an empty parquet placeholder so downstream readers see it.
        try:
            cache_df.to_parquet(cache_path, index=False)
        except Exception:
            cache_path.write_text("")

    return snap_path, cache_path


def _resolve_path(cfg: dict, key: str, default: Path) -> Path:
    """Resolve a config-supplied path. Absolute paths pass through;
    relative paths are anchored at the repo root."""
    p_str = (cfg.get("paths") or {}).get(key)
    if not p_str:
        return default
    p = Path(p_str)
    if p.is_absolute():
        return p
    return paths.REPO_ROOT / p


# ---------------------------------------------------------------- dry-run fixture


def _dry_run_assets() -> list[dict]:
    """Two synthetic symbols for the --dry-run smoke command. One
    passes universe gates; one is a leveraged ETP that should be
    dropped."""
    return [
        {
            "symbol": "FOO", "exchange": "NASDAQ", "venue_code": "XNAS",
            "name": "Foo Industries Inc.",
            "asset_class": "us_equity",
            "tradable": True, "status": "active",
        },
        {
            "symbol": "TSLL", "exchange": "NASDAQ", "venue_code": "XNAS",
            "name": "Direxion Daily TSLA Bull 1.5X Shares",
            "asset_class": "us_equity",
            "tradable": True, "status": "active",
        },
    ]


def _dry_run_bars(symbol: str) -> pd.DataFrame:
    """30 days of synthetic daily bars for the dry-run smoke."""
    base = 8.0 if symbol == "FOO" else 12.0
    rows = []
    for i in range(30):
        c = base + i * 0.03
        rows.append({
            "timestamp": datetime(2026, 4, 1, tzinfo=timezone.utc)
                         + timedelta(days=i),
            "open":  c - 0.05, "high": c + 0.10,
            "low":   c - 0.10, "close": c,
            "volume": 500_000 + i * 1000,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- CLI


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _setup_logging(cfg: dict) -> None:
    L = cfg.get("logging") or {}
    level_name = (L.get("level") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        force=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bowaka v2 universe builder",
    )
    parser.add_argument(
        "--config", required=True,
        help="Path to bowaka_universe_builder.yaml",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Use a built-in 2-symbol fixture; skip the Alpaca call.",
    )
    parser.add_argument(
        "--build-curve", action="store_true",
        help="After the universe build, also (re)compute the time-of-day "
             "volume curve via bowaka_v2_volume_curve.py.",
    )
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    _setup_logging(cfg)

    if args.dry_run:
        asset_supplier = _dry_run_assets
        bars_supplier = _dry_run_bars
        LOG.info("dry-run mode: using built-in fixture (no network)")
    else:
        # Production path — a real Alpaca-backed supplier should be
        # wired in here. For Phase 2 the supplier is operator-supplied
        # via env-var BOWAKA_UNIVERSE_ASSET_SUPPLIER (advanced) OR
        # the dry-run path is the canonical CI smoke.
        LOG.error(
            "production network supplier not yet wired (Phase 3 will "
            "land the Alpaca client). Use --dry-run for now."
        )
        return 2

    snapshot_rows, cache_df, metadata = build_universe(
        cfg,
        asset_supplier=asset_supplier,
        bars_supplier=bars_supplier,
    )
    snap_path, cache_path = write_outputs(
        snapshot_rows, cache_df, metadata, cfg,
    )
    LOG.info(
        "universe build complete: kept=%d dropped=%d universe_hash=%s",
        metadata["symbols_count"],
        metadata["dropped_count"],
        metadata["universe_hash"],
    )
    LOG.info("snapshot -> %s", snap_path)
    LOG.info("cache    -> %s", cache_path)

    if args.build_curve:
        # Lazy import; the curve helper is its own module.
        try:
            import bowaka_v2_volume_curve as vcurve  # noqa: F401
            LOG.info("volume curve module available (operator must invoke it)")
        except ImportError:
            LOG.info(
                "--build-curve requested but bowaka_v2_volume_curve.py "
                "not yet present (lands in Phase 3)"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
