"""Tiny env-variable feature-flag helper for the market-agnostic refactor.

Every new read/write path that the refactor introduces is gated by a
flag here. Default off until Phase 9's canary turns each one on.

No config framework, no hot-reload — flags are read from os.environ on
every call. `.env` edits through `blueprints/broker_credentials.py`
therefore take effect on the next request (that module already calls
``load_dotenv(override=True)`` at import; flips in-process values
persist for the running process).
"""

from __future__ import annotations

import os

_TRUE_VALUES: frozenset[str] = frozenset({"1", "true", "yes", "on"})


def is_enabled(name: str, default: bool = False) -> bool:
    """Return True if env var `name` evaluates truthy.

    Truthy values (case-insensitive, whitespace-stripped): 1, true, yes, on.
    Anything else (including missing) falls through to `default`.
    """
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in _TRUE_VALUES


__all__ = ["is_enabled"]
