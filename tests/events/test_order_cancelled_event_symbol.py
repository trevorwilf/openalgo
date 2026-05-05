"""Regression: ``OrderCancelledEvent`` accepts ``symbol`` + ``exchange``.

Bug: ``broker/alpaca/streaming/alpaca_trade_updates.py`` builds a
shared ``common`` dict (with ``symbol`` / ``exchange``) and unpacks
it into every order-event constructor (placed / modified / failed /
cancelled). ``OrderCancelledEvent`` was missing the two fields, so
every Alpaca cancel event raised::

    TypeError: OrderCancelledEvent.__init__() got an unexpected
    keyword argument 'symbol'

The cancel never reached the bus, the v1 React orderbook never
animated the cancel transition, and the error log was flooded.

Add ``symbol`` + ``exchange`` (default ``""``) to match the schema
of OrderPlaced/Modified/Failed.
"""

from __future__ import annotations

from events.order_events import (
    OrderCancelledEvent,
    OrderModifiedEvent,
    OrderFailedEvent,
    OrderPlacedEvent,
)


def test_order_cancelled_event_accepts_symbol_kwarg():
    e = OrderCancelledEvent(
        mode="live",
        api_type="trade_updates",
        orderid="abc",
        status="CANCELED",
        symbol="AAPL",
        exchange="XNAS",
    )
    assert e.orderid == "abc"
    assert e.symbol == "AAPL"
    assert e.exchange == "XNAS"


def test_order_cancelled_event_symbol_defaults_to_empty_string():
    """Backward-compat: existing callers that don't pass symbol/exchange
    keep working with empty defaults.
    """
    e = OrderCancelledEvent(orderid="x", status="CANCELED")
    assert e.symbol == ""
    assert e.exchange == ""


def test_alpaca_trade_updates_common_dict_unpacks_into_every_event():
    """The streaming code's shared ``common`` dict has symbol +
    exchange. Every order-event subclass we unpack it into must
    accept those keys.
    """
    common = {
        "mode": "live",
        "api_type": "trade_updates",
        "symbol": "AAPL",
        "exchange": "XNAS",
        "request_data": {"trade_update": "canceled", "order_id": "abc"},
        "response_data": {"canonical_status": "CANCELED", "data": {}},
        "api_key": "",
    }
    # Each of these constructions must not raise.
    OrderPlacedEvent(
        strategy="alpaca-stream",
        action="BUY",
        quantity=1,
        pricetype="MARKET",
        product="DAY",
        orderid="abc",
        **common,
    )
    OrderModifiedEvent(orderid="abc", **common)
    OrderCancelledEvent(orderid="abc", status="CANCELED", **common)
    OrderFailedEvent(error_message="rejected", **common)
