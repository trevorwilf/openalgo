"""Phase 5 — v1 indicator catalog.

Defines the ~22 indicators the chart workspace surfaces. Each entry
declares:

* ``key`` — stable id used in `chart_indicators.indicator_key`,
  TS catalog, and the /api/v2/indicators/series endpoint.
* ``label`` — human-readable name for the IndicatorManager UI.
* ``params`` — list of (name, type, default, [min/max/step/options])
  describing the user-tunable parameters.
* ``output_keys`` — list of series keys this indicator emits per bar.
* ``pane`` — `'price'` (overlay on price chart) or `'oscillator'`
  (own pane below price).
* ``compute_path`` — `'talib'` | `'pandas_ta'` | `'talipp_only'`.
  The /api/v2/indicators/series endpoint dispatches in priority:
  talipp (live cache) → TA-Lib (batch) → pandas-ta (modern).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class IndicatorParam:
    name: str
    type: Literal["int", "float", "bool", "string", "select"]
    default: int | float | bool | str
    min_value: int | float | None = None
    max_value: int | float | None = None
    step: int | float | None = None
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class IndicatorDef:
    key: str
    label: str
    pane: Literal["price", "oscillator"]
    output_keys: tuple[str, ...]
    compute_path: Literal["talib", "pandas_ta", "talipp_only"]
    params: tuple[IndicatorParam, ...] = field(default_factory=tuple)


# v1 catalog (HANDOFF §4 / Appendix B§11.2). 22 indicators.
CATALOG: tuple[IndicatorDef, ...] = (
    IndicatorDef(
        key="SMA",
        label="Simple Moving Average",
        pane="price",
        output_keys=("sma",),
        compute_path="talib",
        params=(IndicatorParam("period", "int", 14, 1, 500, 1),),
    ),
    IndicatorDef(
        key="EMA",
        label="Exponential Moving Average",
        pane="price",
        output_keys=("ema",),
        compute_path="talib",
        params=(IndicatorParam("period", "int", 14, 1, 500, 1),),
    ),
    IndicatorDef(
        key="WMA",
        label="Weighted Moving Average",
        pane="price",
        output_keys=("wma",),
        compute_path="talib",
        params=(IndicatorParam("period", "int", 14, 1, 500, 1),),
    ),
    IndicatorDef(
        key="VWAP",
        label="Volume-Weighted Average Price",
        pane="price",
        output_keys=("vwap",),
        compute_path="pandas_ta",
    ),
    IndicatorDef(
        key="RSI",
        label="Relative Strength Index",
        pane="oscillator",
        output_keys=("rsi",),
        compute_path="talib",
        params=(IndicatorParam("period", "int", 14, 2, 100, 1),),
    ),
    IndicatorDef(
        key="MACD",
        label="MACD",
        pane="oscillator",
        output_keys=("macd", "signal", "histogram"),
        compute_path="talib",
        params=(
            IndicatorParam("fast_period", "int", 12, 1, 200, 1),
            IndicatorParam("slow_period", "int", 26, 1, 400, 1),
            IndicatorParam("signal_period", "int", 9, 1, 100, 1),
        ),
    ),
    IndicatorDef(
        key="BB",
        label="Bollinger Bands",
        pane="price",
        output_keys=("upper", "middle", "lower"),
        compute_path="talib",
        params=(
            IndicatorParam("period", "int", 20, 2, 200, 1),
            IndicatorParam("std", "float", 2.0, 0.5, 5.0, 0.5),
        ),
    ),
    IndicatorDef(
        key="STOCH",
        label="Stochastic",
        pane="oscillator",
        output_keys=("k", "d"),
        compute_path="talib",
        params=(
            IndicatorParam("k_period", "int", 14, 1, 100, 1),
            IndicatorParam("d_period", "int", 3, 1, 50, 1),
            IndicatorParam("smooth_k", "int", 3, 1, 50, 1),
        ),
    ),
    IndicatorDef(
        key="ATR",
        label="Average True Range",
        pane="oscillator",
        output_keys=("atr",),
        compute_path="talib",
        params=(IndicatorParam("period", "int", 14, 1, 100, 1),),
    ),
    IndicatorDef(
        key="ADX",
        label="Average Directional Index",
        pane="oscillator",
        output_keys=("adx", "+di", "-di"),
        compute_path="talib",
        params=(IndicatorParam("period", "int", 14, 1, 100, 1),),
    ),
    IndicatorDef(
        key="OBV",
        label="On-Balance Volume",
        pane="oscillator",
        output_keys=("obv",),
        compute_path="talib",
    ),
    IndicatorDef(
        key="CCI",
        label="Commodity Channel Index",
        pane="oscillator",
        output_keys=("cci",),
        compute_path="talib",
        params=(IndicatorParam("period", "int", 20, 1, 100, 1),),
    ),
    IndicatorDef(
        key="WILLIAMS_R",
        label="Williams %R",
        pane="oscillator",
        output_keys=("willr",),
        compute_path="talib",
        params=(IndicatorParam("period", "int", 14, 1, 100, 1),),
    ),
    IndicatorDef(
        key="ICHIMOKU",
        label="Ichimoku Cloud",
        pane="price",
        output_keys=("tenkan", "kijun", "senkou_a", "senkou_b", "chikou"),
        compute_path="pandas_ta",
        params=(
            IndicatorParam("tenkan", "int", 9, 1, 200, 1),
            IndicatorParam("kijun", "int", 26, 1, 200, 1),
            IndicatorParam("senkou", "int", 52, 1, 400, 1),
        ),
    ),
    IndicatorDef(
        key="PSAR",
        label="Parabolic SAR",
        pane="price",
        output_keys=("psar",),
        compute_path="talib",
        params=(
            IndicatorParam("acceleration", "float", 0.02, 0.001, 1.0, 0.001),
            IndicatorParam("maximum", "float", 0.2, 0.05, 1.0, 0.05),
        ),
    ),
    IndicatorDef(
        key="DONCHIAN",
        label="Donchian Channel",
        pane="price",
        output_keys=("upper", "middle", "lower"),
        compute_path="pandas_ta",
        params=(IndicatorParam("period", "int", 20, 1, 200, 1),),
    ),
    IndicatorDef(
        key="KELTNER",
        label="Keltner Channel",
        pane="price",
        output_keys=("upper", "middle", "lower"),
        compute_path="pandas_ta",
        params=(
            IndicatorParam("period", "int", 20, 1, 200, 1),
            IndicatorParam("multiplier", "float", 2.0, 0.5, 5.0, 0.5),
        ),
    ),
    IndicatorDef(
        key="MFI",
        label="Money Flow Index",
        pane="oscillator",
        output_keys=("mfi",),
        compute_path="talib",
        params=(IndicatorParam("period", "int", 14, 1, 100, 1),),
    ),
    IndicatorDef(
        key="ROC",
        label="Rate of Change",
        pane="oscillator",
        output_keys=("roc",),
        compute_path="talib",
        params=(IndicatorParam("period", "int", 10, 1, 100, 1),),
    ),
    IndicatorDef(
        key="STOCH_RSI",
        label="Stochastic RSI",
        pane="oscillator",
        output_keys=("k", "d"),
        compute_path="talib",
        params=(
            IndicatorParam("rsi_period", "int", 14, 1, 100, 1),
            IndicatorParam("stoch_period", "int", 14, 1, 100, 1),
            IndicatorParam("k_period", "int", 3, 1, 50, 1),
            IndicatorParam("d_period", "int", 3, 1, 50, 1),
        ),
    ),
    IndicatorDef(
        key="SUPERTREND",
        label="SuperTrend",
        pane="price",
        output_keys=("supertrend", "direction"),
        compute_path="pandas_ta",
        params=(
            IndicatorParam("period", "int", 7, 1, 100, 1),
            IndicatorParam("multiplier", "float", 3.0, 0.5, 10.0, 0.5),
        ),
    ),
    IndicatorDef(
        key="HEIKIN_ASHI",
        label="Heikin-Ashi",
        pane="price",
        output_keys=("ha_o", "ha_h", "ha_l", "ha_c"),
        compute_path="pandas_ta",
    ),
)


CATALOG_BY_KEY: dict[str, IndicatorDef] = {d.key: d for d in CATALOG}


def get_indicator(key: str) -> IndicatorDef | None:
    return CATALOG_BY_KEY.get(key.upper())


def list_keys() -> list[str]:
    return [d.key for d in CATALOG]


__all__ = [
    "CATALOG",
    "CATALOG_BY_KEY",
    "IndicatorDef",
    "IndicatorParam",
    "get_indicator",
    "list_keys",
]
