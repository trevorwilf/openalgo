"""Phase 1 — Datafeed Foundation: Valkey/Redis connection helper.

Valkey is wire-compatible with Redis ≥7 — we use the official
``redis-py`` client. Single-node localhost by default per HANDOFF D-11;
override with ``VALKEY_URL`` env var.

Lazy initialization — importing this module never connects. The first
call to :func:`get_client` (or any helper that uses it) opens the
connection. This keeps test environments without a Valkey instance from
crashing on import.

Key namespaces (per HANDOFF §0.5):

* ``bars:hist:<symbol>:<timeframe>:<from>:<to>`` — TTL 30 min
* ``bars:tail:<symbol>:<timeframe>``             — rolling N=200, no TTL
* ``bar:forming:<symbol>:<timeframe>``           — single in-progress bar
* ``pubsub:ticks:<symbol>``                      — pub/sub channel
"""

from __future__ import annotations

import os
import threading
from typing import Any

try:
    import redis  # type: ignore[import-not-found]

    REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover
    redis = None  # type: ignore[assignment]
    REDIS_AVAILABLE = False


# Default Valkey URL — single-node localhost per D-11.
DEFAULT_VALKEY_URL = "redis://localhost:6379/0"

# TTL for cached historical bar slices (seconds).
HIST_BARS_TTL_SECONDS = 30 * 60
# Rolling tail length for `bars:tail:*`.
TAIL_BARS_LENGTH = 200

# Key-prefix constants.
KEY_PREFIX_HIST = "bars:hist"
KEY_PREFIX_TAIL = "bars:tail"
KEY_PREFIX_FORMING = "bar:forming"
PUBSUB_CHANNEL_PREFIX = "pubsub:ticks"


# Module-level singleton + lock.
_client: Any = None
_client_lock = threading.Lock()


def get_url() -> str:
    """Resolve the Valkey URL from env (``VALKEY_URL``) with a default."""
    return os.environ.get("VALKEY_URL", DEFAULT_VALKEY_URL)


def get_client() -> Any:
    """Return the singleton Valkey/Redis client, initializing on first use.

    Raises :class:`RuntimeError` if ``redis`` is not installed.
    """
    global _client
    if _client is not None:
        return _client
    if not REDIS_AVAILABLE:
        raise RuntimeError(
            "redis-py is not installed. Install with `uv add redis` to use the Valkey helper."
        )
    with _client_lock:
        if _client is None:
            _client = redis.Redis.from_url(get_url(), decode_responses=True)
    return _client


def reset_client_for_tests(client: Any | None = None) -> None:
    """Replace the singleton — used by tests with fakeredis."""
    global _client
    with _client_lock:
        _client = client


def healthcheck() -> bool:
    """Best-effort liveness probe. Returns False instead of raising."""
    try:
        return bool(get_client().ping())
    except Exception:
        return False


# ---- key builders -----------------------------------------------------------

def hist_key(symbol: str, timeframe: str, frm: int, to: int) -> str:
    """Build a `bars:hist:*` key for a cached historical slice."""
    return f"{KEY_PREFIX_HIST}:{symbol}:{timeframe}:{frm}:{to}"


def tail_key(symbol: str, timeframe: str) -> str:
    """Build a `bars:tail:*` key for the rolling tail."""
    return f"{KEY_PREFIX_TAIL}:{symbol}:{timeframe}"


def forming_key(symbol: str, timeframe: str) -> str:
    """Build a `bar:forming:*` key for the single in-progress bar."""
    return f"{KEY_PREFIX_FORMING}:{symbol}:{timeframe}"


def ticks_channel(symbol: str) -> str:
    """Build a `pubsub:ticks:*` channel name."""
    return f"{PUBSUB_CHANNEL_PREFIX}:{symbol}"


__all__ = [
    "DEFAULT_VALKEY_URL",
    "HIST_BARS_TTL_SECONDS",
    "KEY_PREFIX_FORMING",
    "KEY_PREFIX_HIST",
    "KEY_PREFIX_TAIL",
    "PUBSUB_CHANNEL_PREFIX",
    "REDIS_AVAILABLE",
    "TAIL_BARS_LENGTH",
    "forming_key",
    "get_client",
    "get_url",
    "healthcheck",
    "hist_key",
    "reset_client_for_tests",
    "tail_key",
    "ticks_channel",
]
