"""Phase 6 — D-05 safety defaults.

Per HANDOFF D-05:

* ``max_order_size`` = 100 (units / contracts).
* ``max_notional_usd`` = 100_000 ($100k).
* ``max_notional_inr`` = 1_000_000 (₹10L).
* ``kill_switch_default`` = OFF.
* ``live_mode_default`` = OFF (paper-only first per D-04).

Currency selection comes from the active broker's
``BrokerCapabilities.default_currency``. Unknown currencies fall back
to a USD-equivalent of $100k; if the operator hasn't supplied an FX
snapshot, ``resolve_max_notional`` returns None so the pre-trade
validator can surface a clear "no notional cap configured" error
rather than silently allow.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


# Default per-account guardrails (D-05).
DEFAULT_MAX_ORDER_SIZE = 100
DEFAULT_MAX_NOTIONAL_USD = Decimal("100000")
DEFAULT_MAX_NOTIONAL_INR = Decimal("1000000")
DEFAULT_KILL_SWITCH = False
DEFAULT_LIVE_MODE_ENABLED = False


@dataclass(frozen=True)
class SafetyDefaults:
    max_order_size: int = DEFAULT_MAX_ORDER_SIZE
    max_notional: Decimal | None = None
    currency: str = "USD"
    kill_switch: bool = DEFAULT_KILL_SWITCH
    live_mode_enabled: bool = DEFAULT_LIVE_MODE_ENABLED


def resolve_max_notional(currency: str, fx_to_usd: Decimal | None = None) -> Decimal | None:
    """Map a currency code to the per-account notional cap (D-05).

    Returns None when the currency is unknown AND no FX snapshot was
    supplied — the pre-trade validator treats that as 'no cap
    configured, deny live trades for safety'.
    """
    cur = (currency or "").upper()
    if cur == "USD":
        return DEFAULT_MAX_NOTIONAL_USD
    if cur == "INR":
        return DEFAULT_MAX_NOTIONAL_INR
    if fx_to_usd is not None and fx_to_usd > 0:
        return DEFAULT_MAX_NOTIONAL_USD / fx_to_usd
    return None


def defaults_for_broker_currency(currency: str) -> SafetyDefaults:
    """Build a SafetyDefaults populated from the broker's currency.

    Used at first-load when there's no row in ``chart_safety_settings``
    for the (user, account) pair yet.
    """
    return SafetyDefaults(
        max_order_size=DEFAULT_MAX_ORDER_SIZE,
        max_notional=resolve_max_notional(currency),
        currency=(currency or "USD").upper(),
        kill_switch=DEFAULT_KILL_SWITCH,
        live_mode_enabled=DEFAULT_LIVE_MODE_ENABLED,
    )


__all__ = [
    "DEFAULT_KILL_SWITCH",
    "DEFAULT_LIVE_MODE_ENABLED",
    "DEFAULT_MAX_NOTIONAL_INR",
    "DEFAULT_MAX_NOTIONAL_USD",
    "DEFAULT_MAX_ORDER_SIZE",
    "SafetyDefaults",
    "defaults_for_broker_currency",
    "resolve_max_notional",
]
