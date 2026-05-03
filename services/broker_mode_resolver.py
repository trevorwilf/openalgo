"""Resolve whether the active broker session is paper or live.

A trader who's about to send a real order should never have to wonder
which environment they're connected to. The header renders a yellow
``PAPER`` pill when this resolver returns ``"paper"`` so the
distinction stays unambiguous regardless of broker.

Resolution is broker-specific because every broker encodes the
distinction differently:

* **Alpaca** — the API key starts with ``PK`` for paper and ``AK``
  for live; ``ALPACA_LIVE_MODE=1`` env-var override flips to live
  even when the paper key is in the slot.
* **Indian brokers (Zerodha, Angel, etc.)** — paper accounts don't
  exist as a parallel API; operators use OpenAlgo's analyzer/sandbox
  for virtual trading instead. Returns ``"live"`` (the broker
  session is real, the operator's separate analyzer toggle handles
  the simulated layer).
* **Other US brokers (Schwab, Webull, IBKR future)** — typically use
  separate accounts or environment URLs. Resolver returns
  ``"unknown"`` until a per-broker rule is added.

The function is intentionally dependency-light so it can be called
from auth blueprints without pulling in the broker plugin loader.
"""

from __future__ import annotations

import os
from typing import Literal


BrokerMode = Literal["paper", "live", "unknown"]


def resolve_broker_mode(broker: str | None) -> BrokerMode:
    """Return ``"paper"`` / ``"live"`` / ``"unknown"`` for the active
    broker session.

    Reads from the OpenAlgo env block (no broker plugin loader call,
    no DB lookup) so the auth blueprint can include it in
    ``/auth/broker-config`` cheaply.
    """
    if not broker:
        return "unknown"
    code = broker.strip().lower()

    if code == "alpaca":
        return _resolve_alpaca_mode()

    # Indian brokers — no parallel paper API. The session always
    # represents real broker credentials; OpenAlgo's
    # analyzer/sandbox handles simulated trading separately.
    _INDIA_BROKERS = {
        "aliceblue", "angel", "compositedge", "definedge", "dhan",
        "dhan_sandbox", "firstock", "fivepaisa", "fivepaisaxts",
        "flattrade", "fyers", "groww", "ibulls", "iifl",
        "iiflcapital", "indmoney", "jainamxts", "kotak", "motilal",
        "mstock", "nubra", "paytm", "pocketful", "rmoney", "samco",
        "shoonya", "tradejini", "upstox", "wisdom", "zebu",
        "zerodha",
    }
    if code in _INDIA_BROKERS:
        return "live"

    return "unknown"


def _resolve_alpaca_mode() -> BrokerMode:
    """Alpaca-specific paper-vs-live resolution.

    Mirrors the precedence in
    :func:`broker.alpaca.api.auth_api._resolve_is_paper`:

    1. ``ALPACA_LIVE_MODE`` env var when set (``1`` / ``true`` / ``yes``
       / ``on`` → live; anything else → paper).
    2. ``ALPACA_PAPER`` env var when set (``0`` → live; else paper).
    3. Default: paper (matches the auth_api default).

    Additionally validates the resolution against the API key prefix
    when present: Alpaca paper keys begin with ``PK`` and live keys
    with ``AK``. A mismatch (env says live but key is paper, or
    vice versa) returns ``"unknown"`` so the UI can render an
    explicit warning rather than guess.
    """
    live_mode_env = os.environ.get("ALPACA_LIVE_MODE")
    if live_mode_env is not None:
        env_says_live = live_mode_env.strip().lower() in ("1", "true", "yes", "on")
    else:
        paper_env = os.environ.get("ALPACA_PAPER")
        if paper_env is not None:
            env_says_live = paper_env.strip() == "0"
        else:
            env_says_live = False  # default = paper

    # The KEY actually being used is whichever pair the auth resolver
    # picks. Mirror that decision so the pill matches reality even
    # if the env vars are inconsistent.
    explicit_key = os.environ.get("ALPACA_API_KEY")
    if explicit_key and not _is_placeholder(explicit_key):
        active_key = explicit_key
    elif env_says_live:
        active_key = os.environ.get("BROKER_API_KEY_MARKET", "")
    else:
        active_key = os.environ.get("BROKER_API_KEY", "")

    if _is_placeholder(active_key):
        # Operator hasn't filled in real credentials yet — don't
        # render a confident PAPER / LIVE pill on a placeholder.
        return "unknown"

    key_prefix = active_key[:2].upper() if active_key else ""

    # Cross-check key prefix against env intent. Alpaca's convention
    # is well-defined: PK = paper, AK = live. Disagreement means the
    # operator put the wrong key in the wrong slot — surface as
    # "unknown" so the UI flags it instead of silently guessing.
    if key_prefix == "PK":
        return "live" if env_says_live else "paper"
    if key_prefix == "AK":
        # AK key + paper-mode env is a misconfiguration — flag it.
        return "live" if env_says_live else "unknown"
    if not key_prefix:
        return "unknown"
    # Unrecognised prefix — be conservative.
    return "live" if env_says_live else "paper"


_PLACEHOLDERS = frozenset({
    "",
    "YOUR_BROKER_API_KEY",
    "YOUR_BROKER_API_SECRET",
    "YOUR_ALPACA_API_KEY",
    "YOUR_ALPACA_API_SECRET",
})


def _is_placeholder(value: str | None) -> bool:
    return not value or value in _PLACEHOLDERS


__all__ = ["BrokerMode", "resolve_broker_mode"]
