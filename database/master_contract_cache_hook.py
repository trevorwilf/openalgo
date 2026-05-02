"""Phase 9-bis-2 final-cleanup (T-35 push) — sys.modules aliasing shim.

The actual code lives at
``market_regions.india.legacy_v1.database.master_contract_cache_hook``.
"""
from __future__ import annotations

import sys as _sys

from market_regions.india.legacy_v1.database import master_contract_cache_hook as _orig

_sys.modules[__name__] = _orig
