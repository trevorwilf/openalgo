"""Phase 9-bis-2 final-cleanup (T-35 push) — sys.modules aliasing shim.

The actual blueprint code lives at
``market_regions.india.legacy_v1.blueprints.vol_surface``.
"""
from __future__ import annotations

import sys as _sys

from market_regions.india.legacy_v1.blueprints import vol_surface as _orig

_sys.modules[__name__] = _orig
