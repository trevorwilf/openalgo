"""Phase 9-bis-physical (T-23) — relocated v1 lane internals.

This package is the physical home for the legacy India v1 lane's
restx_api/* modules. It is reached via the shim layer at
``restx_api.*`` (Option B per the migration playbook in
``docs/refactor/market-agnostic-phase-9-bis-physical-plan.md``).

Group A (schemas / data_schemas / account_schema) lands first; Group B
(domain.translators + utils.constants), Group C (37 endpoint modules),
and Group D (_v1_lane_guard) follow.
"""

from __future__ import annotations
