"""Contract test for ``AlpacaOrderTranslator.normalize_order_status``.

Every native Alpaca status string must map to exactly one canonical
``domain.enums.OrderStatus`` value. The mapping is the authoritative
contract between the Alpaca adapter and every UI / display surface
above it; if a mapping changes, the legacy India display vocabulary
parity test (below) and any downstream alerting will surface it
immediately.
"""

from __future__ import annotations

import pytest

from broker.alpaca.api.order_api import AlpacaOrderTranslator
from domain.enums import OrderStatus
from services.order_status_display import (
    coerce_to_status,
    human_label,
    legacy_v1_display,
)


@pytest.mark.parametrize(
    "native, expected",
    [
        # Pre-acceptance
        ("pending_new", OrderStatus.PENDING_NEW),
        ("new", OrderStatus.NEW),
        ("accepted", OrderStatus.NEW),
        ("accepted_for_bidding", OrderStatus.ACCEPTED_FOR_BIDDING),
        # Live in book
        ("partially_filled", OrderStatus.PARTIALLY_FILLED),
        ("held", OrderStatus.SUSPENDED),
        ("suspended", OrderStatus.SUSPENDED),
        ("stopped", OrderStatus.SUSPENDED),
        ("calculated", OrderStatus.CALCULATED),
        # Replace / cancel pending
        ("pending_cancel", OrderStatus.PENDING_CANCEL),
        ("pending_replace", OrderStatus.PENDING_REPLACE),
        ("replaced", OrderStatus.REPLACED),
        # Terminal — success
        ("filled", OrderStatus.FILLED),
        ("done_for_day", OrderStatus.DONE_FOR_DAY),
        # Terminal — failure / withdrawal
        ("canceled", OrderStatus.CANCELED),
        ("cancelled", OrderStatus.CANCELED),  # spelling tolerated
        ("expired", OrderStatus.EXPIRED),
        ("rejected", OrderStatus.REJECTED),
        # Case insensitivity / whitespace tolerance
        ("FILLED", OrderStatus.FILLED),
        (" filled ", OrderStatus.FILLED),
        # Unknown native string falls back to UNKNOWN, never crashes
        ("not_a_real_status", OrderStatus.UNKNOWN),
        ("", OrderStatus.UNKNOWN),
        (None, OrderStatus.UNKNOWN),
    ],
)
def test_alpaca_native_status_maps_to_canonical(native, expected):
    assert AlpacaOrderTranslator.normalize_order_status(native) is expected


@pytest.mark.parametrize(
    "status, legacy",
    [
        (OrderStatus.PENDING_NEW, "open"),
        (OrderStatus.NEW, "open"),
        (OrderStatus.WORKING, "open"),
        (OrderStatus.PARTIALLY_FILLED, "open"),
        (OrderStatus.FILLED, "complete"),
        (OrderStatus.DONE_FOR_DAY, "complete"),
        (OrderStatus.CANCELED, "cancelled"),
        (OrderStatus.EXPIRED, "cancelled"),
        (OrderStatus.REJECTED, "rejected"),
        (OrderStatus.SUSPENDED, "open"),
        (OrderStatus.TRIGGER_PENDING, "trigger pending"),
        (OrderStatus.PENDING_CANCEL, "open"),
        (OrderStatus.PENDING_REPLACE, "open"),
        (OrderStatus.REPLACED, "open"),
        (OrderStatus.UNKNOWN, "open"),
    ],
)
def test_legacy_v1_display_vocabulary(status, legacy):
    """Five-string vocabulary the legacy Indian React UI consumes.

    Parity baselines depend on these strings letter-for-letter.
    """
    assert legacy_v1_display(status) == legacy


@pytest.mark.parametrize(
    "status, label",
    [
        (OrderStatus.NEW, "Open"),
        (OrderStatus.WORKING, "Working"),
        (OrderStatus.PARTIALLY_FILLED, "Partially Filled"),
        (OrderStatus.FILLED, "Filled"),
        (OrderStatus.CANCELED, "Canceled"),
        (OrderStatus.EXPIRED, "Expired"),
        (OrderStatus.REJECTED, "Rejected"),
        (OrderStatus.PENDING_CANCEL, "Cancel Pending"),
        (OrderStatus.TRIGGER_PENDING, "Trigger Pending"),
    ],
)
def test_human_label_format(status, label):
    """Title-case labels suitable for tooltips, modals, telegram bots."""
    assert human_label(status) == label


def test_coerce_to_status_round_trip():
    """The display layer's coerce helper round-trips canonical values."""
    for status in OrderStatus:
        assert coerce_to_status(status.value) is status
        assert coerce_to_status(status) is status


def test_coerce_to_status_unknown_does_not_raise():
    assert coerce_to_status("not-a-real-status") is OrderStatus.UNKNOWN
    assert coerce_to_status(None) is OrderStatus.UNKNOWN
    assert coerce_to_status("") is OrderStatus.UNKNOWN


def test_status_terminal_classification():
    """Terminal vs open partition the state space without overlap."""
    terminal = {s for s in OrderStatus if s.is_terminal}
    open_ = {s for s in OrderStatus if s.is_open}
    assert terminal & open_ == set(), "no status can be both terminal and open"
    # UNKNOWN is intentionally neither.
    assert OrderStatus.UNKNOWN not in terminal
    assert OrderStatus.UNKNOWN not in open_


def test_from_native_order_response_includes_canonical_status():
    """The translator response carries both the canonical and native
    status so downstream consumers can pick whichever vocabulary
    they need."""
    translator = AlpacaOrderTranslator()
    response = translator.from_native_order_response(
        {"id": "abc-123", "status": "filled", "filled_qty": "5", "filled_avg_price": "150.00"},
        instrument=None,
    )
    assert response["order_id"] == "abc-123"
    assert response["status"] == OrderStatus.FILLED.value
    assert response["native_status"] == "filled"
