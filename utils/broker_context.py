"""Return the single broker active in the current deployment.

Track A invariant (ADR 0001): one broker per instance. A request path
has the broker in `flask.session["broker"]`; background jobs can read
it from `BROKER_NAME` env var.

Separate from `utils/config.py` because that module is all about
credentials; this one is about identity. Keep the API tiny.
"""

from __future__ import annotations

import os
from typing import Optional


def current_broker_code() -> Optional[str]:
    """Return the active broker name, or None if unavailable.

    Resolution order:
    1. `flask.session["broker"]` — inside a request context
    2. ``BROKER_NAME`` env var — for background jobs and scripts
    3. None

    Never raises.
    """
    # Import inside the function so non-Flask callers (background jobs,
    # the sync runner) don't pay the import cost and don't crash when
    # Flask isn't configured.
    try:
        from flask import has_request_context, session

        if has_request_context():
            value = session.get("broker")
            if value:
                return str(value)
    except Exception:
        # Flask not installed, or session backend unavailable — fall through.
        pass

    env = os.getenv("BROKER_NAME")
    if env:
        return env.strip() or None
    return None


__all__ = ["current_broker_code"]
