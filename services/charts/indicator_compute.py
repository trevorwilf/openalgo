"""Phase 5 — indicator compute dispatch (talipp / TA-Lib / pandas-ta).

Per HANDOFF Phase 5 §7 / Appendix B§11.2: the compute endpoint
prioritizes:

  1. talipp (live cache hit) — used when the indicator already has a
     hot live instance for (symbol, timeframe). Phase 4 ships the live
     service; Phase 5's batch endpoint just reuses the smoke set
     (RSI/EMA/MACD) when they're already running.
  2. TA-Lib — fast C library, deterministic, broad indicator coverage.
  3. pandas-ta — modern indicators TA-Lib lacks (SuperTrend, Donchian,
     Heikin-Ashi, Keltner, Ichimoku, VWAP).

The endpoint accepts ``[bars]`` + ``indicator_key`` + ``params`` and
returns ``[{t, values}]`` series rows.

When neither TA-Lib nor pandas-ta is installed, the compute path falls
back to a small pure-Python fallback for the moving averages so the
test suite still surfaces values. Production deployments install
both libraries via the operator's `requirements.txt`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

try:
    import talib  # type: ignore[import-not-found]

    TALIB_AVAILABLE = True
except ImportError:  # pragma: no cover
    talib = None  # type: ignore[assignment]
    TALIB_AVAILABLE = False

try:
    import pandas_ta  # type: ignore[import-not-found]

    PANDAS_TA_AVAILABLE = True
except ImportError:  # pragma: no cover
    pandas_ta = None  # type: ignore[assignment]
    PANDAS_TA_AVAILABLE = False

from services.charts.indicator_catalog import IndicatorDef, get_indicator


def _bars_to_frame(bars: Sequence[dict[str, Any]]) -> pd.DataFrame:
    """Project chart wire bars into a pandas DataFrame with float
    columns. Decimal-strings → float at this boundary so TA-Lib /
    pandas-ta can consume them; the API encoder converts back to
    decimal-string at egress.
    """
    if not bars:
        return pd.DataFrame(columns=["t", "open", "high", "low", "close", "volume"])
    return pd.DataFrame(
        {
            "t": [int(b["t"]) for b in bars],
            "open": [float(b["o"]) for b in bars],
            "high": [float(b["h"]) for b in bars],
            "low": [float(b["l"]) for b in bars],
            "close": [float(b["c"]) for b in bars],
            "volume": [float(b["v"]) for b in bars],
        }
    )


def _array_to_series(t: pd.Series, values: np.ndarray, key: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, ts in enumerate(t.tolist()):
        v = values[i] if i < len(values) else None
        if v is None or (isinstance(v, float) and math.isnan(v)):
            out.append({"t": int(ts), "values": {key: None}})
        else:
            out.append({"t": int(ts), "values": {key: float(v)}})
    return out


def compute(
    bars: Sequence[dict[str, Any]],
    indicator_key: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Compute the indicator series for `bars`.

    Returns a list of rows ``[{t: <UTC seconds>, values: {<key>: <float|None>}}]``.

    Raises ``ValueError`` for unknown indicator keys.
    Raises ``RuntimeError`` if neither TA-Lib nor pandas-ta is
    available for the requested compute_path.
    """
    spec = get_indicator(indicator_key)
    if spec is None:
        raise ValueError(f"unknown indicator key: {indicator_key!r}")
    p = {**{ip.name: ip.default for ip in spec.params}, **(params or {})}

    df = _bars_to_frame(bars)
    if df.empty:
        return []

    if spec.compute_path == "talib" and TALIB_AVAILABLE:
        return _compute_talib(df, spec, p)
    if spec.compute_path == "pandas_ta" and PANDAS_TA_AVAILABLE:
        return _compute_pandas_ta(df, spec, p)

    # Fallback: try the other path if the preferred one isn't installed.
    if PANDAS_TA_AVAILABLE:
        return _compute_pandas_ta(df, spec, p)
    if TALIB_AVAILABLE:
        return _compute_talib(df, spec, p)

    return _compute_fallback(df, spec, p)


