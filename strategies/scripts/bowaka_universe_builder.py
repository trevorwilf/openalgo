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
import time
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
    with open(tmp_snap, "w", encoding="utf-8") as f:
        f.write(json.dumps(snap_doc, indent=2, default=str))
        f.flush()
        os.fsync(f.fileno())
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
        # Empty parquet placeholder so downstream readers see it —
        # written atomically (tmp + replace) like the main path so a
        # crash mid-write can't leave a torn cache file.
        tmp_cache = cache_path.with_suffix(cache_path.suffix + ".tmp")
        try:
            cache_df.to_parquet(tmp_cache, index=False)
        except Exception:
            tmp_cache.write_text("")
        os.replace(tmp_cache, cache_path)

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


# ---------------------------------------------------------------- live suppliers


def _drop_today_forming_bar(df: pd.DataFrame) -> pd.DataFrame:
    """Drop today's (ET) daily bar so prior-daily baselines never see
    the current session (handoff §5.7 lookahead rule).

    The live daily fetch uses ``end=now``, so an intraday rebuild would
    otherwise fold today's partial (or just-closed) bar into
    prior_close / ATR / volume / EMA — corrupting every scanner gate
    that hot-reloads the feature cache for the rest of the session.
    No-op for a pre-market build (today's bar does not exist yet) and
    for any frame already ending at a prior session.
    """
    if df is None or len(df) == 0 or "timestamp" not in df.columns:
        return df
    ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    today_et = pd.Timestamp.now(tz="America/New_York").date()
    bar_et_date = ts.dt.tz_convert("America/New_York").dt.date
    keep = bar_et_date < today_et
    if keep.all():
        return df
    return df[keep].reset_index(drop=True)


