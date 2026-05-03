"""Hybrid shim for ``services.oi_tracker_service``.

Both forms used here are necessary:

* ``_sys.modules[__name__] = _orig`` preserves module identity so
  ``mock.patch.object(services.oi_tracker_service, "X", ...)`` and other tests
  that touch the service via the shim path still work.
* The post-swap attribute copy ensures any caller that looks up
  names on this shim's own ``__dict__`` (e.g., a deferred
  ``from services.oi_tracker_service import X`` inside a Flask route that
  resolved to the shim before the swap settled) still finds them.

Source of truth:
``market_regions.india.legacy_v1.services.oi_tracker_service``.
"""
from __future__ import annotations

import sys as _sys

from market_regions.india.legacy_v1.services import oi_tracker_service as _orig

# Copy public attributes onto this module BEFORE the swap so any
# already-bound reference to the shim sees the relocated symbols.
_globals = globals()
for _name in dir(_orig):
    if _name.startswith("__"):
        continue
    if _name in _globals:
        continue
    _globals[_name] = getattr(_orig, _name)
del _globals, _name

# Replace this module in sys.modules with the relocated module so
# future imports of ``services.oi_tracker_service`` resolve to ``_orig`` and so
# patches via ``mock.patch.object`` against either path land on the
# same dict.
_sys.modules[__name__] = _orig
