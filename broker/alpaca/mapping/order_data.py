"""Alpaca → OpenAlgo legacy v1 schema mapping.

Bridges Alpaca's REST response shapes (``/v2/orders``, ``/v2/positions``,
``/v2/account/activities/FILL``) onto the OpenAlgo legacy v1
order-book / position-book / holdings / tradebook output schema.
This is the missing piece that lets the legacy v1 services dispatch
into Alpaca via ``services.orderbook_service``,
``services.positionbook_service``, ``services.holdings_service``,
and ``services.tradebook_service``.

Modeled on ``broker/zerodha/mapping/order_data.py`` (the canonical
reference for the v1 mapping contract). Differences from the
Indian-broker baseline:

* Alpaca symbols don't need ``get_oa_symbol`` lookup — they're already
  in canonical form (``AAPL``, ``TSLA``). No SymToken round-trip.
* Alpaca uses native exchange names (``NASDAQ``, ``NYSE``, ``ARCA``,
  ``BATS``); we pass them through unchanged. The v1 quote schema
  rejects these on the *request* side, but they're fine in *response*
  payloads (orderbook / positions / holdings / tradebook do not
  validate exchange against the Indian enum).
* Alpaca has no MIS / CNC / NRML product distinction. Every position
  is delivery-style (overnight), so positions/holdings default to
  ``"CNC"``. Orders have no product concept either; we surface
  ``"CNC"`` for parity with the v1 shape (downstream consumers that
  switch on product see a stable, sensible value).
* Position quantity is signed (long positive, short negative) per the
  OpenAlgo v1 convention, derived from Alpaca's ``side`` + positive
  ``qty``.
"""

from __future__ import annotations

from typing import Any

from utils.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Alpaca → OpenAlgo enum / status / type translations
# ---------------------------------------------------------------------------

# Alpaca order status → OpenAlgo v1 order_status. The v1 vocabulary is
# {complete, rejected, "trigger pending", open, cancelled}.
_ALPACA_STATUS_TO_OA = {
    # Terminal — success
    "filled": "complete",
    "done_for_day": "complete",
    # Terminal — failure / withdrawal
    "rejected": "rejected",
    "canceled": "cancelled",
    "cancelled": "cancelled",
    "expired": "cancelled",
    # Live in book
    "new": "open",
    "accepted": "open",
    "accepted_for_bidding": "open",
    "pending_new": "open",
    "partially_filled": "open",
    "pending_cancel": "open",
    "pending_replace": "open",
    "replaced": "open",
    "held": "open",
    "stopped": "open",
    "suspended": "open",
    "calculated": "open",
}

# Alpaca order type → OpenAlgo v1 pricetype. The v1 vocabulary is
# {MARKET, LIMIT, SL, SL-M}. We collapse the auction variants and
# trailing-stop onto the closest equivalent.
_ALPACA_TYPE_TO_OA = {
    "market": "MARKET",
    "limit": "LIMIT",
    "stop": "SL-M",            # stop market
    "stop_limit": "SL",        # stop limit
    "trailing_stop": "SL-M",   # closest equivalent
    # Auction variants serialize as plain market/limit at Alpaca; treat
    # them as their non-auction counterparts here (the v1 schema has no
    # MOO / MOC / LOO / LOC values).
    "market_on_open": "MARKET",
    "limit_on_open": "LIMIT",
    "market_on_close": "MARKET",
    "limit_on_close": "LIMIT",
}


def _translate_status(native: Any) -> str:
    if not isinstance(native, str):
        return "open"
    return _ALPACA_STATUS_TO_OA.get(native.lower().strip(), "open")


def _translate_type(native: Any) -> str:
    if not isinstance(native, str):
        return "MARKET"
    return _ALPACA_TYPE_TO_OA.get(native.lower().strip(), native.upper())


def _translate_action(native: Any) -> str:
    """Alpaca uses ``buy`` / ``sell``; OpenAlgo uses ``BUY`` / ``SELL``."""
    if not isinstance(native, str):
        return ""
    return native.upper()


def _coerce_float(raw: Any, default: float = 0.0) -> float:
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _coerce_qty(raw: Any) -> float | int:
    """Quantity stays integer when whole, float when fractional. Mirrors
    ``services.orderbook_service.format_order_data`` so downstream
    coercion is a no-op on already-integer inputs.
    """
    val = _coerce_float(raw, 0.0)
    return int(val) if val == int(val) else val


# ---------------------------------------------------------------------------
# Order book — map / calc / transform
# ---------------------------------------------------------------------------


def map_order_data(order_data: Any) -> list[dict[str, Any]]:
    """Unwrap the ``{"status": ..., "data": [...]}`` envelope into a flat
    list of order rows. Alpaca symbols are already canonical, so no
    per-row symbol rewriting is required (unlike Indian brokers).
    """
    if isinstance(order_data, dict):
        if order_data.get("data") is None:
            logger.info("Alpaca: no order data available.")
            return []
        rows = order_data["data"]
    else:
        rows = order_data or []
    return list(rows) if rows else []


