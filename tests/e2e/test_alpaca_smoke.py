"""Alpaca live-sandbox smoke test (skipped by default).

Gated on env ``ALPACA_E2E=1`` plus real credentials. Without all three,
the module is skipped so CI stays green without keys.

What it exercises end-to-end against paper.alpaca.markets:

1. auth -> account + positions
2. place 1-share MARKET BUY of AAPL, DAY
3. poll order status, assert a terminal or accepted-ish state
4. cancel if still open
"""

from __future__ import annotations

import os
import time
from decimal import Decimal

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("ALPACA_E2E") != "1"
    or not os.environ.get("ALPACA_API_KEY")
    or not os.environ.get("ALPACA_API_SECRET"),
    reason=(
        "Live Alpaca E2E smoke test — set ALPACA_E2E=1 and supply "
        "ALPACA_API_KEY / ALPACA_API_SECRET to run."
    ),
)


def test_alpaca_paper_place_and_cancel_aapl():
    from broker.alpaca.api.account_api import get_account_snapshot
    from broker.alpaca.api.auth_api import authenticate
    from broker.alpaca.api.order_api import AlpacaOrderTranslator

    auth = authenticate()
    snap = get_account_snapshot(auth)
    assert snap.currency.value == "USD"
    assert snap.account_id

    translator = AlpacaOrderTranslator(auth=auth)
    body = {
        "symbol": "AAPL",
        "side": "buy",
        "type": "market",
        "time_in_force": "day",
        "qty": "1",
    }
    placed = translator.place_order(body, {"broker_code": "alpaca"})
    order_id = placed.get("id")
    assert order_id, placed

    # Poll briefly for status.
    deadline = time.monotonic() + 15
    status = placed.get("status")
    while time.monotonic() < deadline:
        try:
            status = translator.get_order_status(order_id).get("status")
        except Exception:
            pass
        if status in {"filled", "canceled", "accepted", "new"}:
            break
        time.sleep(1)
    assert status in {
        "new", "accepted", "accepted_for_bidding", "pending_new",
        "filled", "partially_filled", "canceled", "done_for_day",
    }

    # Best-effort cleanup.
    try:
        translator.cancel_order(order_id)
    except Exception:
        pass
