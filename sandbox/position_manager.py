"""Phase 9-bis-2 final-cleanup (T-35 push) — sys.modules aliasing shim.

The actual code lives at
``market_regions.india.legacy_v1.sandbox.position_manager``. This shim
replaces the module object in ``sys.modules`` with the
relocated module so module-level singletons stay singleton
across both import paths.
"""
from __future__ import annotations

import sys as _sys

from market_regions.india.legacy_v1.sandbox import position_manager as _orig

_sys.modules[__name__] = _orig
