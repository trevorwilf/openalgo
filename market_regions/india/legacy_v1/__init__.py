"""Phase 9-bis stub — target location for the physical relocation
of the v1 lane.

The market-agnostic refactor's Phase 9 (logical) ships the v1
sunset machinery and India-gated conditional mount. The full
physical relocation of:

* ``restx_api/*.py`` (44 files: 37 endpoint modules + schemas +
  account_schema + data_schemas + _v1_lane_guard.py)
* ``domain/translators.py``
* ``utils/constants.py``

into this directory is the v9-bis-2 future engagement. See
``docs/refactor/market-agnostic-phase-9-bis-physical-plan.md`` for
the migration playbook.

This package exists today as a structural placeholder so the
target import path (``market_regions.india.legacy_v1.*``) is
reservable. The real move requires ~100+ import-path updates
across ``app.py``, ``services/``, ``blueprints/``, and other
consumers; that's better handled as a focused engagement with
extensive runtime testing rather than a single-pass automated
refactor.

Phase 9 (logical) already delivers the operator-facing semantic:
the v1 routes are only mounted when the India region plugin is
loaded. The physical move is purely architectural / classification
hygiene.
"""

from __future__ import annotations