def calculate_order_statistics(order_data: list[dict[str, Any]]) -> dict[str, int]:
    """Count BUY / SELL and complete / open / rejected (v1 contract)."""
    total_buy_orders = total_sell_orders = 0
    total_completed_orders = total_open_orders = total_rejected_orders = 0

    for order in order_data or []:
        side = (order.get("side") or "").lower()
        if side == "buy":
            total_buy_orders += 1
        elif side == "sell":
            total_sell_orders += 1

        oa_status = _translate_status(order.get("status"))
        if oa_status == "complete":
            total_completed_orders += 1
        elif oa_status == "open":
            total_open_orders += 1
        elif oa_status == "rejected":
            total_rejected_orders += 1

    return {
        "total_buy_orders": total_buy_orders,
        "total_sell_orders": total_sell_orders,
        "total_completed_orders": total_completed_orders,
        "total_open_orders": total_open_orders,
        "total_rejected_orders": total_rejected_orders,
    }


def transform_order_data(orders: Any) -> list[dict[str, Any]]:
    """Translate raw Alpaca order rows → OpenAlgo v1 orderbook rows."""
    if isinstance(orders, dict):
        orders = [orders]

    transformed: list[dict[str, Any]] = []
    for order in orders or []:
        if not isinstance(order, dict):
            logger.warning(
                f"Alpaca order_data: expected dict, got {type(order)}; skipping"
            )
            continue

        transformed.append({
            "symbol": order.get("symbol", ""),
            "exchange": order.get("exchange", "") or "NASDAQ",
            "action": _translate_action(order.get("side")),
            "quantity": _coerce_qty(order.get("qty", 0)),
            "price": _coerce_float(order.get("limit_price")),
            "trigger_price": _coerce_float(order.get("stop_price")),
            "pricetype": _translate_type(order.get("type")),
            "product": "CNC",  # Alpaca has no MIS/NRML — default to CNC
            "orderid": order.get("id", ""),
            "order_status": _translate_status(order.get("status")),
            "timestamp": order.get("created_at", "") or order.get("submitted_at", ""),
        })
    return transformed


# ---------------------------------------------------------------------------
# Trade book — map / transform
# ---------------------------------------------------------------------------


def map_trade_data(trade_data: Any) -> list[dict[str, Any]]:
    """Unwrap the envelope, same shape as ``map_order_data``."""
    return map_order_data(trade_data)


def transform_tradebook_data(tradebook_data: Any) -> list[dict[str, Any]]:
    """Translate Alpaca FILL activities → OpenAlgo v1 tradebook rows.

    Alpaca's ``/v2/account/activities/FILL`` returns one row per
    execution with fields:
      * ``id``, ``activity_type=FILL``, ``transaction_time``,
        ``order_id``, ``symbol``, ``side`` (``"buy"`` / ``"sell"``),
        ``qty``, ``price``, ``cum_qty``, ``leaves_qty``.
    """
    transformed: list[dict[str, Any]] = []
    for trade in tradebook_data or []:
        if not isinstance(trade, dict):
            continue
        qty = _coerce_qty(trade.get("qty", 0))
        avg_price = _coerce_float(trade.get("price"))
        # ``trade_value`` is signed-naive (always qty * price). Mirror
        # the Zerodha mapping which does the same.
        trade_value = (qty if isinstance(qty, (int, float)) else 0) * avg_price
        transformed.append({
            "symbol": trade.get("symbol", ""),
            "exchange": trade.get("exchange", "") or "NASDAQ",
            "product": "CNC",
            "action": _translate_action(trade.get("side")),
            "quantity": qty,
            "average_price": avg_price,
            "trade_value": trade_value,
            "orderid": trade.get("order_id", ""),
            "timestamp": trade.get("transaction_time", ""),
        })
    return transformed


# ---------------------------------------------------------------------------
# Position book — map / transform
# ---------------------------------------------------------------------------


def map_position_data(position_data: Any) -> list[dict[str, Any]]:
    """Unwrap the ``{"status": ..., "data": [...]}`` envelope into a list
    of raw Alpaca position rows.
    """
    if isinstance(position_data, dict):
        rows = position_data.get("data")
        if rows is None:
            logger.info("Alpaca: no position data available.")
            return []
    else:
        rows = position_data
    return list(rows) if rows else []


