"""Phase 5 — POST /api/v2/indicators/series.

Compute per-bar indicator values for a (symbol, timeframe, indicator,
params, range) request. The endpoint:

  1. Fetches bars from /api/v2/bars (or directly from the bar
     resampler when DuckDB is available).
  2. Routes the compute through `services.charts.indicator_compute.compute`,
     which dispatches talipp (live) → TA-Lib → pandas-ta.
  3. Returns the series rows in the wire shape ``[{t, values}]``.

Acceptance: <500ms for 50k bars + 5 indicators (HANDOFF Phase 5 §7).
"""

from __future__ import annotations

from flask import request
from flask_restx import Namespace, Resource

from restx_api.v2._auth import error, ok
from services.charts.indicator_catalog import get_indicator
from services.charts.indicator_compute import compute

api = Namespace("indicators-series", description="Indicator series compute")


@api.route("")
@api.route("/")
class IndicatorSeries(Resource):
    def post(self):
        body = request.get_json(silent=True) or {}
        bars = body.get("bars")
        key = body.get("indicator_key")
        params = body.get("params") or {}
        if not isinstance(bars, list) or key is None:
            return error("bad_request", "bars and indicator_key are required"), 400
        spec = get_indicator(str(key))
        if spec is None:
            return error("unknown_indicator", f"{key!r} is not in the v1 catalog"), 404
        try:
            series = compute(bars=bars, indicator_key=str(key), params=params)
        except ValueError as e:
            return error("bad_request", str(e)), 400
        except RuntimeError as e:
            return error("compute_unavailable", str(e)), 503
        return ok({"indicator_key": str(key).upper(), "params": params, "series": series}), 200


__all__ = ["api"]
