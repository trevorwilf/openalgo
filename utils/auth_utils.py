"""Phase 9-bis-2 final-cleanup (T-35 push) — sys.modules aliasing shim.

The actual code lives at
``market_regions.india.legacy_v1.utils.auth_utils``.
"""
from __future__ import annotations

import sys as _sys

from market_regions.india.legacy_v1.utils import auth_utils as _orig

_sys.modules[__name__] = _orig