def _live_suppliers(cfg: dict):
    """Wire the universe builder to OpenAlgo's /api/v2/bars + the
    cached US-equity asset list. Returns (asset_supplier,
    bars_supplier, http_client) — the caller is responsible for
    closing the http_client.
    """
    import bowaka_v2_openalgo_client as oa  # local import to avoid pandas-on-startup cost

    live = (cfg.get("live_fetch") or {})
    host = os.environ.get(live.get("host_server_env", "HOST_SERVER"),
                            "http://127.0.0.1:5000")
    api_key = os.environ.get(live.get("api_key_env", "OPENALGO_API_KEY"))
    if not api_key:
        LOG.error(
            "OPENALGO_API_KEY env var must be set for live build "
            "(or pass --dry-run)"
        )
        raise SystemExit(2)
    lookback_days = int(live.get("daily_bars_lookback_calendar_days", 45))
    concurrency = max(1, int(live.get("fetch_concurrency", 32)))
    http = oa.make_http_client(host, max_connections=concurrency + 8)
    asset_cache_path = live.get(
        "asset_list_cache", "strategies/scripts/data/universe_us_equity.json",
    )

    pre_sample_n = (cfg.get("universe") or {}).get("pre_fetch_sample_n")
    pre_sample_seed = int(
        (cfg.get("universe") or {}).get("pre_fetch_sample_seed", 42)
    )

    # Memoize the eligible asset list + a one-time concurrent daily-bar
    # prefetch. build_universe calls asset_supplier() once then
    # bars_supplier(symbol) per symbol in a sequential loop; backing
    # bars_supplier with a parallel prefetch turns that loop into dict
    # lookups so a full (un-sampled) eligible set still builds in
    # seconds rather than minutes.
    _memo: dict[str, Any] = {"assets": None, "bars": None}

    def asset_supplier() -> list[dict]:
        if _memo["assets"] is not None:
            return _memo["assets"]
        cache_path = paths.REPO_ROOT / asset_cache_path
        if not cache_path.exists():
            LOG.error(
                "asset list cache not found at %s. Either run the "
                "v1 prefilter to refresh it, or copy a recent file there.",
                cache_path,
            )
            return []
        try:
            age_days = (
                time.time() - cache_path.stat().st_mtime
            ) / 86400.0
            if age_days > 7:
                LOG.warning(
                    "asset list cache is %.0f days old (%s) — newly "
                    "listed symbols are missing; refresh via the v1 "
                    "prefilter", age_days, cache_path,
                )
        except OSError:
            pass
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        symbols = cache.get("symbols") or []
        ex_by_sym = cache.get("exchanges") or {}
        meta_by_sym = cache.get("asset_meta") or {}
        # Build rows + immediately apply universe + instrument-class
        # filters in memory (no HTTP) so the pre-sample picks from
        # already-eligible symbols.
        all_rows = []
        for s in symbols:
            ex = ex_by_sym.get(s, "")
            m = meta_by_sym.get(s) or {}
            row = {
                "symbol": s,
                "exchange": ex,
                "venue_code": _guess_venue_code(ex),
                "name": m.get("name", ""),
                "asset_class": m.get("class", "us_equity"),
                "tradable": m.get("tradable", True),
                "status": m.get("status", "active"),
            }
            # Skip rows that the universe filter would drop anyway.
            keep, _ = _universe_filter(row, cfg)
            if not keep:
                continue
            classification = classify_instrument(s, row, cfg)
            if _instrument_class_drop_reason(classification, cfg):
                continue
            all_rows.append(row)
        LOG.info("eligible after universe + class filter: %d/%d",
                  len(all_rows), len(symbols))
        if pre_sample_n is not None and len(all_rows) > int(pre_sample_n):
            import random
            rng = random.Random(pre_sample_seed)
            all_rows = rng.sample(all_rows, int(pre_sample_n))
            LOG.info(
                "pre-fetch sample: %d symbols (seed=%d)",
                len(all_rows), pre_sample_seed,
            )
        _memo["assets"] = all_rows
        return all_rows

    def _fetch_one_daily(symbol: str) -> pd.DataFrame:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=lookback_days)
        try:
            return oa.fetch_bars(
                http, api_key,
                venue_code=_guess_venue_code(""), symbol=symbol,
                interval="1d", start=start, end=end,
            )
        except Exception as e:
            LOG.warning("daily bars fetch failed for %s: %s", symbol, e)
            return pd.DataFrame()

    def _prefetch_all_daily() -> None:
        assets = asset_supplier()
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=lookback_days)
        reqs = [
            {
                "venue_code": _guess_venue_code(""),
                "symbol": a["symbol"],
                "interval": "1d",
                "start": start, "end": end,
            }
            for a in assets
        ]
        t0 = time.monotonic()
        _memo["bars"] = oa.fetch_bars_concurrent(
            http, api_key, reqs, concurrency=concurrency,
        )
        LOG.info(
            "prefetched daily bars for %d symbols in %.1fs (concurrency=%d)",
            len(reqs), time.monotonic() - t0, concurrency,
        )

    def bars_supplier(symbol: str) -> pd.DataFrame:
        # Daily bars are venue-agnostic here (default XNAS), matching the
        # prior single-symbol behavior. First call triggers the one-time
        # concurrent prefetch; the rest are dict lookups.
        if _memo["bars"] is None:
            _prefetch_all_daily()
        df = _memo["bars"].get(symbol)
        if df is None:
            df = _fetch_one_daily(symbol)
        # Lookahead guard: never let today's forming session enter the
        # prior-daily baseline (applied at the single serving point so
        # both the prefetch cache and the fallback path are covered).
        return _drop_today_forming_bar(df)

    return asset_supplier, bars_supplier, http


def build_and_write(
    cfg: dict, asset_supplier, bars_supplier,
) -> int:
    """Run the universe build pipeline against live suppliers + apply
    the optional cap_to_n_symbols truncation."""
    snapshot_rows, cache_df, metadata = build_universe(
        cfg, asset_supplier=asset_supplier, bars_supplier=bars_supplier,
    )
    cap = (cfg.get("universe") or {}).get("cap_to_n_symbols")
    if cap and len(snapshot_rows) > int(cap):
        # Rank by avg_dollar_volume DESC; keep top N.
        if not cache_df.empty and "avg_dollar_volume_20d" in cache_df.columns:
            ranked = cache_df.sort_values(
                "avg_dollar_volume_20d", ascending=False,
            )
            kept = set(ranked["symbol"].iloc[:int(cap)].tolist())
            snapshot_rows = [r for r in snapshot_rows if r["symbol"] in kept]
            cache_df = cache_df[cache_df["symbol"].isin(kept)].copy()
            metadata["capped_to"] = int(cap)
            metadata["symbols_count"] = len(snapshot_rows)
            LOG.info("universe capped to %d symbols (by ADV)", cap)
        else:
            snapshot_rows = snapshot_rows[:int(cap)]
            metadata["capped_to"] = int(cap)
            metadata["symbols_count"] = len(snapshot_rows)
    rc = _refuse_suspicious_shrink(snapshot_rows, cfg)
    if rc is not None:
        return rc
    snap_path, cache_path = write_outputs(
        snapshot_rows, cache_df, metadata, cfg,
    )
    LOG.info(
        "universe build complete: kept=%d dropped=%d universe_hash=%s",
        metadata["symbols_count"], metadata["dropped_count"],
        metadata["universe_hash"],
    )
    LOG.info("snapshot -> %s", snap_path)
    LOG.info("cache    -> %s", cache_path)
    return 0