def _compute_talib(df: pd.DataFrame, spec: IndicatorDef, p: dict[str, Any]) -> list[dict[str, Any]]:
    close = df["close"].astype(float).to_numpy()
    high = df["high"].astype(float).to_numpy()
    low = df["low"].astype(float).to_numpy()
    volume = df["volume"].astype(float).to_numpy()
    t = df["t"]
    k = spec.key

    if k == "SMA":
        return _array_to_series(t, talib.SMA(close, timeperiod=int(p["period"])), "sma")
    if k == "EMA":
        return _array_to_series(t, talib.EMA(close, timeperiod=int(p["period"])), "ema")
    if k == "WMA":
        return _array_to_series(t, talib.WMA(close, timeperiod=int(p["period"])), "wma")
    if k == "RSI":
        return _array_to_series(t, talib.RSI(close, timeperiod=int(p["period"])), "rsi")
    if k == "MACD":
        macd, signal, hist = talib.MACD(
            close,
            fastperiod=int(p["fast_period"]),
            slowperiod=int(p["slow_period"]),
            signalperiod=int(p["signal_period"]),
        )
        return _stack_series(t, {"macd": macd, "signal": signal, "histogram": hist})
    if k == "BB":
        upper, middle, lower = talib.BBANDS(
            close, timeperiod=int(p["period"]), nbdevup=float(p["std"]), nbdevdn=float(p["std"])
        )
        return _stack_series(t, {"upper": upper, "middle": middle, "lower": lower})
    if k == "STOCH":
        k_arr, d_arr = talib.STOCH(
            high,
            low,
            close,
            fastk_period=int(p["k_period"]),
            slowk_period=int(p["smooth_k"]),
            slowd_period=int(p["d_period"]),
        )
        return _stack_series(t, {"k": k_arr, "d": d_arr})
    if k == "ATR":
        return _array_to_series(t, talib.ATR(high, low, close, timeperiod=int(p["period"])), "atr")
    if k == "ADX":
        adx = talib.ADX(high, low, close, timeperiod=int(p["period"]))
        plus_di = talib.PLUS_DI(high, low, close, timeperiod=int(p["period"]))
        minus_di = talib.MINUS_DI(high, low, close, timeperiod=int(p["period"]))
        return _stack_series(t, {"adx": adx, "+di": plus_di, "-di": minus_di})
    if k == "OBV":
        return _array_to_series(t, talib.OBV(close, volume), "obv")
    if k == "CCI":
        return _array_to_series(t, talib.CCI(high, low, close, timeperiod=int(p["period"])), "cci")
    if k == "WILLIAMS_R":
        return _array_to_series(t, talib.WILLR(high, low, close, timeperiod=int(p["period"])), "willr")
    if k == "PSAR":
        return _array_to_series(
            t,
            talib.SAR(high, low, acceleration=float(p["acceleration"]), maximum=float(p["maximum"])),
            "psar",
        )
    if k == "MFI":
        return _array_to_series(t, talib.MFI(high, low, close, volume, timeperiod=int(p["period"])), "mfi")
    if k == "ROC":
        return _array_to_series(t, talib.ROC(close, timeperiod=int(p["period"])), "roc")
    if k == "STOCH_RSI":
        k_arr, d_arr = talib.STOCHRSI(
            close,
            timeperiod=int(p["rsi_period"]),
            fastk_period=int(p["k_period"]),
            fastd_period=int(p["d_period"]),
        )
        return _stack_series(t, {"k": k_arr, "d": d_arr})
    raise ValueError(f"talib path not wired for {k!r}")


