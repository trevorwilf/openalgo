"""Phase 4 — talipp live incremental indicator service.

Subscribes to ``pubsub:ticks:<symbol>`` (Valkey) and emits per-tick
indicator updates via the WSEnvelope ``indicator_update`` payload.

Only a smoke set of indicators is wired in Phase 4 (RSI, EMA, MACD).
The full v1 catalog (~22 indicators) wires in Phase 5 alongside the
batch TA-Lib + pandas-ta paths.

Latency target: tick → indicator update <200ms p50 (HANDOFF Phase 4
acceptance).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

try:
    from talipp.indicators import EMA, MACD, RSI

    TALIPP_AVAILABLE = True
except ImportError:  # pragma: no cover
    EMA = MACD = RSI = None  # type: ignore[assignment]
    TALIPP_AVAILABLE = False


@dataclass(frozen=True)
class IndicatorSpec:
    """Per (symbol, timeframe, indicator-key, params) instance."""

    id: str
    symbol: str
    timeframe: str
    key: str  # 'RSI' | 'EMA' | 'MACD' | etc.
    params: dict[str, Any]


@dataclass
class IndicatorInstance:
    """Active running instance of a talipp indicator."""

    spec: IndicatorSpec
    indicator: Any  # talipp indicator object
    last_value: dict[str, float | None] | None = None


class TalippIndicatorService:
    """Manages the active set of running talipp indicators and emits
    updates per tick.

    The class itself does NOT open a Valkey connection — the caller
    feeds it OHLC ticks via :meth:`feed_close`. Tests can drive it
    deterministically without a Valkey instance.
    """

    def __init__(self, on_update: Callable[[IndicatorSpec, dict[str, float | None]], None] | None = None) -> None:
        self._instances: dict[str, IndicatorInstance] = {}
        self._on_update = on_update

    def register(self, spec: IndicatorSpec) -> None:
        if not TALIPP_AVAILABLE:
            raise RuntimeError(
                "talipp is not installed. Run `uv add 'talipp>=2.7'`."
            )
        if spec.id in self._instances:
            return
        ind = _make_indicator(spec.key, spec.params)
        self._instances[spec.id] = IndicatorInstance(spec=spec, indicator=ind)

    def remove(self, indicator_id: str) -> None:
        self._instances.pop(indicator_id, None)

    def list_keys(self) -> list[str]:
        return ["EMA", "RSI", "MACD"]

    def feed_close(self, symbol: str, timeframe: str, close: float) -> None:
        """Push a single close price into every matching indicator and
        emit on_update with the indicator's latest value(s)."""
        for inst in list(self._instances.values()):
            if inst.spec.symbol != symbol or inst.spec.timeframe != timeframe:
                continue
            try:
                inst.indicator.add(close)
            except Exception:  # noqa: BLE001
                continue
            value = _read_value(inst.spec.key, inst.indicator)
            inst.last_value = value
            if self._on_update:
                self._on_update(inst.spec, value)


def _make_indicator(key: str, params: dict[str, Any]) -> Any:
    if not TALIPP_AVAILABLE:
        raise RuntimeError("talipp not installed")
    if key == "EMA":
        return EMA(period=int(params.get("period", 14)))
    if key == "RSI":
        return RSI(period=int(params.get("period", 14)))
    if key == "MACD":
        return MACD(
            fast_period=int(params.get("fast_period", 12)),
            slow_period=int(params.get("slow_period", 26)),
            signal_period=int(params.get("signal_period", 9)),
        )
    raise ValueError(f"unsupported live indicator key: {key!r}")


def _read_value(key: str, indicator: Any) -> dict[str, float | None]:
    out = indicator.output_values
    if not out:
        return {key: None}
    last = out[-1]
    if key == "MACD":
        if last is None:
            return {"macd": None, "signal": None, "histogram": None}
        return {
            "macd": _safe_float(getattr(last, "macd", None)),
            "signal": _safe_float(getattr(last, "signal", None)),
            "histogram": _safe_float(getattr(last, "histogram", None)),
        }
    return {key.lower(): _safe_float(last)}


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return f if f == f else None  # NaN check
    except (TypeError, ValueError):
        return None


__all__ = [
    "IndicatorInstance",
    "IndicatorSpec",
    "TALIPP_AVAILABLE",
    "TalippIndicatorService",
]
