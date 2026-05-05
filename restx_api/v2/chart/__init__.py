"""Phase 1 — Datafeed Foundation: /api/v2/chart/* skeleton.

Routes return shape-correct stub responses (200/201/204) so consumers
can wire against the contract today; full CRUD lands in Phase 5.

Auth reuses the v2 helper (`apikey` field). The user identity used for
per-row scoping is derived from the resolved auth token via
``database.auth_db.get_username_by_apikey``; tests can monkey-patch the
``_resolve_user_id`` helper directly.

Sub-namespaces are exported and registered under their /chart/<x> paths
by ``restx_api.v2.__init__._build``.
"""

from __future__ import annotations

from .layouts import api as layouts_ns
from .drawings import api as drawings_ns
from .indicators import api as indicators_ns
from .watchlists import api as watchlists_ns
from .templates import api as templates_ns
from .active_layout import api as active_layout_ns

__all__ = [
    "active_layout_ns",
    "drawings_ns",
    "indicators_ns",
    "layouts_ns",
    "templates_ns",
    "watchlists_ns",
]
