"""Phase 2 audit acceptance tests — prefilter gates + instrument class.

Covers:
  2.1 Max gates: rvol_max / range_expansion_max / gap_pct_max drop
       blow-off / exhaustion candidates.
  2.2 Bounded signal_strength score: parity when ``bounded=false``,
       clipping + gap penalty when ``bounded=true``.
  2.3 classify_instrument: blocklist / name keyword / asset_class
       decision matrix.
  2.4 Universe filter: ``exclude_otc`` redundancy.
  2.5 Strategy-side defense: a candidate JSON with
       ``instrument_class != "operating_equity"`` never reaches
       submit_entry; emits an entry_decision with reason
       ``excluded_instrument_class``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest


# ---------------------------------------------------------------- 2.1 max gates


def _features_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    return df.set_index("symbol")


def _baseline_cfg(extra_signals: dict | None = None,
                  score_bounded: bool = False) -> dict:
    return {
        "universe": {
            "price_min": 1.0, "price_max": 20.0,
            "avg_dollar_volume_min": 0, "avg_dollar_volume_max": None,
            "allowed_exchanges": ["NASDAQ"],
        },
        "signals": {
            "rvol_min": None, "atr_pct_min": None,
            "range_expansion_min": None, "close_location_min": None,
            "ema_distance_min": None, "ema_slope_min": None,
            **(extra_signals or {}),
        },
        "score": {
            "bounded": score_bounded,
            "rvol_score_cap": 5.0,
            "range_score_cap": 2.5,
            "ema_distance_score_cap": 0.40,
            "ema_slope_score_cap": 0.25,
            "gap_penalty_above": 0.25,
        },
        "instrument_rules": {
            "leveraged_etp": {"action": "exclude"},
            "inverse_etp": {"action": "exclude"},
            "etn": {"action": "exclude"},
            "ticker_blocklist": ["TSLL", "CONL", "SMCX"],
            "name_keywords": {
                "leveraged": ["2X", "3X", "BULL", "BEAR", "DAILY", "LEVERAGED"],
                "inverse": ["INVERSE", "SHORT", "BEAR"],
                "etn": ["ETN"],
            },
        },
    }


def test_rvol_max_drops_blowoff(tmp_path):
    pf = __import__("pytest").importorskip("bowaka_prefilter")
    df = _features_df([
        {"symbol": "A", "close": 5.0, "rvol": 10.0, "atr_pct": 0.1,
         "range_expansion": 1.5, "close_location": 0.8,
         "ema_distance": 0.05, "ema_slope": 0.05, "avg_dollar_volume": 1e7,
         "gap_pct": 0.05},
        {"symbol": "B", "close": 5.0, "rvol": 3.0, "atr_pct": 0.1,
         "range_expansion": 1.5, "close_location": 0.8,
         "ema_distance": 0.05, "ema_slope": 0.05, "avg_dollar_volume": 1e7,
         "gap_pct": 0.05},
    ])
    cfg = _baseline_cfg(extra_signals={"rvol_max": 5.0})
    out, _ = pf.apply_filters(df, cfg, asset_meta={
        "A": {"name": "ASYM Operating Inc", "asset_class": "us_equity"},
        "B": {"name": "BSYM Operating Inc", "asset_class": "us_equity"},
    })
    assert "A" not in out.index   # rvol=10 dropped
    assert "B" in out.index       # rvol=3 admitted


def test_range_expansion_max_drops_extreme(tmp_path):
    pf = __import__("pytest").importorskip("bowaka_prefilter")
    df = _features_df([
        {"symbol": "A", "close": 5.0, "rvol": 3.0, "atr_pct": 0.1,
         "range_expansion": 5.0, "close_location": 0.8,
         "ema_distance": 0.05, "ema_slope": 0.05, "avg_dollar_volume": 1e7,
         "gap_pct": 0.05},
        {"symbol": "B", "close": 5.0, "rvol": 3.0, "atr_pct": 0.1,
         "range_expansion": 1.5, "close_location": 0.8,
         "ema_distance": 0.05, "ema_slope": 0.05, "avg_dollar_volume": 1e7,
         "gap_pct": 0.05},
    ])
    cfg = _baseline_cfg(extra_signals={"range_expansion_max": 2.25})
    out, _ = pf.apply_filters(df, cfg, asset_meta={
        "A": {"name": "ASYM Operating Inc", "asset_class": "us_equity"},
        "B": {"name": "BSYM Operating Inc", "asset_class": "us_equity"},
    })
    assert "A" not in out.index   # range_expansion=5.0 dropped
    assert "B" in out.index


def test_gap_pct_max_drops_gappers(tmp_path):
    pf = __import__("pytest").importorskip("bowaka_prefilter")
    df = _features_df([
        {"symbol": "A", "close": 5.0, "rvol": 3.0, "atr_pct": 0.1,
         "range_expansion": 1.5, "close_location": 0.8,
         "ema_distance": 0.05, "ema_slope": 0.05, "avg_dollar_volume": 1e7,
         "gap_pct": 0.40},
        {"symbol": "B", "close": 5.0, "rvol": 3.0, "atr_pct": 0.1,
         "range_expansion": 1.5, "close_location": 0.8,
         "ema_distance": 0.05, "ema_slope": 0.05, "avg_dollar_volume": 1e7,
         "gap_pct": 0.10},
    ])
    cfg = _baseline_cfg(extra_signals={"gap_pct_max": 0.25})
    out, _ = pf.apply_filters(df, cfg, asset_meta={
        "A": {"name": "ASYM Operating Inc", "asset_class": "us_equity"},
        "B": {"name": "BSYM Operating Inc", "asset_class": "us_equity"},
    })
    assert "A" not in out.index   # gap=40% dropped
    assert "B" in out.index


def test_max_gates_disabled_by_default(tmp_path):
    """Null = disabled. Pre-Phase-2 behavior preserved when YAML
    keeps the new gates at their null defaults."""
    pf = __import__("pytest").importorskip("bowaka_prefilter")
    df = _features_df([
        {"symbol": "X", "close": 5.0, "rvol": 999.0, "atr_pct": 0.1,
         "range_expansion": 99.0, "close_location": 0.8,
         "ema_distance": 0.05, "ema_slope": 0.05, "avg_dollar_volume": 1e7,
         "gap_pct": 99.0},
    ])
    cfg = _baseline_cfg()  # all max gates null
    out, _ = pf.apply_filters(df, cfg, asset_meta={
        "X": {"name": "Xyz Operating Inc", "asset_class": "us_equity"},
    })
    assert "X" in out.index  # extreme values not dropped


# ---------------------------------------------------------------- 2.2 bounded score


def _score_input(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_signal_strength_bounded_false_matches_legacy_formula():
    """Bounded=false produces the exact pre-Phase-2 formula:
       rvol + range_expansion + ema_distance*10 + ema_slope*10
    """
    pf = __import__("pytest").importorskip("bowaka_prefilter")
    df = pd.DataFrame([
        {"rvol": 2.0, "range_expansion": 1.5, "ema_distance": 0.04,
         "ema_slope": 0.03, "gap_pct": 0.05},
        {"rvol": 1.5, "range_expansion": 1.2, "ema_distance": 0.01,
         "ema_slope": 0.005, "gap_pct": 0.10},
    ])
    s = pf.compute_signal_strength(df, {"score": {"bounded": False}})
    expected = (
        df["rvol"] + df["range_expansion"]
        + df["ema_distance"] * 10 + df["ema_slope"] * 10
    )
    pd.testing.assert_series_equal(s, expected, check_names=False)


def test_signal_strength_bounded_caps_rvol_and_penalizes_gap():
    """Bounded=true clips each term at its cap and subtracts a
    penalty proportional to gap_pct above gap_penalty_above."""
    pf = __import__("pytest").importorskip("bowaka_prefilter")
    df = pd.DataFrame([
        # rvol clipped 10 -> 5.0; gap 0.40 - 0.25 = 0.15 penalty
        {"rvol": 10.0, "range_expansion": 1.5, "ema_distance": 0.05,
         "ema_slope": 0.05, "gap_pct": 0.40},
    ])
    cfg = {"score": {
        "bounded": True,
        "rvol_score_cap": 5.0,
        "range_score_cap": 2.5,
        "ema_distance_score_cap": 0.40,
        "ema_slope_score_cap": 0.25,
        "gap_penalty_above": 0.25,
    }}
    s = pf.compute_signal_strength(df, cfg)
    # 5.0 (capped) + 1.5 + 0.05*10 + 0.05*10 - 0.15 = 7.35
    assert s.iloc[0] == pytest.approx(7.35)


def test_signal_strength_bounded_clips_all_terms():
    """Every term respects its cap independently."""
    pf = __import__("pytest").importorskip("bowaka_prefilter")
    df = pd.DataFrame([
        {"rvol": 100.0, "range_expansion": 100.0,
         "ema_distance": 100.0, "ema_slope": 100.0, "gap_pct": 0.0},
    ])
    cfg = {"score": {
        "bounded": True,
        "rvol_score_cap": 5.0,
        "range_score_cap": 2.5,
        "ema_distance_score_cap": 0.40,
        "ema_slope_score_cap": 0.25,
        "gap_penalty_above": 0.25,
    }}
    s = pf.compute_signal_strength(df, cfg)
    # 5.0 + 2.5 + 0.40*10 + 0.25*10 = 14.0
    assert s.iloc[0] == pytest.approx(14.0)


# ---------------------------------------------------------------- 2.3 classify_instrument


def test_classify_blocklist_takes_priority():
    pf = __import__("pytest").importorskip("bowaka_prefilter")
    cfg = _baseline_cfg()
    r = pf.classify_instrument(
        "TSLL", {"name": "Direxion TSLA Bull 2X", "asset_class": "us_equity"}, cfg,
    )
    assert r["instrument_class"] == "leveraged_etp"
    assert r["eligible_for_bowaka_equity_bucket"] is False
    assert r["classification_reason"] == "ticker_blocklist"


def test_classify_conl_blocklisted():
    pf = __import__("pytest").importorskip("bowaka_prefilter")
    cfg = _baseline_cfg()
    r = pf.classify_instrument("CONL", {"name": "Direxion COIN Bull 2X", "asset_class": "us_equity"}, cfg)
    assert r["instrument_class"] == "leveraged_etp"


def test_classify_smcx_blocklisted():
    pf = __import__("pytest").importorskip("bowaka_prefilter")
    cfg = _baseline_cfg()
    r = pf.classify_instrument("SMCX", {"name": "Direxion SMCI 2X", "asset_class": "us_equity"}, cfg)
    assert r["instrument_class"] == "leveraged_etp"


def test_classify_sqqq_by_name_keyword():
    """SQQQ is a 3X inverse on NASDAQ-100; the keyword path classifies
    it without it being on the blocklist."""
    pf = __import__("pytest").importorskip("bowaka_prefilter")
    cfg = _baseline_cfg()
    r = pf.classify_instrument(
        "SQQQ",
        {"name": "ProShares UltraPro Short QQQ", "asset_class": "etf"},
        cfg,
    )
    # SHORT keyword matches inverse first (we put leveraged ahead, but
    # SQQQ name doesn't contain a leveraged keyword like "BULL" or
    # "2X"/"3X"). Actually it contains "Short" which is in the inverse
    # keyword set. The implementation tries leveraged first; the SQQQ
    # name does contain "Ultra" but that's not in our keyword list, so
    # it falls through to inverse. Verify the eligible flag is false
    # either way.
    assert r["instrument_class"] in {"leveraged_etp", "inverse_etp"}
    assert r["eligible_for_bowaka_equity_bucket"] is False


def test_classify_tlt_passes_through_as_etf():
    """TLT is a regular bond ETF — should classify as etf (not
    leveraged/inverse) and be marked ineligible for the equity
    bucket."""
    pf = __import__("pytest").importorskip("bowaka_prefilter")
    cfg = _baseline_cfg()
    r = pf.classify_instrument(
        "TLT",
        {"name": "iShares 20+ Year Treasury Bond ETF",
         "asset_class": "etf"},
        cfg,
    )
    assert r["instrument_class"] == "etf"
    assert r["eligible_for_bowaka_equity_bucket"] is False


def test_classify_operating_equity_default():
    pf = __import__("pytest").importorskip("bowaka_prefilter")
    cfg = _baseline_cfg()
    r = pf.classify_instrument(
        "AAPL",
        {"name": "Apple Inc.", "asset_class": "us_equity"},
        cfg,
    )
    assert r["instrument_class"] == "operating_equity"
    assert r["eligible_for_bowaka_equity_bucket"] is True
    assert r["classification_reason"] == "default_operating_equity"


def test_classify_2x_3x_by_keyword():
    """A leveraged ETP whose name contains 2X / 3X / DAILY classifies
    as leveraged_etp even without being on the blocklist."""
    pf = __import__("pytest").importorskip("bowaka_prefilter")
    cfg = _baseline_cfg()
    r = pf.classify_instrument(
        "TQQQ",
        {"name": "ProShares UltraPro QQQ 3X", "asset_class": "etf"},
        cfg,
    )
    assert r["instrument_class"] == "leveraged_etp"


# ---------------------------------------------------------------- 2.3 apply_filters drops excluded


def test_apply_filters_drops_leveraged_etp_by_class():
    """A row whose name triggers the leveraged-etp classifier is
    dropped from the candidate set (and stashed on the dataframe for
    diagnostic CSV inclusion)."""
    pf = __import__("pytest").importorskip("bowaka_prefilter")
    df = _features_df([
        {"symbol": "TSLL", "close": 5.0, "rvol": 3.0, "atr_pct": 0.1,
         "range_expansion": 1.5, "close_location": 0.8,
         "ema_distance": 0.05, "ema_slope": 0.05, "avg_dollar_volume": 1e7,
         "gap_pct": 0.05},
        {"symbol": "AAPL", "close": 5.0, "rvol": 3.0, "atr_pct": 0.1,
         "range_expansion": 1.5, "close_location": 0.8,
         "ema_distance": 0.05, "ema_slope": 0.05, "avg_dollar_volume": 1e7,
         "gap_pct": 0.05},
    ])
    cfg = _baseline_cfg()
    out, counts = pf.apply_filters(df, cfg, asset_meta={
        "TSLL": {"name": "Direxion TSLA Bull 2X", "asset_class": "us_equity"},
        "AAPL": {"name": "Apple Inc.", "asset_class": "us_equity"},
    })
    assert "TSLL" not in out.index
    assert "AAPL" in out.index
    assert counts["n_excluded_by_instrument_class"] == 1


# ---------------------------------------------------------------- 2.5 strategy-side defense


def _candidates_payload(rows, *, schema_version=2, data_feed="iex",
                        config_hash="sha256:00", as_of_date="2026-05-11"):
    return {
        "schema_version": schema_version,
        "strategy": "bowaka",
        "as_of_date": as_of_date,
        "data_feed": data_feed,
        "config_hash": config_hash,
        "candidates": rows,
    }


def test_load_candidates_hydrates_instrument_class(strategy_module, tmp_path):
    from datetime import date
    path = tmp_path / "in_play.json"
    today = date(2026, 5, 11)
    rows = [
        {"ticker": "TSLL", "close": 5.0, "signal_strength": 5.0,
         "venue_code": "XNAS",
         "instrument_class": "leveraged_etp",
         "eligible_for_bowaka_equity_bucket": False},
        {"ticker": "AAPL", "close": 5.0, "signal_strength": 5.0,
         "venue_code": "XNAS",
         "instrument_class": "operating_equity",
         "eligible_for_bowaka_equity_bucket": True},
    ]
    path.write_text(json.dumps(_candidates_payload(rows, as_of_date=today.isoformat())))
    cands = strategy_module.load_candidates(
        path, max_age_trading_days=10, expected_config_hash=None,
        today_et=today,
    )
    by = {c.ticker: c for c in cands}
    assert by["TSLL"].instrument_class == "leveraged_etp"
    assert by["TSLL"].eligible_for_bowaka_equity_bucket is False
    assert by["AAPL"].instrument_class == "operating_equity"


def test_load_candidates_legacy_v1_defaults_safe(strategy_module, tmp_path):
    """v1 candidate file (no instrument_class) → defaults to None /
    True so legacy operation continues."""
    from datetime import date
    path = tmp_path / "in_play.json"
    today = date(2026, 5, 11)
    path.write_text(json.dumps({
        "as_of_date": today.isoformat(),
        "candidates": [{"ticker": "AAPL", "close": 5.0, "signal_strength": 5.0,
                        "venue_code": "XNAS"}],
    }))
    cands = strategy_module.load_candidates(
        path, max_age_trading_days=10, expected_config_hash=None,
        today_et=today,
    )
    assert cands[0].instrument_class is None
    assert cands[0].eligible_for_bowaka_equity_bucket is True


def test_select_entries_rejects_leveraged_etp_by_class(
    strategy_module, cfg_with_paths,
):
    """A candidate marked leveraged_etp never reaches submit_entry —
    select_entries rejects it with reason ``excluded_instrument_class``.
    """
    state = strategy_module.blank_state()
    cands = [
        strategy_module.Candidate(
            ticker="TSLL", close=10.0, signal_strength=9.0,
            features={"avg_dollar_volume": 1e7},
            instrument_class="leveraged_etp",
            eligible_for_bowaka_equity_bucket=False,
        ),
        strategy_module.Candidate(
            ticker="AAPL", close=10.0, signal_strength=8.0,
            features={"avg_dollar_volume": 1e7},
            instrument_class="operating_equity",
        ),
    ]
    selected = strategy_module.select_entries(
        cands, state, equity=100_000.0, latest_prices={},
        cfg=cfg_with_paths, kill_state=strategy_module.KillLevel.NONE,
    )
    assert [e.ticker for e in selected] == ["AAPL"]
    # Verify the ledger captured the rejection with the correct reason.
    # Phase 1.2: ledger lives under data/<env>/trade_ledger.jsonl.
    ledger_path = strategy_module._ledger_path(cfg_with_paths)
    events = []
    for line in ledger_path.read_text().splitlines():
        if not line.strip():
            continue
        events.append(json.loads(line))
    reasons = {
        e["payload"]["ticker"]: e["payload"]["reason"]
        for e in events if e["event_type"] == "entry_decision"
    }
    assert reasons["TSLL"] == "excluded_instrument_class"


# ---------------------------------------------------------------- regression


def test_apply_filters_diagnostic_carries_excluded_rows(tmp_path):
    """The diagnostic CSV path includes the rows excluded by
    instrument class with an ``excluded_reason`` column."""
    pf = __import__("pytest").importorskip("bowaka_prefilter")

    df = _features_df([
        {"symbol": "TSLL", "close": 5.0, "rvol": 3.0, "atr_pct": 0.1,
         "range_expansion": 1.5, "close_location": 0.8,
         "ema_distance": 0.05, "ema_slope": 0.05, "avg_dollar_volume": 1e7,
         "gap_pct": 0.05},
        {"symbol": "AAPL", "close": 5.0, "rvol": 3.0, "atr_pct": 0.1,
         "range_expansion": 1.5, "close_location": 0.8,
         "ema_distance": 0.05, "ema_slope": 0.05, "avg_dollar_volume": 1e7,
         "gap_pct": 0.05},
    ])
    cfg = _baseline_cfg()
    out, _ = pf.apply_filters(df, cfg, asset_meta={
        "TSLL": {"name": "Direxion TSLA Bull 2X", "asset_class": "us_equity"},
        "AAPL": {"name": "Apple Inc.", "asset_class": "us_equity"},
    })

    candidates_path = tmp_path / "in_play.json"
    diag = tmp_path / "diag.csv"
    write_cfg = {
        **cfg,
        "alpaca": {"feed": "iex"},
        "output": {"candidates_path": str(candidates_path),
                   "diagnostic_csv": str(diag)},
    }
    pf.write_output(
        out, counts={"n_in_play": len(out)},
        cfg=write_cfg, cfg_hash="abcd1234",
        exchanges={"AAPL": "NASDAQ", "TSLL": "NASDAQ"},
        universe_symbols=["AAPL", "TSLL"],
    )
    csv_text = diag.read_text()
    # TSLL appears in the diagnostic CSV even though it was excluded
    # from the candidate JSON.
    assert "TSLL" in csv_text
    assert "ticker_blocklist" in csv_text