def _compute_pandas_ta(df: pd.DataFrame, spec: IndicatorDef, p: dict[str, Any]) -> list[dict[str, Any]]:
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]
    t = df["t"]
    k = spec.key

    if k == "VWAP":
        # pandas-ta VWAP needs a date-indexed DataFrame; build it.
        d = df.copy()
        d["date"] = pd.to_datetime(d["t"], unit="s", utc=True)
        d = d.set_index("date")
        v = d.ta.vwap()
        return _array_to_series(t, v.to_numpy(), "vwap")
    if k == "ICHIMOKU":
        result = pandas_ta.ichimoku(high, low, close, tenkan=p["tenkan"], kijun=p["kijun"], senkou=p["senkou"])
        df1 = result[0]
        cols = list(df1.columns)
        out: dict[str, np.ndarray] = {}
        for canonical, col in zip(("tenkan", "kijun", "senkou_a", "senkou_b", "chikou"), cols):
            out[canonical] = df1[col].to_numpy()
        return _stack_series(t, out)
    if k == "DONCHIAN":
        result = pandas_ta.donchian(high, low, length=int(p["period"]))
        cols = list(result.columns)
        return _stack_series(
            t,
            {"lower": result[cols[0]].to_numpy(), "middle": result[cols[1]].to_numpy(), "upper": result[cols[2]].to_numpy()},
        )
    if k == "KELTNER":
        result = pandas_ta.kc(
            high, low, close, length=int(p["period"]), scalar=float(p["multiplier"])
        )
        cols = list(result.columns)
        return _stack_series(
            t,
            {"lower": result[cols[0]].to_numpy(), "middle": result[cols[1]].to_numpy(), "upper": result[cols[2]].to_numpy()},
        )
    if k == "SUPERTREND":
        result = pandas_ta.supertrend(
            high, low, close, length=int(p["period"]), multiplier=float(p["multiplier"])
        )
        cols = list(result.columns)
        return _stack_series(
            t,
            {"supertrend": result[cols[0]].to_numpy(), "direction": result[cols[1]].to_numpy()},
        )
    if k == "HEIKIN_ASHI":
        result = pandas_ta.ha(df["open"], high, low, close)
        return _stack_series(
            t,
            {
                "ha_o": result["HA_open"].to_numpy(),
                "ha_h": result["HA_high"].to_numpy(),
                "ha_l": result["HA_low"].to_numpy(),
                "ha_c": result["HA_close"].to_numpy(),
            },
        )
    raise ValueError(f"pandas_ta path not wired for {k!r}")


def _compute_fallback(df: pd.DataFrame, spec: IndicatorDef, p: dict[str, Any]) -> list[dict[str, Any]]:
    """Pure-Python fallback for moving averages when neither TA-Lib
    nor pandas-ta is installed. Used in CI environments where the
    operator opts out of the C deps."""
    close = df["close"].to_numpy()
    t = df["t"]
    k = spec.key
    if k == "SMA":
        period = int(p["period"])
        out = np.full(len(close), np.nan)
        for i in range(period - 1, len(close)):
            out[i] = float(np.mean(close[i - period + 1 : i + 1]))
        return _array_to_series(t, out, "sma")
    if k == "EMA":
        period = int(p["period"])
        alpha = 2.0 / (period + 1)
        out = np.full(len(close), np.nan)
        ema = float(close[0])
        for i, x in enumerate(close):
            ema = alpha * float(x) + (1 - alpha) * ema
            if i >= period - 1:
                out[i] = ema
        return _array_to_series(t, out, "ema")
    raise RuntimeError(
        f"Indicator {k!r} requires talib or pandas_ta; install one of them"
    )


def _stack_series(t: pd.Series, columns: dict[str, np.ndarray]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    n = len(t)
    for i in range(n):
        values: dict[str, float | None] = {}
        for name, arr in columns.items():
            v = arr[i] if arr is not None and i < len(arr) else None
            if v is None or (isinstance(v, float) and math.isnan(v)):
                values[name] = None
            else:
                values[name] = float(v)
        rows.append({"t": int(t.iloc[i]), "values": values})
    return rows


__all__ = ["PANDAS_TA_AVAILABLE", "TALIB_AVAILABLE", "compute"]
