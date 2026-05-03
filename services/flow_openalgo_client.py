"""Hybrid shim for ``services.flow_openalgo_client``.

Both forms used here are necessary:

* ``_sys.modules[__name__] = _orig`` preserves module identity so
  ``mock.patch.object(services.flow_openalgo_client, "X", ...)`` and other tests
  that touch the service via the shim path still work.
* The post-swap attribute copy ensures any caller that looks up
  names on this shim's own ``__dict__`` (e.g., a deferred
  ``from services.flow_openalgo_client import X`` inside a Flask route that
  resolved to the shim before the swap settled) still finds them.

Source of truth:
``market_regions.india.legacy_v1.services.flow_openalgo_client``.
"""
from __future__ import annotations

import sys as _sys

from market_regions.india.legacy_v1.services import flow_openalgo_client as _orig

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
# future imports of ``services.flow_openalgo_client`` resolve to ``_orig`` and so
# patches via ``mock.patch.object`` against either path land on the
# same dict.
_sys.modules[__name__] = _orig
