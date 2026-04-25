"""Top-level pytest conftest.

Adds the repo root to ``sys.path`` so test modules can ``import domain``,
``import services``, and so on regardless of how pytest is invoked. The
parity harness already does this manually for its own scripts; this
conftest does it once for the rest of the suite so each test module
does not have to.

This file intentionally has no fixtures — it only affects the
discovery-time module path. It must remain at the repo root for pytest
to load it before any test module collection happens.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
