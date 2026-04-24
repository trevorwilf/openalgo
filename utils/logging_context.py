"""Structured-logging context helpers.

Wraps a block of work with log record extras so every log line
emitted inside the context carries the same broker/region/venue/
rule-id fields. Promoted and legacy lane dispatchers use this at
entry to keep the two lanes distinguishable in aggregate logs.

Example::

    with log_context(broker_code="alpaca", venue_code="XNAS",
                     legacy_fallback=False):
        logger.info("order received")
"""

from __future__ import annotations

import contextvars
import logging
from contextlib import contextmanager
from typing import Any, Iterator

_LOG_CONTEXT: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "openalgo_log_context", default={}
)


# Allowed keys — keeps operators' dashboards consistent. New keys
# should be added here intentionally.
SUPPORTED_KEYS = frozenset(
    {
        "broker_code",
        "region_code",
        "venue_code",
        "instrument_id",
        "asset_class",
        "session",
        "time_in_force",
        "quantity_unit",
        "rule_id",
        "legacy_fallback",
    }
)


class _ContextFilter(logging.Filter):
    """Attach the active context dict to each log record as `.context`.

    Most handlers either format `record.__dict__` or rely on extras in
    structured output; `.context` is a stable attribute either can pick
    up. Unknown keys are not filtered — callers' mistakes surface.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = _LOG_CONTEXT.get()
        if ctx:
            record.__dict__["context"] = ctx
            for k, v in ctx.items():
                # Mirror into dedicated attributes so a JSON formatter
                # that uses record.__dict__ directly picks them up.
                record.__dict__.setdefault(k, v)
        return True


_filter_installed = False


def install_log_context_filter(logger: logging.Logger | None = None) -> None:
    """Attach the context filter to the root logger (once)."""
    global _filter_installed
    if _filter_installed:
        return
    target = logger or logging.getLogger()
    target.addFilter(_ContextFilter())
    _filter_installed = True


@contextmanager
def log_context(**fields: Any) -> Iterator[dict[str, Any]]:
    """Push ``fields`` onto the logging context for this block."""
    current = _LOG_CONTEXT.get()
    merged = {**current, **{k: v for k, v in fields.items() if v is not None}}
    token = _LOG_CONTEXT.set(merged)
    try:
        yield merged
    finally:
        _LOG_CONTEXT.reset(token)


def current_context() -> dict[str, Any]:
    """Return a copy of the active log context — for metrics helpers."""
    return dict(_LOG_CONTEXT.get())


__all__ = [
    "SUPPORTED_KEYS",
    "current_context",
    "install_log_context_filter",
    "log_context",
]
