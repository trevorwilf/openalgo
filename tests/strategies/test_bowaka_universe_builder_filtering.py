"""Phase 2 — universe-builder gate tests.

Pins the "no signal gates in the universe layer" contract: the
universe builder should keep names that would FAIL v1's
rvol/range/close_location thresholds, because those gates move
into the intraday scanner.
"""
from __future__ import annotations

import pandas as pd
import pytest

import bowaka_universe_builder as ub


def _cfg() -> dict:
    return {
        "universe": {
            "allowed_exchanges": ["NASDAQ", "NYSE", "AMEX", "ARCA", "BATS"],
            "exclude_otc": True,
            "exclude_etf": True,
            "exclude_leveraged_etp": True,
            "exclude_inverse_etp": True,
            "exclude_etn": True,
            "exclude_warrants": True,
            "exclude_units": True,
            "exclude_rights": True,
            "exclude_preferred": True,
            "ticker_blocklist": ["BLOCKED"],
            "price_min": 1.0, "price_max": 20.0,
            "avg_dollar_volume_min": 250_000,
        },
        "instrument_rules": {
            "ticker_blocklist": [],
            "name_keywords": {
                "leveraged": ["2X", "3X", "BULL"],
                "inverse": ["INVERSE", "SHORT"],
                "etn": ["NOTES"],
                "warrant": ["WARRANT"],
                "unit": ["UNIT"],
                "right": ["RIGHT"],
                "preferred": ["PREFERRED"],
                "etf": ["ETF", "INDEX FUND"],
            },
        },
        "historical_features": {
            "lookback_days": 20, "atr_days": 14,
            "ema_days": 10, "ema_slope_lookback": 3,
        },
    }


def _bars(symbol: str, *, base: float = 5.0,
          vol: float = 1_000_000.0) -> pd.DataFrame:
    rows = []
    from datetime import datetime, timedelta, timezone
    for i in range(25):
        c = base + i * 0.05
        rows.append({
            "timestamp": datetime(2026, 4, 1, tzinfo=timezone.utc)
                         + timedelta(days=i),
            "open": c - 0.05, "high": c + 0.10,
            "low":  c - 0.10, "close": c, "volume": vol,
        })
    return pd.DataFrame(rows)


def _build(cfg, assets, bars_for=None):
    bars_for = bars_for or (lambda s: _bars(s))
    snap, cache, meta = ub.build_universe(
        cfg, asset_supplier=lambda: assets,
        bars_supplier=bars_for,
    )
    return snap, cache, meta


# ---- exchange / OTC --------------------------------------------------


def test_otc_excluded():
    cfg = _cfg()
    snap, _, _ = _build(cfg, [
        {"symbol": "AAA", "exchange": "OTC", "name": "AAA Corp",
         "asset_class": "us_equity", "tradable": True, "status": "active"},
    ])
    assert all(r["symbol"] != "AAA" for r in snap)


def test_only_allowed_exchanges_kept():
    cfg = _cfg()
    snap, _, _ = _build(cfg, [
        {"symbol": "AAA", "exchange": "TSX", "name": "AAA",
         "asset_class": "us_equity", "tradable": True, "status": "active"},
        {"symbol": "BBB", "exchange": "NASDAQ", "name": "BBB",
         "asset_class": "us_equity", "tradable": True, "status": "active"},
    ])
    symbols = {r["symbol"] for r in snap}
    assert "BBB" in symbols
    assert "AAA" not in symbols


# ---- instrument-class exclusions -------------------------------------


def test_etf_etn_leveraged_inverse_excluded():
    cfg = _cfg()
    snap, _, _ = _build(cfg, [
        {"symbol": "SPYY", "exchange": "ARCA", "name": "Vanguard SPYY ETF",
         "asset_class": "us_equity", "tradable": True, "status": "active"},
        {"symbol": "NOTE", "exchange": "NYSE", "name": "DB AGRICULTURE NOTES",
         "asset_class": "us_equity", "tradable": True, "status": "active"},
        {"symbol": "TSLU", "exchange": "NASDAQ",
         "name": "Direxion 2X TSLA BULL",
         "asset_class": "us_equity", "tradable": True, "status": "active"},
        {"symbol": "SQQ",  "exchange": "NASDAQ",
         "name": "ProShares INVERSE QQQ",
         "asset_class": "us_equity", "tradable": True, "status": "active"},
    ])
    kept = {r["symbol"] for r in snap}
    for excluded in ("SPYY", "NOTE", "TSLU", "SQQ"):
        assert excluded not in kept


