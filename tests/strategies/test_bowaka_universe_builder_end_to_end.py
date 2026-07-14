"""Phase 2 — universe builder end-to-end integration smoke."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

import bowaka_universe_builder as ub
import bowaka_v2_paths as paths


def _cfg(tmp_path: Path) -> dict:
    return {
        "paths": {
            "universe_snapshot_path": str(tmp_path / "universe_snapshot.json"),
            "daily_feature_cache_path": str(tmp_path / "daily_feature_cache.parquet"),
        },
        "data": {"provider": "alpaca", "feed": "iex"},
        "universe": {
            "allowed_exchanges": ["NASDAQ", "NYSE"],
            "exclude_otc": True,
            "exclude_etf": True,
            "exclude_leveraged_etp": True,
            "price_min": 1.0, "price_max": 20.0,
            "avg_dollar_volume_min": 250_000,
            "ticker_blocklist": [],
        },
        "instrument_rules": {
            "name_keywords": {
                "leveraged": ["2X", "3X"],
                "inverse": ["INVERSE"],
                "etn": ["NOTES"],
                "etf": ["ETF"],
            },
        },
        "historical_features": {
            "lookback_days": 20, "atr_days": 14,
            "ema_days": 10, "ema_slope_lookback": 3,
        },
    }


def test_end_to_end_writes_both_outputs(tmp_path):
    cfg = _cfg(tmp_path)
    assets = [
        {"symbol": "FOO", "exchange": "NASDAQ", "name": "Foo Inc",
         "asset_class": "us_equity", "tradable": True, "status": "active"},
        {"symbol": "BAR", "exchange": "NYSE", "name": "Bar Holdings",
         "asset_class": "us_equity", "tradable": True, "status": "active"},
    ]

    def bars_supplier(symbol):
        rows = []
        for i in range(25):
            c = 5.0 + i * 0.05
            rows.append({
                "timestamp": datetime(2026, 4, 1, tzinfo=timezone.utc)
                             + timedelta(days=i),
                "open": c - 0.05, "high": c + 0.10,
                "low":  c - 0.10, "close": c, "volume": 500_000,
            })
        return pd.DataFrame(rows)

    snap, cache, meta = ub.build_universe(
        cfg,
        asset_supplier=lambda: assets,
        bars_supplier=bars_supplier,
    )
    snap_path, cache_path = ub.write_outputs(snap, cache, meta, cfg)
    assert snap_path.exists()
    assert cache_path.exists()

    snap_doc = json.loads(snap_path.read_text())
    assert snap_doc["symbols_count"] == 2
    symbols = {s["symbol"] for s in snap_doc["symbols"]}
    assert symbols == {"FOO", "BAR"}
    assert snap_doc["universe_hash"].startswith("sha256:")
    assert snap_doc["config_hash"].startswith("sha256:")
    # data_feed lineage present.
    assert snap_doc["data_feed"] == "iex"
    # Cache parquet readable + contains both symbols.
    df = pd.read_parquet(cache_path)
    assert set(df["symbol"]) == {"FOO", "BAR"}
    assert "prior_close" in df.columns


def test_dry_run_smoke_completes(tmp_path, monkeypatch):
    """Phase 2 smoke command: python bowaka_universe_builder.py
    --config <cfg> --dry-run uses the built-in fixture and writes
    both outputs without a network call.

    Hardening Phase 7 (deliberate behavior change): dry-run outputs
    now land in a _dryrun/ sandbox next to the configured paths so
    the fixture can never clobber production outputs."""
    cfg_path = tmp_path / "cfg.yaml"
    cfg_text = (
        "paths:\n"
        f"  universe_snapshot_path: {tmp_path}/universe_snapshot.json\n"
        f"  daily_feature_cache_path: {tmp_path}/daily_feature_cache.parquet\n"
        "data:\n"
        "  provider: alpaca\n"
        "  feed: iex\n"
        "universe:\n"
        "  allowed_exchanges: [NASDAQ, NYSE]\n"
        "  exclude_otc: true\n"
        "  exclude_leveraged_etp: true\n"
        "  exclude_etf: true\n"
        "  price_min: 1.0\n"
        "  price_max: 50.0\n"
        "  avg_dollar_volume_min: 1.0\n"
        "  ticker_blocklist: []\n"
        "instrument_rules:\n"
        "  name_keywords:\n"
        "    leveraged: ['1.5X', '2X', '3X']\n"
        "    inverse: []\n"
        "    etn: []\n"
        "    etf: []\n"
        "historical_features:\n"
        "  lookback_days: 20\n"
        "  atr_days: 14\n"
        "  ema_days: 10\n"
        "  ema_slope_lookback: 3\n"
        "logging:\n"
        "  level: WARNING\n"
    )
    cfg_path.write_text(cfg_text)
    rc = ub.main(["--config", str(cfg_path), "--dry-run"])
    assert rc == 0
    snap_path = tmp_path / "_dryrun" / "universe_snapshot.json"
    cache_path = tmp_path / "_dryrun" / "daily_feature_cache.parquet"
    assert snap_path.exists()
    assert cache_path.exists()
    snap_doc = json.loads(snap_path.read_text())
    # FOO is the operating equity; TSLL is leveraged and dropped.
    assert {s["symbol"] for s in snap_doc["symbols"]} == {"FOO"}
    # The configured (production) paths were NOT written.
    assert not (tmp_path / "universe_snapshot.json").exists()
    assert not (tmp_path / "daily_feature_cache.parquet").exists()


def test_dry_run_never_clobbers_existing_production_outputs(tmp_path):
    """Regression for the --dry-run clobber: a live universe snapshot
    + feature cache at the configured paths must be byte-identical
    after a dry-run."""
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(
        "paths:\n"
        f"  universe_snapshot_path: {tmp_path}/universe_snapshot.json\n"
        f"  daily_feature_cache_path: {tmp_path}/daily_feature_cache.parquet\n"
        "data:\n  provider: alpaca\n  feed: iex\n"
        "universe:\n"
        "  allowed_exchanges: [NASDAQ, NYSE]\n"
        "  exclude_otc: true\n"
        "  exclude_leveraged_etp: true\n"
        "  exclude_etf: true\n"
        "  price_min: 1.0\n  price_max: 50.0\n"
        "  avg_dollar_volume_min: 1.0\n"
        "  ticker_blocklist: []\n"
        "instrument_rules:\n"
        "  name_keywords:\n"
        "    leveraged: ['2X', '3X']\n"
        "    inverse: []\n    etn: []\n    etf: []\n"
        "historical_features:\n"
        "  lookback_days: 20\n  atr_days: 14\n"
        "  ema_days: 10\n  ema_slope_lookback: 3\n"
        "logging:\n  level: WARNING\n"
    )
    prod_snap = tmp_path / "universe_snapshot.json"
    prod_cache = tmp_path / "daily_feature_cache.parquet"
    prod_snap.write_text('{"symbols": ["PRODUCTION"], "sentinel": 1}')
    prod_cache.write_bytes(b"PRODUCTION-PARQUET-SENTINEL")

    rc = ub.main(["--config", str(cfg_path), "--dry-run"])
    assert rc == 0
    assert prod_snap.read_text() == (
        '{"symbols": ["PRODUCTION"], "sentinel": 1}')
    assert prod_cache.read_bytes() == b"PRODUCTION-PARQUET-SENTINEL"
    assert (tmp_path / "_dryrun" / "universe_snapshot.json").exists()


# ---- fix Phase 8: shrink guard --------------------------------------------------


def _write_prev_snapshot(tmp_path: Path, count: int) -> Path:
    snap = tmp_path / "universe_snapshot.json"
    snap.write_text(json.dumps({
        "symbols_count": count,
        "symbols": [{"symbol": f"S{i}"} for i in range(min(count, 3))],
        "universe_hash": "sha256:prev",
    }), encoding="utf-8")
    return snap


def _rows(n: int) -> list[dict]:
    return [{"symbol": f"S{i}"} for i in range(n)]


def test_shrink_guard_refuses_empty_build(tmp_path, monkeypatch):
    monkeypatch.delenv("BOWAKA_UNIVERSE_ALLOW_SHRINK", raising=False)
    cfg = _cfg(tmp_path)
    _write_prev_snapshot(tmp_path, 600)
    assert ub._refuse_suspicious_shrink([], cfg) == 6


def test_shrink_guard_refuses_empty_even_without_previous(tmp_path, monkeypatch):
    monkeypatch.delenv("BOWAKA_UNIVERSE_ALLOW_SHRINK", raising=False)
    cfg = _cfg(tmp_path)
    assert ub._refuse_suspicious_shrink([], cfg) == 6


def test_shrink_guard_refuses_600_to_200(tmp_path, monkeypatch):
    monkeypatch.delenv("BOWAKA_UNIVERSE_ALLOW_SHRINK", raising=False)
    cfg = _cfg(tmp_path)
    _write_prev_snapshot(tmp_path, 600)
    assert ub._refuse_suspicious_shrink(_rows(200), cfg) == 6


def test_shrink_guard_allows_600_to_550(tmp_path, monkeypatch):
    monkeypatch.delenv("BOWAKA_UNIVERSE_ALLOW_SHRINK", raising=False)
    cfg = _cfg(tmp_path)
    _write_prev_snapshot(tmp_path, 600)
    assert ub._refuse_suspicious_shrink(_rows(550), cfg) is None


def test_shrink_guard_ignores_small_previous(tmp_path, monkeypatch):
    """prev < 50 symbols never arms the ratio guard (tiny test
    universes shrink freely)."""
    monkeypatch.delenv("BOWAKA_UNIVERSE_ALLOW_SHRINK", raising=False)
    cfg = _cfg(tmp_path)
    _write_prev_snapshot(tmp_path, 40)
    assert ub._refuse_suspicious_shrink(_rows(5), cfg) is None


def test_shrink_guard_env_override_allows_write(tmp_path, monkeypatch, caplog):
    import logging
    monkeypatch.setenv("BOWAKA_UNIVERSE_ALLOW_SHRINK", "1")
    cfg = _cfg(tmp_path)
    _write_prev_snapshot(tmp_path, 600)
    with caplog.at_level(logging.WARNING):
        assert ub._refuse_suspicious_shrink(_rows(200), cfg) is None
    assert any("shrink override" in r.message for r in caplog.records)


def test_build_and_write_exit6_leaves_snapshot_untouched(tmp_path, monkeypatch):
    """End-to-end: a 2-symbol build against an existing 600-symbol
    snapshot exits 6 with the snapshot byte-identical."""
    monkeypatch.delenv("BOWAKA_UNIVERSE_ALLOW_SHRINK", raising=False)
    cfg = _cfg(tmp_path)
    snap = _write_prev_snapshot(tmp_path, 600)
    before = snap.read_bytes()
    assets = [
        {"symbol": "FOO", "exchange": "NASDAQ", "name": "Foo Inc",
         "asset_class": "us_equity", "tradable": True, "status": "active"},
        {"symbol": "BAR", "exchange": "NYSE", "name": "Bar Holdings",
         "asset_class": "us_equity", "tradable": True, "status": "active"},
    ]

    def bars_supplier(symbol):
        rows = []
        for i in range(25):
            c = 5.0 + i * 0.05
            rows.append({
                "timestamp": datetime(2026, 4, 1, tzinfo=timezone.utc)
                             + timedelta(days=i),
                "open": c - 0.05, "high": c + 0.10,
                "low":  c - 0.10, "close": c, "volume": 500_000,
            })
        return pd.DataFrame(rows)

    rc = ub.build_and_write(cfg, lambda: assets, bars_supplier)
    assert rc == 6
    assert snap.read_bytes() == before
    assert not (tmp_path / "daily_feature_cache.parquet").exists()


def test_build_and_write_no_previous_snapshot_writes(tmp_path, monkeypatch):
    monkeypatch.delenv("BOWAKA_UNIVERSE_ALLOW_SHRINK", raising=False)
    cfg = _cfg(tmp_path)
    assets = [
        {"symbol": "FOO", "exchange": "NASDAQ", "name": "Foo Inc",
         "asset_class": "us_equity", "tradable": True, "status": "active"},
    ]

    def bars_supplier(symbol):
        rows = []
        for i in range(25):
            c = 5.0 + i * 0.05
            rows.append({
                "timestamp": datetime(2026, 4, 1, tzinfo=timezone.utc)
                             + timedelta(days=i),
                "open": c - 0.05, "high": c + 0.10,
                "low":  c - 0.10, "close": c, "volume": 500_000,
            })
        return pd.DataFrame(rows)

    rc = ub.build_and_write(cfg, lambda: assets, bars_supplier)
    assert rc == 0
    doc = json.loads((tmp_path / "universe_snapshot.json").read_text())
    assert doc["symbols_count"] == 1


# ---- fix Phase 8: stale asset-cache warning ---------------------------------------


def test_stale_asset_cache_warns(tmp_path, monkeypatch, caplog):
    import logging
    import os as _os
    import time as _time

    cache = tmp_path / "universe_us_equity.json"
    cache.write_text(json.dumps({
        "symbols": [], "exchanges": {}, "asset_meta": {},
    }), encoding="utf-8")
    ten_days_ago = _time.time() - 10 * 86400
    _os.utime(cache, (ten_days_ago, ten_days_ago))

    monkeypatch.setenv("OPENALGO_API_KEY", "test-key")
    cfg = _cfg(tmp_path)
    cfg["live_fetch"] = {"asset_list_cache": str(cache),
                          "fetch_concurrency": 1}
    asset_supplier, _bars, http = ub._live_suppliers(cfg)
    try:
        with caplog.at_level(logging.WARNING):
            rows = asset_supplier()
    finally:
        http.close()
    assert rows == []
    assert any("days old" in r.message for r in caplog.records)


def test_fresh_asset_cache_no_warning(tmp_path, monkeypatch, caplog):
    import logging

    cache = tmp_path / "universe_us_equity.json"
    cache.write_text(json.dumps({
        "symbols": [], "exchanges": {}, "asset_meta": {},
    }), encoding="utf-8")
    monkeypatch.setenv("OPENALGO_API_KEY", "test-key")
    cfg = _cfg(tmp_path)
    cfg["live_fetch"] = {"asset_list_cache": str(cache),
                          "fetch_concurrency": 1}
    asset_supplier, _bars, http = ub._live_suppliers(cfg)
    try:
        with caplog.at_level(logging.WARNING):
            asset_supplier()
    finally:
        http.close()
    assert not any("days old" in r.message for r in caplog.records)
