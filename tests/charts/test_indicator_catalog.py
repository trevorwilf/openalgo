"""Phase 5 — indicator catalog v1 contains all 22 entries."""

from __future__ import annotations

from services.charts.indicator_catalog import CATALOG, get_indicator, list_keys


EXPECTED_KEYS = {
    "SMA",
    "EMA",
    "WMA",
    "VWAP",
    "RSI",
    "MACD",
    "BB",
    "STOCH",
    "ATR",
    "ADX",
    "OBV",
    "CCI",
    "WILLIAMS_R",
    "ICHIMOKU",
    "PSAR",
    "DONCHIAN",
    "KELTNER",
    "MFI",
    "ROC",
    "STOCH_RSI",
    "SUPERTREND",
    "HEIKIN_ASHI",
}


def test_catalog_size_is_22():
    assert len(CATALOG) == 22


def test_catalog_has_expected_keys():
    actual = {d.key for d in CATALOG}
    assert actual == EXPECTED_KEYS


def test_each_indicator_has_pane_and_output_keys():
    for d in CATALOG:
        assert d.pane in {"price", "oscillator"}
        assert len(d.output_keys) >= 1


def test_each_indicator_compute_path_is_known():
    for d in CATALOG:
        assert d.compute_path in {"talib", "pandas_ta", "talipp_only"}


def test_get_indicator_case_insensitive():
    d = get_indicator("rsi")
    assert d is not None
    assert d.key == "RSI"


def test_list_keys_matches_catalog():
    assert set(list_keys()) == EXPECTED_KEYS
