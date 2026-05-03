"""Order-status display formatting — single source of truth.

The canonical state machine lives in :class:`domain.enums.OrderStatus`.
Different UI surfaces have different display vocabularies:

* The legacy Indian React UI (``frontend/src/india_legacy/``) renders a
  short lowercase set: ``open``, ``complete``, ``cancelled``,
  ``rejected``, ``trigger pending``. Existing parity baselines depend
  on these strings letter-for-letter, so the legacy formatter MUST
  remain stable.
* The modern UI / Telegram bot / structured logs prefer the FIX-aligned
  vocabulary directly (``FILLED``, ``CANCELED``, etc.) — that's already
  what :class:`OrderStatus` values are.
* Human-friendly labels ("Filled", "Canceled", "Pending Cancel") are
  rendered for places that show the status to a person, not parse it.

All three live in this module so a future surface (web, mobile,
analyzer dashboard, …) reaches for one canonical mapping rather than
re-deriving its own.
"""

from __future__ import annotations

from domain.enums import OrderStatus


# ---------------------------------------------------------------------------
# Legacy Indian React UI — short lowercase vocabulary the old templates
# render directly. Parity fixtures depend on these strings; do NOT
# change them without updating ``tests/parity/baseline/*``.
# ---------------------------------------------------------------------------

_LEGACY_V1_DISPLAY: dict[OrderStatus, str] = {
    OrderStatus.PENDING_NEW: "open",
    OrderStatus.NEW: "open",
    OrderStatus.WORKING: "open",
    OrderStatus.PARTIALLY_FILLED: "open",
    OrderStatus.FILLED: "complete",
    OrderStatus.DONE_FOR_DAY: "complete",
    OrderStatus.CANCELED: "cancelled",
    OrderStatus.EXPIRED: "cancelled",
    OrderStatus.REJECTED: "rejected",
    OrderStatus.SUSPENDED: "open",
    OrderStatus.TRIGGER_PENDING: "trigger pending",
    OrderStatus.PENDING_CANCEL: "open",
    OrderStatus.PENDING_REPLACE: "open",
    OrderStatus.REPLACED: "open",
    OrderStatus.ACCEPTED_FOR_BIDDING: "open",
    OrderStatus.CALCULATED: "open",
    OrderStatus.UNKNOWN: "open",
}


def legacy_v1_display(status: OrderStatus) -> str:
    """Return the legacy Indian React UI's short status string.

    The five-string vocabulary is:
    ``open`` / ``complete`` / ``cancelled`` / ``rejected`` /
    ``trigger pending``.

    Falls back to ``"open"`` if a future ``OrderStatus`` value is added
    without a mapping entry — that's the safest legacy default.
    """
    return _LEGACY_V1_DISPLAY.get(status, "open")


# ---------------------------------------------------------------------------
# Human-friendly labels — title-cased version of the canonical name.
# Useful for tooltips, modals, and notifications. Locale-agnostic for
# now; future i18n hooks can extend the signature without breaking
# existing callers.
# ---------------------------------------------------------------------------

_HUMAN_LABEL: dict[OrderStatus, str] = {
    OrderStatus.PENDING_NEW: "Submitting",
    OrderStatus.NEW: "Open",
    OrderStatus.WORKING: "Working",
    OrderStatus.PARTIALLY_FILLED: "Partially Filled",
    OrderStatus.FILLED: "Filled",
    OrderStatus.DONE_FOR_DAY: "Done for Day",
    OrderStatus.CANCELED: "Canceled",
    OrderStatus.EXPIRED: "Expired",
    OrderStatus.REJECTED: "Rejected",
    OrderStatus.SUSPENDED: "Suspended",
    OrderStatus.TRIGGER_PENDING: "Trigger Pending",
    OrderStatus.PENDING_CANCEL: "Cancel Pending",
    OrderStatus.PENDING_REPLACE: "Replace Pending",
    OrderStatus.REPLACED: "Replaced",
    OrderStatus.ACCEPTED_FOR_BIDDING: "Accepted",
    OrderStatus.CALCULATED: "Calculated",
    OrderStatus.UNKNOWN: "Unknown",
}


def human_label(status: OrderStatus, locale: str = "en") -> str:
    """Return a title-cased, human-readable label for ``status``.

    ``locale`` is reserved for future i18n; today every locale resolves
    to English. Callers should pass the value rather than parsing the
    enum name directly so that adding a translation later is a one-
    line change here.
    """
    del locale  # i18n hook for future use
    return _HUMAN_LABEL.get(status, status.value.replace("_", " ").title())


# ---------------------------------------------------------------------------
# Convenience for legacy v1 callers that have a raw OrderStatus value
# string (already canonical) rather than an enum instance.
# ---------------------------------------------------------------------------


def coerce_to_status(raw: str | OrderStatus | None) -> OrderStatus:
    """Coerce a string or enum into :class:`OrderStatus`. Returns
    :attr:`OrderStatus.UNKNOWN` rather than raising.
    """
    if raw is None:
        return OrderStatus.UNKNOWN
    if isinstance(raw, OrderStatus):
        return raw
    upper = str(raw).strip().upper().replace("-", "_")
    try:
        return OrderStatus(upper)
    except ValueError:
        return OrderStatus.UNKNOWN


__all__ = [
    "coerce_to_status",
    "human_label",
    "legacy_v1_display",
]