#: A previous snapshot at least this large arms the 50%-shrink guard.
_SHRINK_GUARD_MIN_PREV = 50


def _refuse_suspicious_shrink(
    snapshot_rows: list[dict], cfg: dict,
) -> int | None:
    """Guard the LIVE write path against clobbering a good universe
    with a bad build (finding 8): a transient asset-cache / bars-fetch
    failure yields an empty (or drastically smaller) symbol list, and
    writing it would blank the scanner for the rest of the session.

    Refuses (exit code 6, nothing written) when the new build has 0
    symbols, or when the existing snapshot holds >=
    ``_SHRINK_GUARD_MIN_PREV`` symbols and the new build has fewer
    than half of them. ``BOWAKA_UNIVERSE_ALLOW_SHRINK=1`` downgrades
    the refusal to a WARNING (deliberate universe reductions). Dry-run
    builds never route through here (they bypass build_and_write into
    the _dryrun/ sandbox). Returns 6 to refuse, None to proceed."""
    new_count = len(snapshot_rows)
    snap_path = _resolve_path(cfg, "universe_snapshot_path",
                                paths.UNIVERSE_SNAPSHOT_PATH)
    prev_count = None
    if snap_path.exists():
        try:
            prev_doc = json.loads(snap_path.read_text(encoding="utf-8"))
            pc = prev_doc.get("symbols_count")
            if isinstance(pc, int) and not isinstance(pc, bool):
                prev_count = pc
            elif isinstance(prev_doc.get("symbols"), list):
                prev_count = len(prev_doc["symbols"])
        except Exception as e:
            LOG.warning(
                "existing snapshot unreadable (%s) — shrink guard has "
                "no baseline", e,
            )
    suspicious = new_count == 0 or (
        prev_count is not None
        and prev_count >= _SHRINK_GUARD_MIN_PREV
        and new_count < 0.5 * prev_count
    )
    if not suspicious:
        return None
    if os.environ.get("BOWAKA_UNIVERSE_ALLOW_SHRINK") == "1":
        LOG.warning(
            "universe shrink override: writing %d symbols over an "
            "existing snapshot of %s (BOWAKA_UNIVERSE_ALLOW_SHRINK=1)",
            new_count, prev_count,
        )
        return None
    LOG.error(
        "REFUSING to write universe: new build has %d symbols vs the "
        "existing snapshot's %s — this smells like a transient fetch/"
        "cache failure, and writing it would blank the scanner. Set "
        "BOWAKA_UNIVERSE_ALLOW_SHRINK=1 to force a deliberate "
        "reduction. Nothing was written (exit 6).",
        new_count, prev_count,
    )
    return 6


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
    # httpx logs one INFO line per request — at build fan-out volume
    # that is pure noise in the err log.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


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
        # Dry-run must NEVER touch the live outputs — the tiny built-in
        # fixture would clobber the production universe snapshot and
        # daily feature cache. Redirect both outputs into a _dryrun/
        # sandbox next to the configured destination.
        snap_dest = _resolve_path(cfg, "universe_snapshot_path",
                                  paths.UNIVERSE_SNAPSHOT_PATH)
        cache_dest = _resolve_path(cfg, "daily_feature_cache_path",
                                   paths.DAILY_FEATURE_CACHE_PATH)
        dry_dir = snap_dest.parent / "_dryrun"
        cfg.setdefault("paths", {})
        cfg["paths"]["universe_snapshot_path"] = str(
            dry_dir / snap_dest.name,
        )
        cfg["paths"]["daily_feature_cache_path"] = str(
            dry_dir / cache_dest.name,
        )
        LOG.info(
            "dry-run mode: using built-in fixture (no network); "
            "outputs redirected to %s", dry_dir,
        )
    else:
        asset_supplier, bars_supplier, http_client_ref = _live_suppliers(cfg)
        try:
            res = build_and_write(
                cfg, asset_supplier, bars_supplier,
            )
        finally:
            if http_client_ref:
                http_client_ref.close()
        return res

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
