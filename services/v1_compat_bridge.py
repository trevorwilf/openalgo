"""v1 → v2 compatibility bridge for non-India brokers.

When a non-India broker session hits a legacy ``/api/v1/*`` endpoint
that has a documented v2 replacement, the lane guard delegates to
this bridge instead of returning the architectural 410 Gone. The
bridge:

  1. Authenticates the request the same way ``/api/v1`` does
     (apikey-in-body OR ``X-API-KEY`` header).
  2. Routes the call to the corresponding v2 dispatcher, translating
     the request body to the normalized shape.
  3. Translates the v2 response back into the v1 envelope the legacy
     React UI expects.

This keeps the existing UI (and external API consumers) functional on
non-India brokers without forcing a frontend refactor before the
operator's deadline. The architectural intent (ADR 0023, invariant 5
— non-India brokers never reach the legacy India services) is
preserved because the bridge dispatches through ``/api/v2`` end
state, not through ``services.quotes_service`` /
``services.place_order_service`` / etc.

Bridge entries are opt-in per path. Paths without a registered
bridge fall through to the original 410 behavior.
"""

from __future__ import annotations

from typing import Any, Callable

from flask import g, jsonify, request, session

from utils.logging import get_logger

logger = get_logger(__name__)


BridgeFn = Callable[[], tuple[Any, int]]


def _resolve_apikey() -> str | None:
    """v1 endpoints accept apikey in body or X-API-KEY header."""
    body = request.get_json(silent=True) or {}
    apikey = body.get("apikey") or request.headers.get("X-API-KEY")
    if apikey:
        return str(apikey)
    # Form-encoded fallback
    form_key = request.form.get("apikey") if request.form else None
    return str(form_key) if form_key else None


def _api_key_to_auth() -> tuple[str | None, str | None, str | None]:
    """Resolve (auth_token, broker, error_msg) the same way the v2
    ``resolve_auth`` helper does, but tolerant to v1's apikey-in-body
    convention.
    """
    apikey = _resolve_apikey()
    if not apikey:
        return None, None, "missing apikey"

    try:
        from database.auth_db import get_auth_token_broker

        auth_token, broker = get_auth_token_broker(apikey)
    except Exception as e:  # noqa: BLE001
        return None, None, f"apikey resolution failed: {e}"
    if not auth_token:
        return None, None, "invalid apikey"
    return auth_token, broker, None


def _v1_envelope(status: str = "success", **fields: Any) -> dict[str, Any]:
    """Standard v1 response shape: ``{status: "success", ...}``."""
    return {"status": status, **fields}


# ---------------------------------------------------------------------------
# Venue aliasing — accept the friendly US-exchange names the typical
# US trader knows (NASDAQ / NYSE / AMEX / BATS / ARCA) in addition to
# their canonical ISO 10383 MIC codes (XNAS / XNYS / ARCX / BATS).
# ---------------------------------------------------------------------------

_VENUE_ALIASES = {
    "NASDAQ": "XNAS",
    "NSDQ": "XNAS",
    "NMS": "XNAS",
    "OTC": "XNAS",
    "NYSE": "XNYS",
    "NYS": "XNYS",
    "AMEX": "XNYS",
    "ASE": "XNYS",
    "ARCA": "ARCX",
    "ARC": "ARCX",
    "BATS": "BATS",
    "BZX": "BATS",
    "CBOE": "BATS",
    # India-shaped codes occasionally leak in through legacy URL
    # construction; default to NASDAQ so the API at least resolves
    # rather than 404'ing.
    "NSE": "XNAS",
    "BSE": "XNYS",
}


def _alias_venue(raw: str | None) -> str:
    """Map a user-friendly exchange string to a canonical MIC code.

    Returns the input upper-cased if no alias matches, so canonical
    MIC codes (XNAS, XNYS, …) pass through unchanged.
    """
    if not raw:
        return "XNAS"
    upper = raw.upper().strip()
    return _VENUE_ALIASES.get(upper, upper)


def _v1_error(message: str, code: str | None = None) -> dict[str, Any]:
    return {
        "status": "error",
        **({"code": code} if code else {}),
        "message": message,
    }


