"""Phase 9-bis-2 final-cleanup (T-35 push) — sys.modules aliasing shim.

The actual sandbox engine code lives at
``market_regions.india.legacy_v1.sandbox``. This package alias
preserves ``import sandbox`` / ``from sandbox import X`` /
``from sandbox.order_manager import OrderManager`` etc. by
replacing the package object in ``sys.modules`` with the
relocated package. Module-level singletons (threads, locks)
stay singleton because both import paths resolve to the same
module object.
"""
from __future__ import annotations

import sys as _sys

from market_regions.india.legacy_v1 import sandbox as _orig

_sys.modules[__name__] = _orig
