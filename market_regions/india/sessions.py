"""India region timezone object — Phase 2 T-10 relocation.

Single source of truth for the ``Asia/Kolkata`` timezone object that
the rest of the codebase imports as ``IST``. Five PROMOTED_CORE
files previously each carried their own
``IST = pytz.timezone("Asia/Kolkata")`` module-level constant; they
now import it from here.

This is byte-equivalent: the underlying ``pytz.timezone`` object is
the same instance regardless of import path because pytz caches
timezone objects by name.
"""

from __future__ import annotations

import pytz


IST = pytz.timezone("Asia/Kolkata")


__all__ = ["IST"]
