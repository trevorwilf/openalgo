"""Bowaka prefilter unit tests.

Focused on the parts that don't need a live Alpaca client: write_output
(candidate JSON + as_of_date derivation), the listing-exchange ->
venue MIC mapping, and the universe-cache shape.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def prefilter_module():
    """Import the prefilter as a module so tests can call its
    functions directly. Lives at ``strategies/scripts/`` so we add
    that to sys.path lazily here (matches the conftest pattern used
    for the strategy)."""
    import importlib
    import sys
    p = Path(__file__).resolve().parents[2] / "strategies" / "scripts"
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
    return importlib.import_module("bowaka_prefilter")


def _candidates_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df.set_index("ticker", inplace=True)
    return df


def test_write_output_uses_explicit_as_of_date_override(
    prefilter_module, tmp_path,
):
    """Item 8 (Critical #5): the prefilter accepts an explicit
    as_of_date_override (derived from the latest bar timestamp) and
    uses it instead of the wall-clock run date. Holiday / weekend
    runs would otherwise stamp today as as_of even when the bars are
    from an earlier session."""
    out_path = tmp_path / "in_play.json"
    cfg = {"output": {"candidates_path": str(out_path)}}
    df = _candidates_df([
        {"ticker": "AAPL", "close": 150.0, "rvol": 2.0, "atr_pct": 0.08,
         "range_expansion": 1.4, "gap_pct": 0.02, "close_location": 0.85,
         "ema_distance": 0.05, "ema_slope": 0.02, "avg_dollar_volume": 1e6,
         "signal_strength": 9.0},
    ])
    prefilter_module.write_output(
        df, {"n_universe_with_features": 1, "n_passed_universe_gates": 1,
             "n_in_play": 1},
        cfg, "abcd1234",
        exchanges={"AAPL": "NASDAQ"},
        as_of_date_override="2026-05-04",
    )
    payload = json.loads(out_path.read_text())
    assert payload["as_of_date"] == "2026-05-04"


def test_write_output_falls_back_to_run_date_when_no_override(
    prefilter_module, tmp_path,
):
    """Backward compat: with no override the prefilter still stamps
    the wall-clock date so callers that haven't been threaded through
    keep working."""
    from datetime import date
    from datetime import datetime, timezone
    out_path = tmp_path / "in_play.json"
    cfg = {"output": {"candidates_path": str(out_path)}}
    df = _candidates_df([
        {"ticker": "AAPL", "close": 150.0, "rvol": 2.0, "atr_pct": 0.08,
         "range_expansion": 1.4, "gap_pct": 0.02, "close_location": 0.85,
         "ema_distance": 0.05, "ema_slope": 0.02, "avg_dollar_volume": 1e6,
         "signal_strength": 9.0},
    ])
    prefilter_module.write_output(
        df, {"n_universe_with_features": 1, "n_passed_universe_gates": 1,
             "n_in_play": 1},
        cfg, "abcd1234",
        exchanges={"AAPL": "NASDAQ"},
    )
    payload = json.loads(out_path.read_text())
    today_iso = datetime.now(timezone.utc).date().isoformat()
    assert payload["as_of_date"] == today_iso


def test_write_output_emits_per_row_venue_code(prefilter_module, tmp_path):
    """Item 2 + Item 8 sanity: each candidate row carries the
    venue_code and exchange the strategy will read."""
    out_path = tmp_path / "in_play.json"
    cfg = {"output": {"candidates_path": str(out_path)}}
    df = _candidates_df([
        {"ticker": "AAPL", "close": 150.0, "rvol": 2.0, "atr_pct": 0.08,
         "range_expansion": 1.4, "gap_pct": 0.02, "close_location": 0.85,
         "ema_distance": 0.05, "ema_slope": 0.02, "avg_dollar_volume": 1e6,
         "signal_strength": 9.0},
        {"ticker": "CAT", "close": 80.0, "rvol": 2.0, "atr_pct": 0.08,
         "range_expansion": 1.4, "gap_pct": 0.02, "close_location": 0.85,
         "ema_distance": 0.05, "ema_slope": 0.02, "avg_dollar_volume": 5e6,
         "signal_strength": 6.0},
    ])
    prefilter_module.write_output(
        df, {"n_universe_with_features": 2, "n_passed_universe_gates": 2,
             "n_in_play": 2},
        cfg, "abcd1234",
        exchanges={"AAPL": "NASDAQ", "CAT": "NYSE"},
        as_of_date_override="2026-05-05",
    )
    rows = {r["ticker"]: r for r in json.loads(out_path.read_text())["candidates"]}
    assert rows["AAPL"]["venue_code"] == "XNAS"
    assert rows["AAPL"]["exchange"] == "NASDAQ"
    assert rows["CAT"]["venue_code"] == "XNYS"
    assert rows["CAT"]["exchange"] == "NYSE"


def test_alpaca_exchange_to_mic_folds_amex_to_xnys(prefilter_module):
    """AMEX listings fold to XNYS to match OpenAlgo's Alpaca plugin —
    Alpaca's quote/bar/order adapters only accept the four canonical
    venues {XNAS, XNYS, ARCX, BATS}."""
    m = prefilter_module.ALPACA_EXCHANGE_TO_MIC
    assert m["NASDAQ"] == "XNAS"
    assert m["NYSE"] == "XNYS"
    assert m["AMEX"] == "XNYS"
    assert m["ARCA"] == "ARCX"
    assert m["BATS"] == "BATS"
