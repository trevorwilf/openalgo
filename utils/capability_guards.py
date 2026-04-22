"""Phase 7 — Flask route decorator that gates on `BrokerCapabilities`.

When a route is decorated with ``@requires_capability("supports_analyzer")``:

1. Reads the current broker from ``flask.session["broker"]``.
2. Looks up the rich capability object via
   ``utils.plugin_loader.get_broker_capabilities``.
3. If the capability attribute is `False` (or the capability object is
   unavailable), returns a structured 403 JSON body and never enters
   the route function.

No behavior change when the capability is `True`. Decorator is safe to
apply to any Flask view — it preserves the view's return shape (JSON
for API endpoints, ``render_template`` for HTML pages both pass through
untouched when allowed).

Per ADR 0004 the analyzer is explicitly India-only. Capability gating
is how non-Indian brokers get a clean "feature unavailable" response
instead of a 500 on the first India-specific query the handler runs.
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from flask import jsonify, request, session

from utils.logging import get_logger

logger = get_logger(__name__)


def _current_capability_object():
    """Best-effort lookup of the current broker's BrokerCapabilities.

    Returns (caps, broker) — either may be None if the session has no
    broker or the loader has no record for it.
    """
    broker = session.get("broker")
    if not broker:
        return None, None
    try:
        from utils.plugin_loader import get_broker_capabilities

        return get_broker_capabilities(broker), broker
    except Exception as e:  # defensive: loader misconfiguration, etc.
        logger.debug("capability lookup failed for %s: %s", broker, e)
        return None, broker


def _is_html_request() -> bool:
    """Return True if the client prefers HTML — we'll return a minimal
    403 body the browser can render rather than JSON.

    This matches how the existing blueprints behave: most routes serve
    HTML when hit directly and JSON when the React app calls them.
    """
    # If Flask's content negotiation prefers html over json, treat it
    # as an HTML request. Falls back to Accept-header sniffing.
    accept = request.accept_mimetypes
    best = accept.best_match(["application/json", "text/html"])
    return best == "text/html"


def requires_capability(
    name: str, *, status: int = 403
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Flask route decorator — gates on a BrokerCapabilities attribute.

    ``name`` is the attribute on ``BrokerCapabilities`` (e.g.
    ``"supports_analyzer"``, ``"supports_fractional"``). The decorator
    is tolerant of both first-class flags and entries under the
    ``features`` dict via ``caps.has_capability(name)``.

    Failure payload (JSON, matches `/api/v1` style plus a ``code``):

        {
          "status": "error",
          "code": "CAPABILITY_UNAVAILABLE",
          "capability": "<name>",
          "message": "Broker '<broker>' does not support <name>."
        }
    """

    def decorator(view: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            caps, broker = _current_capability_object()

            # No caps or no broker → fail closed. An unauthenticated
            # request to an analyzer route is not our job to fix here;
            # the existing session_required decorators elsewhere handle
            # auth. We return 403 for consistency.
            allowed = False
            if caps is not None:
                # Prefer the capability's own has_capability() so we
                # handle both first-class flags and `features` dict
                # entries uniformly.
                if hasattr(caps, "has_capability"):
                    allowed = bool(caps.has_capability(name))
                else:
                    allowed = bool(getattr(caps, name, False))

            if not allowed:
                broker_label = broker or "unknown"
                logger.info(
                    "capability gate blocked route %s for broker=%s capability=%s",
                    request.path, broker_label, name,
                )
                payload = {
                    "status": "error",
                    "code": "CAPABILITY_UNAVAILABLE",
                    "capability": name,
                    "message": f"Broker {broker_label!r} does not support {name}.",
                }
                # Always JSON — simpler for callers to handle and the
                # React frontend always reads JSON anyway.
                return jsonify(payload), status

            return view(*args, **kwargs)

        return wrapper

    return decorator


__all__ = ["requires_capability"]