def transform_positions_data(positions_data: Any) -> list[dict[str, Any]]:
    """Translate Alpaca position rows → OpenAlgo v1 positionbook rows.

    Sign convention: Alpaca returns positive ``qty`` with a separate
    ``side``: ``"long"`` or ``"short"``. OpenAlgo v1 uses signed
    quantity (negative for short).
    """
    transformed: list[dict[str, Any]] = []
    for position in positions_data or []:
        if not isinstance(position, dict):
            continue
        side = (position.get("side") or "long").lower()
        raw_qty = _coerce_qty(position.get("qty", 0))
        # _coerce_qty may return int or float. Either way, negate for
        # a short side.
        signed_qty = -raw_qty if side == "short" and raw_qty else raw_qty
        avg_price = _coerce_float(position.get("avg_entry_price"))
        market_value = _coerce_float(position.get("market_value"))
        # LTP = market_value / qty when qty != 0; fallback to current
        # price field when Alpaca surfaces it.
        if raw_qty:
            ltp = abs(market_value / raw_qty) if raw_qty else 0.0
        else:
            ltp = _coerce_float(position.get("current_price"))
        transformed.append({
            "symbol": position.get("symbol", ""),
            "exchange": position.get("exchange", "") or "NASDAQ",
            "product": "CNC",
            "quantity": signed_qty,
            "pnl": round(_coerce_float(position.get("unrealized_pl")), 2),
            "average_price": "{:.2f}".format(avg_price),
            "ltp": round(ltp, 2),
        })
    return transformed


# ---------------------------------------------------------------------------
# Holdings — map / transform / portfolio statistics
# ---------------------------------------------------------------------------


def map_portfolio_data(portfolio_data: Any) -> list[dict[str, Any]]:
    """Unwrap the envelope. Same input shape as ``map_position_data``
    because Alpaca surfaces holdings via ``/v2/positions``.
    """
    return map_position_data(portfolio_data)


def transform_holdings_data(holdings_data: Any) -> list[dict[str, Any]]:
    """Translate Alpaca position rows → OpenAlgo v1 holdings rows.

    Differs from ``transform_positions_data`` by the v1 holdings
    schema: ``{symbol, exchange, quantity, product, average_price,
    pnl, pnlpercent}`` (no ``ltp``, adds ``pnlpercent``). Quantity is
    NOT signed for holdings (a "short holding" is meaningless); the
    legacy India v1 schema treats holdings as long-only delivery
    positions. We surface the absolute quantity here for parity.
    """
    transformed: list[dict[str, Any]] = []
    for h in holdings_data or []:
        if not isinstance(h, dict):
            continue
        avg_price = _coerce_float(h.get("avg_entry_price"))
        last_price = _coerce_float(h.get("current_price"))
        if last_price == 0.0:
            # Fall back to market_value / qty when current_price is
            # absent (older Alpaca responses).
            qty_for_ltp = _coerce_float(h.get("qty"))
            if qty_for_ltp:
                last_price = abs(_coerce_float(h.get("market_value")) / qty_for_ltp)

        if avg_price == 0:
            logger.debug(
                f"Alpaca holdings: zero avg_entry_price for {h.get('symbol', '?')}"
            )
            pnlpercent = 0.0
        else:
            pnlpercent = round((last_price - avg_price) / avg_price * 100, 2)

        transformed.append({
            "symbol": h.get("symbol", ""),
            "exchange": h.get("exchange", "") or "NASDAQ",
            "quantity": _coerce_qty(h.get("qty", 0)),
            "product": "CNC",
            "average_price": avg_price,
            "pnl": round(_coerce_float(h.get("unrealized_pl")), 2),
            "pnlpercent": pnlpercent,
        })
    return transformed


def calculate_portfolio_statistics(holdings_data: list[dict[str, Any]]) -> dict[str, float]:
    """Totals across all holdings — mirrors the Zerodha helper."""
    totalholdingvalue = 0.0
    totalinvvalue = 0.0
    totalprofitandloss = 0.0
    for h in holdings_data or []:
        # Use the original Alpaca shape if available (raw rows pre-transform);
        # transformed rows don't carry ``last_price`` / ``market_value``.
        last_price = _coerce_float(h.get("current_price")) or _coerce_float(h.get("last_price"))
        avg_price = _coerce_float(h.get("avg_entry_price")) or _coerce_float(h.get("average_price"))
        qty = _coerce_float(h.get("qty")) or _coerce_float(h.get("quantity"))
        totalholdingvalue += last_price * qty
        totalinvvalue += avg_price * qty
        totalprofitandloss += _coerce_float(h.get("unrealized_pl")) or _coerce_float(h.get("pnl"))

    totalpnlpercentage = (
        (totalprofitandloss / totalinvvalue * 100) if totalinvvalue else 0.0
    )
    return {
        "totalholdingvalue": round(totalholdingvalue, 2),
        "totalinvvalue": round(totalinvvalue, 2),
        "totalprofitandloss": round(totalprofitandloss, 2),
        "totalpnlpercentage": round(totalpnlpercentage, 2),
    }


__all__ = [
    "calculate_order_statistics",
    "calculate_portfolio_statistics",
    "map_order_data",
    "map_portfolio_data",
    "map_position_data",
    "map_trade_data",
    "transform_holdings_data",
    "transform_order_data",
    "transform_positions_data",
    "transform_tradebook_data",
]
