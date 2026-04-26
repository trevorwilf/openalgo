"""Phase 4 v4 (ADR 0025) — plugin diagnostics endpoint.

GET /api/v2/plugins/diagnostics
    Returns the per-broker plugin loader diagnostics produced at app
    startup. Operator inspects this to see which plugins loaded, which
    were skipped, and why.

Response shape::

    {
        "status": "success",
        "data": {
            "summary": {
                "loaded": 27,
                "loaded_with_warnings": 0,
                "skipped": 0,
                "promoted_loaded": 3
            },
            "brokers": {
                "alpaca": {
                    "state": "loaded",
                    "promoted": true,
                    "broker_type": "US_stock",
                    "supported_regions": ["us"]
                },
                "_mock_schwab_like": {...},
                "zerodha": {...},
                ...
            }
        }
    }

Skipped brokers carry a ``reason`` and ``errors``/``missing_fields``
blob explaining the rejection. The structure is intentionally
operator-readable; tools can key on the ``state`` enum.
"""

from __future__ import annotations

from flask_restx import Namespace, Resource

from restx_api.v2._auth import ok
from utils.plugin_loader import get_plugin_diagnostics

api = Namespace("plugins", description="Promoted plugin diagnostics")


@api.route("/diagnostics")
@api.route("/diagnostics/")
class PluginDiagnostics(Resource):
    def get(self):
        diagnostics = get_plugin_diagnostics()
        loaded = sum(1 for d in diagnostics.values() if d.get("state") == "loaded")
        loaded_with_warnings = sum(
            1 for d in diagnostics.values() if d.get("state") == "loaded_with_warnings"
        )
        skipped = sum(1 for d in diagnostics.values() if d.get("state") == "skipped")
        promoted_loaded = sum(
            1
            for d in diagnostics.values()
            if d.get("state") == "loaded" and d.get("promoted")
        )
        return ok({
            "summary": {
                "loaded": loaded,
                "loaded_with_warnings": loaded_with_warnings,
                "skipped": skipped,
                "promoted_loaded": promoted_loaded,
            },
            "brokers": diagnostics,
        }), 200