# ---------------------------------------------------------------------------
# Per-endpoint bridges. Each returns a (json, http_status) tuple ready
# for Flask. Keep them tiny — they translate shapes and call into the
# Alpaca translator / adapters directly so the dispatch stays out of
# the v1 service modules entirely.
# ---------------------------------------------------------------------------


def _funds() -> tuple[Any, int]:
    auth_token, broker, err = _api_key_to_auth()
    if err:
        return jsonify(_v1_error(err)), 401

    if broker == "alpaca":
        from broker.alpaca.api.position_balance_adapters import (
            AlpacaBalanceAdapter,
        )

        try:
            balance = AlpacaBalanceAdapter().get_balance(
                {"broker_code": broker, "auth_token": auth_token}
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("v1 bridge funds failed: %s", e)
            return jsonify(_v1_error(str(e))), 502

        cash = float(balance.cash or 0)
        equity = float(balance.equity if balance.equity is not None else balance.cash or 0)
        used = float(balance.margin_used or 0)
        last_equity = balance.metadata.get("last_equity")
        try:
            intraday = equity - float(last_equity) if last_equity is not None else 0.0
        except (TypeError, ValueError):
            intraday = 0.0
        # Match the OpenAlgo widget shape used by /api/v1/funds today.
        return (
            jsonify(
                _v1_envelope(
                    data={
                        "availablecash": f"{cash:.2f}",
                        "collateral": "0.00",
                        "m2munrealized": f"{intraday:.2f}",
                        "m2mrealized": "0.00",
                        "utiliseddebits": f"{used:.2f}",
                    }
                )
            ),
            200,
        )

    return jsonify(_v1_error("v1 bridge not implemented for this broker")), 501


def _positionbook() -> tuple[Any, int]:
    auth_token, broker, err = _api_key_to_auth()
    if err:
        return jsonify(_v1_error(err)), 401

    if broker == "alpaca":
        from broker.alpaca.api.position_balance_adapters import (
            AlpacaPositionAdapter,
        )

        try:
            positions = AlpacaPositionAdapter().get_positions(
                {"broker_code": broker, "auth_token": auth_token}
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("v1 bridge positionbook failed: %s", e)
            return jsonify(_v1_error(str(e))), 502

        rows = [
            {
                "symbol": p.canonical_symbol,
                "exchange": p.venue_code,
                "quantity": str(p.quantity),
                "average_price": str(p.average_price) if p.average_price is not None else "0",
                "ltp": str(p.metadata.get("current_price") or "0"),
                "pnl": str(p.unrealized_pnl) if p.unrealized_pnl is not None else "0",
                "product": "MIS",  # v1 UI expects a product code; Alpaca has no equivalent
            }
            for p in positions
        ]
        return jsonify(_v1_envelope(data=rows)), 200

    return jsonify(_v1_error("v1 bridge not implemented for this broker")), 501


def _holdings() -> tuple[Any, int]:
    """Alpaca's snapshot doesn't carry T+N holdings the way Indian
    cash markets do. Return an empty holdings list with statistics
    as numeric zeros so the React UI's ``.toFixed()`` calls don't
    throw a runtime error.
    """
    auth_token, broker, err = _api_key_to_auth()
    if err:
        return jsonify(_v1_error(err)), 401

    return (
        jsonify(
            _v1_envelope(
                data={
                    "holdings": [],
                    "statistics": {
                        # Numeric, not stringified — the React Holdings
                        # page calls `.toFixed()` on each of these.
                        "totalholdingvalue": 0,
                        "totalinvvalue": 0,
                        "totalpnlpercentage": 0,
                        "totalprofitandloss": 0,
                    },
                }
            )
        ),
        200,
    )


def _orderbook() -> tuple[Any, int]:
    auth_token, broker, err = _api_key_to_auth()
    if err:
        return jsonify(_v1_error(err)), 401

    if broker == "alpaca":
        try:
            from broker.alpaca.api.order_api import AlpacaOrderTranslator

            translator = AlpacaOrderTranslator()
            rows = translator.list_orders_via_token(auth_token, status="all")
        except Exception as e:  # noqa: BLE001
            logger.exception("v1 bridge orderbook failed: %s", e)
            return jsonify(_v1_error(str(e))), 502

        orders = [_alpaca_order_to_v1(r) for r in rows]
        return (
            jsonify(
                _v1_envelope(
                    data={
                        "orders": orders,
                        "statistics": _v1_order_stats(orders),
                    }
                )
            ),
            200,
        )

    return jsonify(_v1_error("v1 bridge not implemented for this broker")), 501


def _tradebook() -> tuple[Any, int]:
    auth_token, broker, err = _api_key_to_auth()
    if err:
        return jsonify(_v1_error(err)), 401

    if broker == "alpaca":
        try:
            from broker.alpaca.api.order_api import AlpacaOrderTranslator
            from domain.enums import OrderStatus

            translator = AlpacaOrderTranslator()
            rows = translator.list_orders_via_token(auth_token, status="closed")
        except Exception as e:  # noqa: BLE001
            logger.exception("v1 bridge tradebook failed: %s", e)
            return jsonify(_v1_error(str(e))), 502

        # Tradebook = orders that produced fills, regardless of broker
        # vocabulary. Use the canonical status to filter.
        trades: list[dict[str, Any]] = []
        for r in rows:
            canonical = AlpacaOrderTranslator.normalize_order_status(r.get("status"))
            if canonical not in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
                continue
            if (r.get("filled_qty") or "0") in ("0", "0.0"):
                continue
            trades.append(_alpaca_order_to_v1(r, kind="trade"))
        return jsonify(_v1_envelope(data=trades)), 200

    return jsonify(_v1_error("v1 bridge not implemented for this broker")), 501


def _placeorder() -> tuple[Any, int]:
    auth_token, broker, err = _api_key_to_auth()
    if err:
        return jsonify(_v1_error(err)), 401

    if broker != "alpaca":
        return jsonify(_v1_error("v1 bridge not implemented for this broker")), 501

    body = request.get_json(silent=True) or {}
    # Translate v1 payload to NormalizedOrderRequest shape, then dispatch.
    try:
        normalized = _v1_order_to_normalized(body)
    except ValueError as e:
        return jsonify(_v1_error(str(e), code="bad_request")), 400

    # Dispatch through the v2 promoted route by calling the dispatcher
    # function directly (avoids spinning a second HTTP request).
    from restx_api.v2._auth import error as v2_error  # noqa: F401
    from restx_api.v2.orders import _dispatch_promoted
    from services.broker_translator_registry import get_broker_translator

    translator = get_broker_translator(broker)
    if translator is None:
        return jsonify(_v1_error("alpaca translator not registered", code="translator_not_registered")), 503

    # _dispatch_promoted returns (json_dict, status). The json_dict is
    # the v2 envelope; we re-shape into v1's {status, orderid}.
    resp_dict, status_code = _dispatch_promoted(
        normalized, broker=broker, auth_token=auth_token, promoted=translator
    )
    if status_code >= 400:
        # Promoted dispatcher already returns a structured error envelope
        # under either ``error.message`` or top-level ``message`` keys.
        return jsonify(_v2_error_to_v1(resp_dict)), status_code

    inner = resp_dict.get("data") or resp_dict
    order_id = inner.get("order_id") or ""

    # Publish OrderPlacedEvent so the SocketIO subscriber pushes a
    # live update to the React UI's order book without polling. The
    # async trade_updates stream catches externally-initiated orders;
    # this synchronous publish covers the self-initiated path so the
    # UI updates the instant the bridge returns.
    try:
        from events import OrderPlacedEvent
        from utils.event_bus import bus

        bus.publish(
            OrderPlacedEvent(
                mode="live",
                api_type="placeorder",
                strategy=str(body.get("strategy") or "ui"),
                symbol=str(body.get("symbol") or "").upper(),
                exchange=str(body.get("exchange") or "XNAS").upper(),
                action=str(body.get("action") or "").upper(),
                quantity=int(float(body.get("quantity") or 0)),
                pricetype=str(body.get("price_type") or body.get("pricetype") or "").upper(),
                product=str(body.get("product") or "MIS").upper(),
                orderid=order_id,
                request_data=body,
                response_data={"orderid": order_id},
                api_key=str(body.get("apikey") or ""),
            )
        )
    except Exception:  # noqa: BLE001 - never break the order path on observability
        logger.exception("v1 bridge: OrderPlacedEvent publish failed")

    return (
        jsonify(_v1_envelope(orderid=order_id)),
        200,
    )


def _cancelorder() -> tuple[Any, int]:
    auth_token, broker, err = _api_key_to_auth()
    if err:
        return jsonify(_v1_error(err)), 401

    if broker != "alpaca":
        return jsonify(_v1_error("v1 bridge not implemented for this broker")), 501

    body = request.get_json(silent=True) or {}
    order_id = body.get("orderid") or body.get("order_id")
    if not order_id:
        return jsonify(_v1_error("orderid required")), 400

    try:
        from broker.alpaca.api.order_api import AlpacaOrderTranslator

        translator = AlpacaOrderTranslator()
        translator.cancel_order_via_token(auth_token, order_id)
    except Exception as e:  # noqa: BLE001
        logger.exception("v1 bridge cancel failed: %s", e)
        return jsonify(_v1_error(str(e))), 502

    # Synchronous event so the React orderbook updates immediately.
    try:
        from events import OrderCancelledEvent
        from utils.event_bus import bus

        bus.publish(
            OrderCancelledEvent(
                mode="live",
                api_type="cancelorder",
                orderid=order_id,
                status="canceled",
                request_data={"orderid": order_id},
                response_data={"status": "success"},
                api_key=str(body.get("apikey") or ""),
            )
        )
    except Exception:  # noqa: BLE001
        logger.exception("v1 bridge: OrderCancelledEvent publish failed")

    return jsonify(_v1_envelope(orderid=order_id)), 200


def _multiquotes() -> tuple[Any, int]:
    """``POST /api/v1/multiquotes`` — fetch one quote per (symbol, exchange).

    The legacy v1 shape is ``{apikey, symbols: [{symbol, exchange}, …]}``
    returning ``{status, results: [{symbol, exchange, data: QuotesData}]}``.
    Bridges through Alpaca's quote adapter — one HTTP call per
    symbol (Alpaca doesn't expose a batch latest-quote endpoint for
    arbitrary symbol lists, but the REST calls are fast).
    """
    auth_token, broker, err = _api_key_to_auth()
    if err:
        return jsonify(_v1_error(err)), 401
    if broker != "alpaca":
        return jsonify(_v1_error("v1 bridge not implemented for this broker")), 501

    body = request.get_json(silent=True) or {}
    symbols = body.get("symbols") or []
    if not isinstance(symbols, list):
        return jsonify(_v1_error("symbols must be a list")), 400

    try:
        from broker.alpaca.api.auth_api import auth_handle_from_token
        from broker.alpaca.api.quote_api import AlpacaQuoteAdapter
        from domain.instrument_ref import InstrumentRef
        from services.instrument_resolution import resolve_instrument

        auth = auth_handle_from_token(auth_token)
        adapter = AlpacaQuoteAdapter(auth=auth)
        account_ctx = {
            "broker_code": "alpaca",
            "auth_token": auth_token,
            "base_currency": "USD",
        }
    except Exception as e:  # noqa: BLE001
        logger.exception("v1 bridge multiquotes setup failed: %s", e)
        return jsonify(_v1_error(str(e))), 502

    results: list[dict[str, Any]] = []
    for entry in symbols:
        if not isinstance(entry, dict):
            continue
        sym = (entry.get("symbol") or "").upper()
        ex = _alias_venue(entry.get("exchange"))
        if not sym:
            continue
        try:
            ref = InstrumentRef(venue_code=ex, canonical_symbol=sym)
            resolved = resolve_instrument(ref, broker_code="alpaca")
            if resolved is None:
                continue
            quote = adapter.get_quote(resolved, account_ctx)
        except Exception as e:  # noqa: BLE001
            logger.warning("multiquotes %s@%s failed: %s", sym, ex, e)
            continue
        last = float(quote.last) if quote.last is not None else 0.0
        results.append(
            {
                "symbol": sym,
                "exchange": ex,
                "data": {
                    "ask": float(quote.ask) if quote.ask is not None else 0.0,
                    "bid": float(quote.bid) if quote.bid is not None else 0.0,
                    "high": last,
                    "low": last,
                    "ltp": last,
                    "oi": 0,
                    "open": last,
                    "prev_close": last,
                    "volume": 0,
                },
            }
        )

    # multiquotes uses {results: ...} at the top level (NOT under
    # `data`). Mirroring that exactly so the React MarketDataManager
    # parses the shape it already expects.
    return jsonify({"status": "success", "results": results}), 200


def _history() -> tuple[Any, int]:
    """``POST /api/v1/history`` — historical OHLCV bars.

    Legacy shape: ``{apikey, symbol, exchange, interval, start_date,
    end_date}`` returning ``{status, data: [{timestamp, open, high,
    low, close, volume}, …]}``. Bridges to the Alpaca bar adapter
    with the v2-canonical interval vocabulary.
    """
    auth_token, broker, err = _api_key_to_auth()
    if err:
        return jsonify(_v1_error(err)), 401
    if broker != "alpaca":
        return jsonify(_v1_error("v1 bridge not implemented for this broker")), 501

    body = request.get_json(silent=True) or {}
    sym = (body.get("symbol") or "").upper()
    ex = _alias_venue(body.get("exchange"))
    interval_in = (body.get("interval") or "").strip()
    start_date = (body.get("start_date") or "").strip()
    end_date = (body.get("end_date") or "").strip()

    if not (sym and interval_in and start_date and end_date):
        return jsonify(_v1_error(
            "symbol, interval, start_date and end_date are required"
        )), 400

    # Map the v1 interval vocabulary (1m / 5m / 15m / 30m / 1h / D)
    # to the canonical promoted-lane interval vocabulary the Alpaca
    # bar adapter consumes.
    _INTERVAL_MAP = {
        "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
        "1h": "1h", "1H": "1h",
        "D": "1d", "1D": "1d", "d": "1d", "1d": "1d",
        "W": "1w", "1W": "1w", "1w": "1w",
        "M": "1mo", "1M": "1mo", "1mo": "1mo",
    }
    interval = _INTERVAL_MAP.get(interval_in)
    if interval is None:
        return jsonify(_v1_error(
            f"interval {interval_in!r} not supported by Alpaca bridge "
            f"(supported: {sorted(set(_INTERVAL_MAP)).__repr__()})"
        )), 400

    try:
        from datetime import datetime, time, timezone

        from broker.alpaca.api.auth_api import auth_handle_from_token
        from broker.alpaca.api.bar_api import AlpacaBarAdapter
        from domain.broker_market_data import NormalizedBarRequest
        from domain.instrument_ref import InstrumentRef
        from services.instrument_resolution import resolve_instrument

        # Date strings are YYYY-MM-DD; treat as UTC midnight to
        # match the legacy India semantics (which used IST midnight,
        # but Alpaca's data is UTC-stamped and the operator picks
        # the interval — close enough for paper trading).
        start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
        end_dt = datetime.combine(
            datetime.fromisoformat(end_date).date(),
            time(23, 59, 59),
            tzinfo=timezone.utc,
        )
    except Exception as e:  # noqa: BLE001
        return jsonify(_v1_error(f"invalid date format: {e}")), 400

    try:
        auth = auth_handle_from_token(auth_token)
        adapter = AlpacaBarAdapter(auth=auth)
        ref = InstrumentRef(venue_code=ex, canonical_symbol=sym)
        resolved = resolve_instrument(ref, broker_code="alpaca")
        if resolved is None:
            return jsonify(_v1_error(f"instrument not in universe: {sym}@{ex}")), 404
        account_ctx = {
            "broker_code": "alpaca",
            "auth_token": auth_token,
            "base_currency": "USD",
        }
        bars = adapter.get_bars(
            resolved,
            NormalizedBarRequest(interval=interval, start=start_dt, end=end_dt),
            account_ctx,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("v1 bridge history failed: %s", e)
        return jsonify(_v1_error(str(e))), 502

    rows = [
        {
            "timestamp": int(bar.ts.timestamp()),
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": int(float(bar.volume)) if bar.volume is not None else 0,
        }
        for bar in bars
    ]
    return jsonify(_v1_envelope(data=rows)), 200


def _depth() -> tuple[Any, int]:
    """``POST /api/v1/depth`` — order-book depth for a symbol.

    Alpaca's free IEX feed doesn't expose multi-level book depth — only
    top-of-book bid/ask. We synthesize a single-level depth response
    so the React MarketDepthPanel renders something useful (and
    non-empty). Operators with a SIP subscription get the same call
    pattern; future work can fetch deeper levels when the broker
    plugin advertises that capability.
    """
    auth_token, broker, err = _api_key_to_auth()
    if err:
        return jsonify(_v1_error(err)), 401
    if broker != "alpaca":
        return jsonify(_v1_error("v1 bridge not implemented for this broker")), 501

    body = request.get_json(silent=True) or {}
    sym = (body.get("symbol") or "").upper()
    ex = _alias_venue(body.get("exchange"))
    if not sym:
        return jsonify(_v1_error("symbol required")), 400

    try:
        from broker.alpaca.api.auth_api import auth_handle_from_token
        from broker.alpaca.api.quote_api import AlpacaQuoteAdapter
        from domain.instrument_ref import InstrumentRef
        from services.instrument_resolution import resolve_instrument

        auth = auth_handle_from_token(auth_token)
        adapter = AlpacaQuoteAdapter(auth=auth)
        ref = InstrumentRef(venue_code=ex, canonical_symbol=sym)
        resolved = resolve_instrument(ref, broker_code="alpaca")
        if resolved is None:
            return jsonify(_v1_error(f"instrument not in universe: {sym}@{ex}")), 404
        account_ctx = {
            "broker_code": "alpaca",
            "auth_token": auth_token,
            "base_currency": "USD",
        }
        quote = adapter.get_quote(resolved, account_ctx)
    except Exception as e:  # noqa: BLE001
        logger.exception("v1 bridge depth failed: %s", e)
        return jsonify(_v1_error(str(e))), 502

    last = float(quote.last) if quote.last is not None else 0.0
    bid = float(quote.bid) if quote.bid is not None else 0.0
    ask = float(quote.ask) if quote.ask is not None else 0.0
    bid_size = float(quote.bid_size) if quote.bid_size is not None else 0.0
    ask_size = float(quote.ask_size) if quote.ask_size is not None else 0.0

    return (
        jsonify(
            _v1_envelope(
                data={
                    "asks": [{"price": ask, "quantity": int(ask_size)}],
                    "bids": [{"price": bid, "quantity": int(bid_size)}],
                    "high": last,
                    "low": last,
                    "ltp": last,
                    "ltq": 0,
                    "oi": 0,
                    "open": last,
                    "prev_close": last,
                    "totalbuyqty": int(bid_size),
                    "totalsellqty": int(ask_size),
                    "volume": 0,
                }
            )
        ),
        200,
    )


def _quotes() -> tuple[Any, int]:
    auth_token, broker, err = _api_key_to_auth()
    if err:
        return jsonify(_v1_error(err)), 401

    if broker != "alpaca":
        return jsonify(_v1_error("v1 bridge not implemented for this broker")), 501

    body = request.get_json(silent=True) or {}
    symbol = (body.get("symbol") or "").upper()
    exchange = (body.get("exchange") or "").upper()
    if not symbol:
        return jsonify(_v1_error("symbol required")), 400

    venue = _alias_venue(exchange) if exchange else "XNAS"

    try:
        from broker.alpaca.api.auth_api import auth_handle_from_token
        from broker.alpaca.api.quote_api import AlpacaQuoteAdapter
        from domain.instrument_ref import InstrumentRef
        from services.instrument_resolution import resolve_instrument

        auth = auth_handle_from_token(auth_token)
        adapter = AlpacaQuoteAdapter(auth=auth)
        ref = InstrumentRef(venue_code=venue, canonical_symbol=symbol)
        resolved = resolve_instrument(ref, broker_code="alpaca")
        if resolved is None:
            return jsonify(_v1_error(f"instrument not in universe: {symbol}@{venue}")), 404
        account_ctx = {
            "broker_code": "alpaca",
            "auth_token": auth_token,
            "base_currency": "USD",
        }
        quote = adapter.get_quote(resolved, account_ctx)
    except Exception as e:  # noqa: BLE001
        logger.exception("v1 bridge quotes failed: %s", e)
        return jsonify(_v1_error(str(e))), 502

    if quote is None:
        return jsonify(_v1_error(f"quote unavailable for {symbol}")), 404

    last = float(quote.last) if quote.last is not None else 0.0
    return (
        jsonify(
            _v1_envelope(
                data={
                    "ask": float(quote.ask) if quote.ask is not None else 0.0,
                    "bid": float(quote.bid) if quote.bid is not None else 0.0,
                    "high": last,
                    "low": last,
                    "ltp": last,
                    "oi": 0,
                    "open": last,
                    "prev_close": last,
                    "volume": 0,
                }
            )
        ),
        200,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _alpaca_order_to_v1(row: dict, *, kind: str = "order") -> dict[str, Any]:
    """Translate an Alpaca order row into the v1 orderbook/tradebook
    shape the React UI expects.

    Status mapping goes through the canonical
    :class:`domain.enums.OrderStatus` so the legacy display vocabulary
    ("open" / "complete" / "cancelled" / "rejected" / "trigger pending")
    matches what the Indian React components rendered for v1 brokers.
    The native Alpaca string is preserved under ``native_status`` for
    debugging.
    """
    from broker.alpaca.api.order_api import AlpacaOrderTranslator
    from services.order_status_display import legacy_v1_display

    qty_filled = row.get("filled_qty") or "0"
    qty_total = row.get("qty") or "0"
    native_status = row.get("status") or ""
    canonical = AlpacaOrderTranslator.normalize_order_status(native_status)
    base = {
        "orderid": row.get("id"),
        "symbol": row.get("symbol"),
        "exchange": (row.get("asset_class") == "us_equity" and "XNAS") or "XNAS",
        "action": (row.get("side") or "").upper(),
        "quantity": qty_total,
        "filled_quantity": qty_filled,
        "price": row.get("limit_price") or row.get("filled_avg_price") or "0",
        "trigger_price": row.get("stop_price") or "0",
        "average_price": row.get("filled_avg_price") or "0",
        "order_status": legacy_v1_display(canonical),
        "canonical_status": canonical.value,
        "native_status": native_status,
        "order_type": (row.get("type") or "").upper(),
        "product": "MIS",
        "timestamp": row.get("created_at"),
    }
    if kind == "trade":
        base["trade_value"] = (
            float(qty_filled) * float(row.get("filled_avg_price") or 0)
        )
    return base


def _v1_order_stats(orders: list[dict]) -> dict[str, Any]:
    """Compute orderbook summary counts from the legacy display vocab."""
    open_count = sum(1 for o in orders if o["order_status"] == "open")
    filled_count = sum(1 for o in orders if o["order_status"] == "complete")
    cancelled_count = sum(
        1 for o in orders if o["order_status"] in ("cancelled", "rejected")
    )
    return {
        "total_buy_orders": sum(1 for o in orders if o["action"] == "BUY"),
        "total_sell_orders": sum(1 for o in orders if o["action"] == "SELL"),
        "total_completed_orders": filled_count,
        "total_open_orders": open_count,
        "total_rejected_orders": cancelled_count,
    }


def _v1_order_to_normalized(body: dict) -> Any:
    """Map a v1 placeorder body to a NormalizedOrderRequest.

    Handles three Alpaca-specific shapes the legacy v1 contract didn't
    cover:

    * **Fractional shares** — ``quantity`` may now be a decimal (e.g.
      ``"0.5"``); when fractional, ``quantity_unit`` is ``FRACTIONAL``
      so the v2 dispatcher's broker-rule check passes.
    * **Notional orders** — ``notional=true`` (or non-empty
      ``"notional"`` field) flips ``quantity_unit`` to ``NOTIONAL``
      so ``quantity`` is interpreted as a USD amount instead of a
      share count.
    * **Extended hours** — the v1 caller can pass ``extended_hours=true``
      to place pre/post-market orders (Alpaca's ``extended_hours``
      bit). Passes through to the canonical
      ``NormalizedOrderRequest.extended_hours`` field.
    """
    from decimal import Decimal

    from domain.instrument_ref import InstrumentRef
    from domain.orders import NormalizedOrderRequest

    symbol = (body.get("symbol") or "").upper()
    exchange = _alias_venue(body.get("exchange") or "XNAS")
    action = (body.get("action") or "BUY").upper()
    pricetype = (body.get("price_type") or body.get("pricetype") or "MARKET").upper()
    quantity = body.get("quantity") or "1"
    price = body.get("price")
    if not symbol:
        raise ValueError("symbol required")

    pricetype_map = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "STOP_LIMIT",
        "SL-M": "STOP",
    }
    order_type = pricetype_map.get(pricetype, pricetype)

    # ---- quantity_unit selection ----------------------------------
    notional_flag = body.get("notional")
    is_notional = (
        bool(notional_flag) and str(notional_flag).strip().lower() not in ("0", "false", "")
    )

    if is_notional:
        quantity_unit = "NOTIONAL"
    else:
        # Detect fractional via the quantity string's content rather
        # than a flag — operators may submit ``"0.5"`` or ``"1.25"``
        # without setting any explicit "fractional" toggle.
        try:
            qty_decimal = Decimal(str(quantity))
            quantity_unit = "FRACTIONAL" if qty_decimal != qty_decimal.to_integral_value() else "WHOLE"
        except Exception:  # noqa: BLE001
            quantity_unit = "WHOLE"

    # ---- extended_hours flag --------------------------------------
    eh_raw = body.get("extended_hours")
    extended_hours = bool(eh_raw) and str(eh_raw).strip().lower() not in (
        "0", "false", "",
    )

    return NormalizedOrderRequest(
        instrument=InstrumentRef(venue_code=exchange, canonical_symbol=symbol),
        side=action,
        order_type=order_type,
        quantity=Decimal(str(quantity)),
        quantity_unit=quantity_unit,
        price=(Decimal(str(price)) if price not in (None, "", "0") and order_type != "MARKET" else None),
        time_in_force="DAY",
        extended_hours=extended_hours,
    )


def _v2_error_to_v1(resp: Any) -> dict[str, Any]:
    """Squash a v2 error envelope into v1's {status:error, message}."""
    if isinstance(resp, dict):
        err = resp.get("error") or {}
        msg = err.get("message") or resp.get("message") or "broker error"
        code = err.get("code") or resp.get("code")
        return _v1_error(msg, code=code)
    return _v1_error(str(resp))


# ---------------------------------------------------------------------------
# Bridge dispatch table.
# ---------------------------------------------------------------------------

BRIDGES: dict[str, BridgeFn] = {
    "/api/v1/funds": _funds,
    "/api/v1/funds/": _funds,
    "/api/v1/positionbook": _positionbook,
    "/api/v1/positionbook/": _positionbook,
    "/api/v1/holdings": _holdings,
    "/api/v1/holdings/": _holdings,
    "/api/v1/orderbook": _orderbook,
    "/api/v1/orderbook/": _orderbook,
    "/api/v1/tradebook": _tradebook,
    "/api/v1/tradebook/": _tradebook,
    "/api/v1/placeorder": _placeorder,
    "/api/v1/placeorder/": _placeorder,
    "/api/v1/cancelorder": _cancelorder,
    "/api/v1/cancelorder/": _cancelorder,
    "/api/v1/quotes": _quotes,
    "/api/v1/quotes/": _quotes,
    "/api/v1/multiquotes": _multiquotes,
    "/api/v1/multiquotes/": _multiquotes,
    "/api/v1/depth": _depth,
    "/api/v1/depth/": _depth,
    "/api/v1/history": _history,
    "/api/v1/history/": _history,
}


def try_bridge(broker: str | None, path: str | None) -> tuple[Any, int] | None:
    """Return ``(json, status)`` if a bridge handles the (broker, path)
    pair, else ``None`` so the caller can fall back to the architectural
    410 Gone response.
    """
    if not broker or not path:
        return None
    if broker.lower() != "alpaca":
        # Only Alpaca is bridged for now. Other non-India brokers
        # continue to receive the 410 architectural error.
        return None
    bridge = BRIDGES.get(path)
    if bridge is None:
        return None
    try:
        return bridge()
    except Exception as e:  # noqa: BLE001
        logger.exception("v1 bridge crashed for %s: %s", path, e)
        return jsonify(_v1_error(str(e))), 500


__all__ = ["BRIDGES", "try_bridge"]