def test_ticker_blocklist_enforced():
    cfg = _cfg()
    snap, _, _ = _build(cfg, [
        {"symbol": "BLOCKED", "exchange": "NASDAQ", "name": "Blocked Inc",
         "asset_class": "us_equity", "tradable": True, "status": "active"},
    ])
    assert all(r["symbol"] != "BLOCKED" for r in snap)


def test_warrants_units_rights_preferred_excluded():
    cfg = _cfg()
    snap, _, _ = _build(cfg, [
        {"symbol": "AAA",  "exchange": "NYSE", "name": "AAA Corp WARRANT",
         "asset_class": "us_equity", "tradable": True, "status": "active"},
        {"symbol": "BBB",  "exchange": "NYSE", "name": "BBB Holdings UNIT",
         "asset_class": "us_equity", "tradable": True, "status": "active"},
        {"symbol": "CCC",  "exchange": "NYSE", "name": "CCC RIGHT",
         "asset_class": "us_equity", "tradable": True, "status": "active"},
        {"symbol": "DDD",  "exchange": "NYSE", "name": "DDD PREFERRED",
         "asset_class": "us_equity", "tradable": True, "status": "active"},
    ])
    kept = {r["symbol"] for r in snap}
    assert kept == set()


# ---- price / ADV bands -----------------------------------------------


def test_price_band_min_max():
    cfg = _cfg()
    # bar baselines feed prior_close - too low symbol uses small base.
    # _bars adds +0.05 per row × 24 rows = +1.20 to base, so we need
    # the LOW base low enough that prior_close (= last row close)
    # still lands under price_min=1.0.
    snap, _, _ = _build(cfg, [
        {"symbol": "LOW",  "exchange": "NASDAQ", "name": "Penny Inc",
         "asset_class": "us_equity", "tradable": True, "status": "active"},
        {"symbol": "MID",  "exchange": "NASDAQ", "name": "Mid Inc",
         "asset_class": "us_equity", "tradable": True, "status": "active"},
        {"symbol": "HIGH", "exchange": "NASDAQ", "name": "Expensive Inc",
         "asset_class": "us_equity", "tradable": True, "status": "active"},
    ], bars_for=lambda s: _bars(
        s,
        base={"LOW": -0.50, "MID": 7.0, "HIGH": 30.0}[s],
    ))
    kept = {r["symbol"] for r in snap}
    assert "MID" in kept
    assert "LOW" not in kept
    assert "HIGH" not in kept


def test_avg_dollar_volume_min_enforced():
    cfg = _cfg()
    snap, _, _ = _build(cfg, [
        {"symbol": "THIN", "exchange": "NASDAQ", "name": "Thin Trader Inc",
         "asset_class": "us_equity", "tradable": True, "status": "active"},
        {"symbol": "THICK", "exchange": "NASDAQ", "name": "Thick Trader Inc",
         "asset_class": "us_equity", "tradable": True, "status": "active"},
    ], bars_for=lambda s: _bars(
        s,
        vol=1000.0 if s == "THIN" else 1_000_000.0,
    ))
    kept = {r["symbol"] for r in snap}
    assert "THICK" in kept
    assert "THIN" not in kept


# ---- the headline contract: no signal gates here ---------------------


def test_no_signal_gates_applied():
    """A symbol that would FAIL v1's RVOL / range / close_location
    thresholds MUST still pass the universe layer. v2 moves those
    gates into the intraday scanner."""
    cfg = _cfg()
    # Provide a symbol with flat daily bars (no range, RVOL=1).
    def flat_bars(_):
        rows = []
        from datetime import datetime, timedelta, timezone
        for i in range(25):
            rows.append({
                "timestamp": datetime(2026, 4, 1, tzinfo=timezone.utc)
                             + timedelta(days=i),
                "open": 5.0, "high": 5.0, "low": 5.0, "close": 5.0,
                "volume": 500_000,
            })
        return pd.DataFrame(rows)

    snap, _, _ = _build(cfg, [
        {"symbol": "FLAT", "exchange": "NASDAQ",
         "name": "Flat Trader Inc",
         "asset_class": "us_equity", "tradable": True, "status": "active"},
    ], bars_for=flat_bars)
    kept = {r["symbol"] for r in snap}
    assert "FLAT" in kept, (
        "universe layer must NOT apply v1 signal gates. v2 moves them "
        "into the intraday scanner."
    )
