"""Alpaca order translator + HTTP order operations.

Implements :class:`~domain.broker_translator.BrokerOrderTranslator` for
the promoted-lane ``/api/v2/orders`` dispatcher, plus the direct
HTTP helpers ``place_order``, ``get_order_status``, ``cancel_order``.

Scope (post-Branches I/J/K/L):
  * US equities + ETFs (XNAS, XNYS, ARCX, BATS).
  * Order types: MARKET, LIMIT, STOP, STOP_LIMIT, TRAILING_STOP,
    MARKET_ON_OPEN, LIMIT_ON_OPEN, MARKET_ON_CLOSE, LIMIT_ON_CLOSE.
  * Time in force: DAY, GTC, IOC, FOK, OPG, ATC.
  * Sessions: REGULAR, PRE_MARKET, POST_MARKET, EXTENDED.
  * Combo orders: SINGLE, OTO, OCO, OTOCO (bracket).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx

from broker.alpaca.api.auth_api import AlpacaAuth, authenticate
from domain.broker_translator import AccountContext
from domain.enums import (
    ComboType,
    OrderSide,
    OrderStatus,
    OrderType,
    QuantityUnit,
    Session,
    TimeInForce,
)
from domain.errors import UnsupportedCapability

# Branch N — single source of truth for vocabulary mapping lives in
# ``broker.alpaca.mapping.transform_data``. The translator imports
# the tables it needs rather than maintaining inline duplicates.
from broker.alpaca.mapping.transform_data import (
    AUCTION_ORDER_TYPES,
    COMBO_TYPE_TO_ALPACA,
    CRYPTO_VENUES as _CRYPTO_VENUES,
    EXTENDED_HOURS_SESSIONS as _EXTENDED_HOURS_SESSIONS,
    LIMIT_PRICED_ORDER_TYPES as _LIMIT_PRICED,
    ORDER_TYPE_NATIVE as _ORDER_TYPE_NATIVE,
    STOP_PRICED_ORDER_TYPES as _STOP_PRICED,
    SUPPORTED_COMBO_TYPES as _SUPPORTED_COMBO_TYPES,
    SUPPORTED_ORDER_TYPES as _ROUND_TRIPPABLE_ORDER_TYPES,
    SUPPORTED_SESSIONS as _SUPPORTED_SESSIONS,
    SUPPORTED_TIF as _SUPPORTED_TIF,
    SUPPORTED_VENUES as _SUPPORTED_VENUES,
    TIF_TO_ALPACA as _TIF_NATIVE,
)


# The translator accepts ROUND-TRIPPABLE simple types PLUS the
# auction collapse types from mapping/transform_data. Both unions
# come from canonical tables — no inline duplicates.
_SUPPORTED_TYPES = _ROUND_TRIPPABLE_ORDER_TYPES | AUCTION_ORDER_TYPES

# Translator accepts the round-trippable real venues plus the
# synthetic CRYPTO venue. mapping/transform_data's SUPPORTED_VENUES
# tracks round-trippable real venues only; CRYPTO is broker-
# namespaced and lives in CRYPTO_VENUES.
_SUPPORTED_VENUES = _SUPPORTED_VENUES | _CRYPTO_VENUES


class _ComboLegOrder:
    """Order-shaped view of a combo ``OrderLeg`` for ``validate()``.

    A combo leg only carries per-leg fields (side, order_type, qty,
    price, trigger_price); ``time_in_force`` and ``session`` live on
    the parent ``NormalizedComboOrderRequest``. ``validate()`` reads
    both flavors of field, so this lightweight wrapper composes them
    into a single object per leg without mutating the immutable
    pydantic models.
    """

    __slots__ = (
        "order_type",
        "time_in_force",
        "session",
        "quantity_unit",
        "extended_hours",
    )

    def __init__(self, combo: Any, leg: Any) -> None:
        self.order_type = leg.order_type
        self.time_in_force = combo.time_in_force
        self.session = combo.session
        self.quantity_unit = leg.quantity_unit
        self.extended_hours = bool((combo.metadata or {}).get("extended_hours"))


class AlpacaOrderTranslator:
    broker_code = "alpaca"

    def __init__(
        self,
        auth: AlpacaAuth | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._auth = auth
        self._client = client

    # ---- BrokerOrderTranslator surface ---------------------------------

    def validate(
        self,
        order: Any,
        instrument: Any,
        account_ctx: AccountContext,
    ) -> None:
        if instrument is not None and instrument.venue_code not in _SUPPORTED_VENUES:
            raise UnsupportedCapability(
                broker_code=self.broker_code,
                capability_name="venue",
                details=(
                    f"Alpaca does not trade venue "
                    f"{instrument.venue_code!r}"
                ),
            )
        if order.order_type not in _SUPPORTED_TYPES:
            supported = sorted(t.value for t in _SUPPORTED_TYPES)
            raise UnsupportedCapability(
                broker_code=self.broker_code,
                capability_name="order_type",
                details=(
                    f"Alpaca supports order types {supported}; got "
                    f"{order.order_type.value}"
                ),
            )
        if order.time_in_force not in _SUPPORTED_TIF:
            supported_tif = sorted(t.value for t in _SUPPORTED_TIF)
            raise UnsupportedCapability(
                broker_code=self.broker_code,
                capability_name="time_in_force",
                details=(
                    f"Alpaca supports time-in-force {supported_tif}; got "
                    f"{order.time_in_force.value}"
                ),
            )
        if order.session not in _SUPPORTED_SESSIONS:
            raise UnsupportedCapability(
                broker_code=self.broker_code,
                capability_name="session",
                details=(
                    f"Alpaca supports REGULAR / PRE_MARKET / POST_MARKET / "
                    f"EXTENDED sessions; got {order.session.value}"
                ),
            )
        # Alpaca's extended-hours flag is only valid on LIMIT-priced
        # orders with TIF=DAY (per their REST docs). Fail-fast if the
        # combination is illegal — saves a round-trip to the broker.
        if order.session in _EXTENDED_HOURS_SESSIONS:
            if order.order_type not in {OrderType.LIMIT}:
                raise UnsupportedCapability(
                    broker_code=self.broker_code,
                    capability_name="extended_hours_order_type",
                    details=(
                        "Alpaca extended-hours orders must be type=LIMIT "
                        "(per Alpaca REST docs); got "
                        f"{order.order_type.value}"
                    ),
                )
            if order.time_in_force != TimeInForce.DAY:
                raise UnsupportedCapability(
                    broker_code=self.broker_code,
                    capability_name="extended_hours_time_in_force",
                    details=(
                        "Alpaca extended-hours orders must use TIF=DAY "
                        "(per Alpaca REST docs); got "
                        f"{order.time_in_force.value}"
                    ),
                )
        if order.quantity_unit == QuantityUnit.LOTS:
            raise UnsupportedCapability(
                broker_code=self.broker_code,
                capability_name="quantity_unit",
                details="Alpaca does not support LOTS",
            )

    def to_native(
        self,
        order: Any,
        instrument: Any,
        account_ctx: AccountContext,
    ) -> dict[str, Any]:
        symbol = (
            instrument.broker_native_symbol
            if (instrument is not None and instrument.broker_native_symbol)
            else (
                instrument.canonical_symbol
                if instrument is not None
                else (order.instrument.canonical_symbol or "")
            )
        )
        # Branch M — crypto symbols: OpenAlgo canonical form uses '-'
        # (BTC-USD), Alpaca's REST API uses '/' (BTC/USD). Substitute
        # only when routing to the CRYPTO venue so equity tickers
        # that happen to contain '-' are unaffected.
        if (
            instrument is not None
            and instrument.venue_code in _CRYPTO_VENUES
            and "-" in symbol
        ):
            symbol = symbol.replace("-", "/")
        side = "buy" if order.side == OrderSide.BUY else "sell"
        body: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": _ORDER_TYPE_NATIVE[order.order_type],
            "time_in_force": _TIF_NATIVE[order.time_in_force],
        }
        if order.quantity_unit == QuantityUnit.NOTIONAL:
            body["notional"] = str(order.quantity)
        else:
            body["qty"] = str(order.quantity)

        # LIMIT, STOP_LIMIT, LIMIT_ON_OPEN, LIMIT_ON_CLOSE all carry
        # a limit price (the auction variants collapse to type=limit
        # at the wire level, so they need the same payload field).
        # Branch N — _LIMIT_PRICED comes from mapping/transform_data.
        if order.order_type in _LIMIT_PRICED:
            if order.price is None:
                raise UnsupportedCapability(
                    broker_code=self.broker_code,
                    capability_name="limit_price",
                    details=(
                        f"{order.order_type.value} order requires a price"
                    ),
                )
            body["limit_price"] = str(order.price)

        # STOP and STOP_LIMIT carry a stop trigger.
        # Branch N — _STOP_PRICED comes from mapping/transform_data.
        if order.order_type in _STOP_PRICED:
            if order.trigger_price is None:
                # The domain validator prevents this from happening,
                # but the explicit guard makes the failure mode clear
                # if a future caller bypasses NormalizedOrderRequest.
                raise UnsupportedCapability(
                    broker_code=self.broker_code,
                    capability_name="stop_price",
                    details=(
                        f"{order.order_type.value} order requires a "
                        "trigger_price"
                    ),
                )
            body["stop_price"] = str(order.trigger_price)

        # TRAILING_STOP carries a trailing offset. OpenAlgo's
        # ``trailing_offset`` is a single Decimal — by default it
        # maps to Alpaca's ``trail_price`` (dollar amount). The
        # operator can flip to percent semantics by setting
        # ``order.extra["alpaca_trail_unit"] = "percent"``.
        if order.order_type == OrderType.TRAILING_STOP:
            offset = order.trailing_offset
            if offset is None:
                raise UnsupportedCapability(
                    broker_code=self.broker_code,
                    capability_name="trailing_offset",
                    details="TRAILING_STOP order requires trailing_offset",
                )
            unit = (
                getattr(order, "extra", {}) or {}
            ).get("alpaca_trail_unit", "price")
            if unit == "percent":
                body["trail_percent"] = str(offset)
            else:
                body["trail_price"] = str(offset)

        # Extended-hours flag — two paths feed into Alpaca's
        # ``extended_hours: true`` body bit:
        #
        #   * Session-based (Branch K legacy): the operator picked
        #     PRE_MARKET / POST_MARKET / EXTENDED via the session enum.
        #   * Field-based (modern v2 dialog): the operator toggled the
        #     ``extended_hours`` boolean independently of the session.
        #
        # Crypto trades 24/7 with no auction phases, so the flag is
        # silently dropped on crypto venues (Branch M).
        is_crypto_venue = (
            instrument is not None and instrument.venue_code in _CRYPTO_VENUES
        )
        wants_extended = (
            order.session in _EXTENDED_HOURS_SESSIONS
            or getattr(order, "extended_hours", False)
        )
        if wants_extended and not is_crypto_venue:
            body["extended_hours"] = True

        if order.client_order_id:
            body["client_order_id"] = order.client_order_id

        return body

    # ---- Branch L — combo / bracket order surface ---------------------

    def validate_combo(
        self,
        combo: Any,
        instruments_by_leg: list[Any],
        account_ctx: AccountContext,
    ) -> None:
        """Validate a NormalizedComboOrderRequest against Alpaca's
        bracket / OCO / OTO constraints before serializing.

        Reuses validate() for each leg's per-leg constraints (venue,
        order type, etc.) then layers combo-specific shape checks:

          * combo_type must be one of SINGLE / OTO / OCO / OTOCO.
          * SINGLE: exactly 1 leg.
          * OTO: 2 legs (parent + child).
          * OCO: 2 legs (parent LIMIT + stop child).
          * OTOCO (bracket): 3 legs (parent + take_profit LIMIT + stop_loss).
        """
        if combo.combo_type not in _SUPPORTED_COMBO_TYPES:
            raise UnsupportedCapability(
                broker_code=self.broker_code,
                capability_name="combo_type",
                details=(
                    f"Alpaca supports SINGLE / OTO / OCO / OTOCO; got "
                    f"{combo.combo_type.value}"
                ),
            )
        expected_legs = {
            ComboType.SINGLE: 1,
            ComboType.OTO: 2,
            ComboType.OCO: 2,
            ComboType.OTOCO: 3,
            # BRACKET is the canonical name for parent + take-profit
            # + stop-loss. At Alpaca it serializes to the same
            # `order_class=bracket` as OTOCO; the translator accepts
            # either form so operators using the clearer name don't
            # have to translate it themselves.
            ComboType.BRACKET: 3,
        }[combo.combo_type]
        if len(combo.legs) != expected_legs:
            raise UnsupportedCapability(
                broker_code=self.broker_code,
                capability_name="combo_leg_count",
                details=(
                    f"Alpaca {combo.combo_type.value} requires "
                    f"{expected_legs} leg(s); got {len(combo.legs)}"
                ),
            )
        if len(instruments_by_leg) != len(combo.legs):
            raise ValueError(
                "instruments_by_leg length must match combo.legs length"
            )

        # Per-leg invariants: defer to ``validate()`` so the same
        # venue / order_type / time_in_force / session / quantity_unit
        # / extended-hours rules apply to each leg as they would to a
        # standalone single order. The combo-level TIF and session
        # propagate from the parent (per ``_to_native_single_leg``),
        # so a bracket leg whose order_type isn't in the supported set
        # fails validate-time with an ``order_type`` capability code
        # rather than waiting for serialization to surface a
        # ``*_price`` failure further downstream.
        for leg, inst in zip(combo.legs, instruments_by_leg):
            self.validate(
                _ComboLegOrder(combo, leg), inst, account_ctx
            )

        # Combo-level invariant: every leg must trade the same
        # instrument as the parent. Alpaca's bracket / OCO / OTO are
        # tied to a single symbol (no spreads).
        parent_symbol = instruments_by_leg[0].canonical_symbol
        for inst in instruments_by_leg[1:]:
            if inst.canonical_symbol != parent_symbol:
                raise UnsupportedCapability(
                    broker_code=self.broker_code,
                    capability_name="combo_cross_symbol",
                    details=(
                        "Alpaca bracket / OCO / OTO requires every leg to "
                        "trade the same symbol; got "
                        f"{parent_symbol!r} vs {inst.canonical_symbol!r}"
                    ),
                )

        # OTOCO / BRACKET: leg[1] must be the LIMIT take_profit and
        # leg[2] must be the STOP / STOP_LIMIT stop_loss.
        if combo.combo_type in (ComboType.OTOCO, ComboType.BRACKET):
            tp_leg = combo.legs[1]
            sl_leg = combo.legs[2]
            if tp_leg.order_type != OrderType.LIMIT:
                raise UnsupportedCapability(
                    broker_code=self.broker_code,
                    capability_name="bracket_take_profit_type",
                    details=(
                        "Alpaca bracket take_profit leg (legs[1]) must be "
                        f"LIMIT; got {tp_leg.order_type.value}"
                    ),
                )
            if sl_leg.order_type not in {OrderType.STOP, OrderType.STOP_LIMIT}:
                raise UnsupportedCapability(
                    broker_code=self.broker_code,
                    capability_name="bracket_stop_loss_type",
                    details=(
                        "Alpaca bracket stop_loss leg (legs[2]) must be "
                        f"STOP or STOP_LIMIT; got {sl_leg.order_type.value}"
                    ),
                )

    def to_native_combo(
        self,
        combo: Any,
        instruments_by_leg: list[Any],
        account_ctx: AccountContext,
    ) -> dict[str, Any]:
        """Translate a NormalizedComboOrderRequest into Alpaca's
        bracket / OCO / OTO payload shape.

        Alpaca's REST API accepts a parent order with embedded
        ``take_profit`` and ``stop_loss`` siblings:

            { ...parent fields..., "order_class": "bracket",
              "take_profit": {"limit_price": "200.00"},
              "stop_loss":   {"stop_price": "175.00",
                              "limit_price": "174.50"} }

        SINGLE collapses to a plain order without ``order_class``.
        """
        if combo.combo_type == ComboType.SINGLE:
            return self._to_native_single_leg(
                combo, instruments_by_leg[0], account_ctx
            )

        parent_leg = combo.legs[0]
        parent_inst = instruments_by_leg[0]
        # Build the parent payload from a synthetic single-leg order
        # so we reuse the to_native validation + payload assembly.
        body = self._to_native_single_leg(combo, parent_inst, account_ctx)
        body["order_class"] = COMBO_TYPE_TO_ALPACA[combo.combo_type]

        if combo.combo_type in (ComboType.OTOCO, ComboType.BRACKET):
            tp_leg = combo.legs[1]
            sl_leg = combo.legs[2]
            body["take_profit"] = _build_take_profit(tp_leg)
            body["stop_loss"] = _build_stop_loss(sl_leg)
        elif combo.combo_type == ComboType.OTO:
            child = combo.legs[1]
            if child.order_type == OrderType.LIMIT:
                body["take_profit"] = _build_take_profit(child)
            else:
                body["stop_loss"] = _build_stop_loss(child)
        elif combo.combo_type == ComboType.OCO:
            # OCO pairs the parent's limit (take_profit) with a
            # separate stop_loss leg.
            sl_leg = combo.legs[1]
            body["stop_loss"] = _build_stop_loss(sl_leg)

        return body

    def _to_native_single_leg(
        self,
        combo: Any,
        instrument: Any,
        account_ctx: AccountContext,
    ) -> dict[str, Any]:
        """Build the parent-order payload from combo.legs[0].

        Reuses to_native() by constructing a transient-shaped object
        with the leg's fields + the combo's TIF / session.
        """
        leg = combo.legs[0]

        class _SyntheticOrder:
            instrument = type(
                "_I",
                (),
                {
                    "canonical_symbol": leg.instrument_ref.canonical_symbol,
                    "broker_native_symbol": None,
                },
            )()
            side = leg.side
            order_type = leg.order_type
            quantity = leg.quantity
            quantity_unit = leg.quantity_unit
            price = leg.price
            trigger_price = leg.trigger_price
            trailing_offset = None
            time_in_force = combo.time_in_force
            session = combo.session
            client_order_id = combo.link_id
            extra = combo.metadata or {}

        return self.to_native(_SyntheticOrder(), instrument, account_ctx)

    def send_native(
        self,
        native_payload: dict[str, Any],
        account_ctx: AccountContext,
    ) -> dict[str, Any]:
        """Dispatcher hook — POST the native payload to Alpaca."""
        return self._post("/v2/orders", native_payload)

    def from_native_order_response(
        self,
        payload: dict[str, Any],
        instrument: Any,
    ) -> dict[str, Any]:
        if "id" not in payload:
            raise ValueError("Alpaca order response missing `id`")
        native_status = payload.get("status", "new")
        canonical = self.normalize_order_status(native_status)
        return {
            "order_id": payload["id"],
            "status": canonical.value,
            "native_status": native_status,
            "filled_quantity": _opt_decimal(payload.get("filled_qty")),
            "filled_avg_price": _opt_decimal(payload.get("filled_avg_price")),
            "native": payload,
        }

    # ---- BrokerOrderTranslator status normalization --------------------
    #
    # Maps Alpaca's native status vocabulary to the canonical
    # ``domain.enums.OrderStatus`` (FIX-aligned). Enumerates every
    # value documented in Alpaca's API:
    # https://docs.alpaca.markets/docs/orders-at-alpaca#order-lifecycle
    #
    # The classmethod form lets ops scripts and tests call this without
    # constructing a translator instance.

    _NATIVE_STATUS_MAP: dict[str, OrderStatus] = {
        # Pre-acceptance
        "pending_new": OrderStatus.PENDING_NEW,
        "new": OrderStatus.NEW,
        "accepted": OrderStatus.NEW,            # Alpaca acks then leaves NEW until working
        "accepted_for_bidding": OrderStatus.ACCEPTED_FOR_BIDDING,
        # Live in book
        "held": OrderStatus.SUSPENDED,
        "suspended": OrderStatus.SUSPENDED,
        "stopped": OrderStatus.SUSPENDED,        # Alpaca's "stopped" — broker held
        "calculated": OrderStatus.CALCULATED,
        "partially_filled": OrderStatus.PARTIALLY_FILLED,
        # Terminal — success
        "filled": OrderStatus.FILLED,
        "done_for_day": OrderStatus.DONE_FOR_DAY,
        # Replace / cancel
        "pending_cancel": OrderStatus.PENDING_CANCEL,
        "pending_replace": OrderStatus.PENDING_REPLACE,
        "replaced": OrderStatus.REPLACED,
        # Terminal — failure / withdrawal
        "canceled": OrderStatus.CANCELED,
        "cancelled": OrderStatus.CANCELED,       # spelling tolerated
        "expired": OrderStatus.EXPIRED,
        "rejected": OrderStatus.REJECTED,
    }

    @classmethod
    def normalize_order_status(cls, native: str | None) -> OrderStatus:
        """Map an Alpaca native status string to canonical ``OrderStatus``.

        Returns :attr:`OrderStatus.UNKNOWN` for any value Alpaca starts
        emitting that's not in ``_NATIVE_STATUS_MAP`` — operators
        watching that value in dashboards will see it grow and can
        update the map.
        """
        if not native:
            return OrderStatus.UNKNOWN
        return cls._NATIVE_STATUS_MAP.get(native.lower().strip(), OrderStatus.UNKNOWN)

    # ---- Direct helpers (used by Phase 7 / ops tools) ------------------

    def place_order(
        self, payload: dict[str, Any], account_ctx: AccountContext | None = None
    ) -> dict[str, Any]:
        return self._post("/v2/orders", payload)

    def get_order_status(self, order_id: str) -> dict[str, Any]:
        return self._get(f"/v2/orders/{order_id}")

    def cancel_order(self, order_id: str) -> None:
        self._delete(f"/v2/orders/{order_id}")

    # ---- Session-bound order management for /api/v2 dispatcher ---------
    #
    # These take the OpenAlgo session ``auth_token`` (the JSON blob the
    # broker callback emits) and rebuild an :class:`AlpacaAuth` from
    # it via :func:`auth_handle_from_token` so paper-vs-live mode is
    # honored for the lifetime of the session, regardless of what the
    # current ``ALPACA_PAPER`` / ``ALPACA_LIVE_MODE`` env vars say.

    def list_orders_via_token(
        self,
        auth_token: str,
        *,
        status: str = "open",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """GET /v2/orders with the session's auth handle."""
        from broker.alpaca.api.auth_api import auth_handle_from_token

        auth = auth_handle_from_token(auth_token)
        with httpx.Client(**self._client_kwargs(auth)) as c:
            r = c.get(f"/v2/orders?status={status}&limit={limit}")
        r.raise_for_status()
        return r.json() or []

    def get_order_via_token(
        self,
        auth_token: str,
        order_id: str,
    ) -> dict[str, Any]:
        """GET /v2/orders/<id>."""
        from broker.alpaca.api.auth_api import auth_handle_from_token

        auth = auth_handle_from_token(auth_token)
        with httpx.Client(**self._client_kwargs(auth)) as c:
            r = c.get(f"/v2/orders/{order_id}")
        r.raise_for_status()
        return r.json()

    def cancel_order_via_token(
        self,
        auth_token: str,
        order_id: str,
    ) -> None:
        """DELETE /v2/orders/<id>. Returns None on 204 / 200; raises on other status."""
        from broker.alpaca.api.auth_api import auth_handle_from_token

        auth = auth_handle_from_token(auth_token)
        with httpx.Client(**self._client_kwargs(auth)) as c:
            r = c.delete(f"/v2/orders/{order_id}")
        if r.status_code not in (200, 204):
            r.raise_for_status()

    # ---- HTTP plumbing -------------------------------------------------

    def _resolve_auth(self) -> AlpacaAuth:
        if self._auth is None:
            return authenticate()
        return self._auth

    def _client_kwargs(self, auth: AlpacaAuth) -> dict[str, Any]:
        return {
            "base_url": auth.base_url,
            "headers": dict(auth.headers),
            "timeout": httpx.Timeout(10.0, connect=5.0),
        }

    def _post(self, path: str, body: dict) -> dict:
        auth = self._resolve_auth()
        if self._client is not None:
            r = self._client.post(path, json=body)
        else:
            with httpx.Client(**self._client_kwargs(auth)) as c:
                r = c.post(path, json=body)
        _raise_with_alpaca_message(r)
        return r.json()

    def _get(self, path: str) -> dict:
        auth = self._resolve_auth()
        if self._client is not None:
            r = self._client.get(path)
        else:
            with httpx.Client(**self._client_kwargs(auth)) as c:
                r = c.get(path)
        _raise_with_alpaca_message(r)
        return r.json()

    def _delete(self, path: str) -> None:
        auth = self._resolve_auth()
        if self._client is not None:
            r = self._client.delete(path)
        else:
            with httpx.Client(**self._client_kwargs(auth)) as c:
                r = c.delete(path)
        if r.status_code not in (200, 204):
            r.raise_for_status()


def _opt_decimal(raw: Any) -> str | None:
    if raw is None or raw == "":
        return None
    try:
        return str(Decimal(str(raw)))
    except (ArithmeticError, ValueError):
        return None


def _raise_with_alpaca_message(response: httpx.Response) -> None:
    """Surface Alpaca's JSON error body in the raised exception.

    ``httpx.Response.raise_for_status()`` produces a generic
    ``Client error '422 Unprocessable Entity'`` message, dropping
    Alpaca's actual diagnostic (e.g. ``"stop price must be greater
    than current price"`` or ``"insufficient buying power"``).
    Operators see the generic message via the v1 bridge's
    502 ``broker_error`` envelope and have no way to know what
    actually went wrong.

    Parse the response body when possible and append Alpaca's
    ``message`` to the raised exception.
    """
    if 200 <= response.status_code < 400:
        return

    detail = ""
    try:
        body = response.json()
    except (ValueError, TypeError):
        body = None
    if isinstance(body, dict):
        msg = body.get("message")
        code = body.get("code")
        if msg:
            detail = f": {msg}"
            if code:
                detail = f" (code {code}){detail}"

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        # Re-raise with the broker's diagnostic appended. Preserve
        # the original exception type so callers' except clauses
        # still match.
        if detail:
            raise httpx.HTTPStatusError(
                f"{e}{detail}",
                request=e.request,
                response=e.response,
            ) from e
        raise


# ---- Branch L — bracket / OCO / OTO leg builders ---------------------


def _build_take_profit(leg: Any) -> dict[str, Any]:
    """Alpaca's ``take_profit`` block accepts a single ``limit_price``."""
    if leg.price is None:
        raise UnsupportedCapability(
            broker_code="alpaca",
            capability_name="take_profit_price",
            details="take_profit leg must be LIMIT with a price",
        )
    return {"limit_price": str(leg.price)}


def _build_stop_loss(leg: Any) -> dict[str, Any]:
    """Alpaca's ``stop_loss`` block accepts ``stop_price`` (required)
    and optional ``limit_price`` for STOP_LIMIT semantics.
    """
    if leg.trigger_price is None:
        raise UnsupportedCapability(
            broker_code="alpaca",
            capability_name="stop_loss_trigger_price",
            details=(
                "stop_loss leg requires trigger_price (Alpaca stop_price)"
            ),
        )
    block: dict[str, Any] = {"stop_price": str(leg.trigger_price)}
    if leg.order_type == OrderType.STOP_LIMIT:
        if leg.price is None:
            raise UnsupportedCapability(
                broker_code="alpaca",
                capability_name="stop_loss_limit_price",
                details=(
                    "STOP_LIMIT stop_loss leg requires both trigger_price "
                    "and price (Alpaca stop_price + limit_price)"
                ),
            )
        block["limit_price"] = str(leg.price)
    return block


# ---------------------------------------------------------------------------
# Module-level legacy shims for ``services.cancel_order_service`` /
# ``services.modify_order_service`` etc., which dynamically import
# ``broker.<broker>.api.order_api`` and call ``cancel_order`` /
# ``modify_order`` / ``get_order_book`` etc. as module-level functions.
#
# Wiring these to the new translator lets the existing Indian-shaped
# UI endpoints (``/cancel_order``, ``/modify_order``) work for Alpaca
# without forcing every legacy service to grow a per-broker branch.
# Each shim is just a thin adapter: rebuild an :class:`AlpacaAuth`
# from the session ``auth_token``, do the HTTP call, return the
# legacy-shaped tuple ``(response_dict, http_status)``.
#
# These are NEVER imported from PROMOTED_CORE — only the legacy
# services reach them (lane-isolation invariant preserved).
# ---------------------------------------------------------------------------


def cancel_order(orderid: str, auth_token: str) -> tuple[dict[str, Any], int]:
    """Module-level shim — used by ``services.cancel_order_service``.

    Returns ``({status, orderid?}, http_status)``. Status 200 = success.
    """
    try:
        translator = AlpacaOrderTranslator()
        translator.cancel_order_via_token(auth_token, orderid)
        return {"status": "success", "orderid": orderid}, 200
    except httpx.HTTPStatusError as e:
        try:
            payload = e.response.json()
            msg = payload.get("message") or str(payload)
        except Exception:  # noqa: BLE001
            msg = e.response.text or str(e)
        return {"status": "error", "message": msg}, e.response.status_code
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": str(e)}, 500


def modify_order(
    data: dict[str, Any], auth_token: str
) -> tuple[dict[str, Any], int]:
    """Module-level shim — used by ``services.modify_order_service``.

    Alpaca's PATCH /v2/orders/<id> accepts qty / time_in_force /
    limit_price / stop_price / trail / client_order_id. Maps the
    legacy v1 ``modify_order`` fields onto that subset.
    """
    from broker.alpaca.api.auth_api import auth_handle_from_token

    orderid = data.get("orderid") or data.get("order_id")
    if not orderid:
        return {"status": "error", "message": "orderid required"}, 400

    def _is_set(value: Any) -> bool:
        """Treat 0 / "0" / "" / None as "not set" so the legacy
        UI's habit of defaulting these to 0 doesn't leak through to
        Alpaca as an explicit zero (which Alpaca rejects with
        ``stop price must be > 0`` etc.).
        """
        if value is None or value == "":
            return False
        try:
            return float(value) != 0.0
        except (TypeError, ValueError):
            return bool(str(value).strip())

    patch_body: dict[str, Any] = {}
    if _is_set(data.get("quantity")):
        patch_body["qty"] = str(data["quantity"])
    if _is_set(data.get("price")):
        patch_body["limit_price"] = str(data["price"])
    if _is_set(data.get("trigger_price")):
        patch_body["stop_price"] = str(data["trigger_price"])
    if not patch_body:
        return {"status": "error", "message": "no modifiable fields supplied"}, 400

    try:
        auth = auth_handle_from_token(auth_token)
        with httpx.Client(
            base_url=auth.base_url,
            headers=dict(auth.headers),
            timeout=httpx.Timeout(10.0, connect=5.0),
        ) as c:
            r = c.patch(f"/v2/orders/{orderid}", json=patch_body)
        if r.status_code >= 400:
            # Surface Alpaca's structured JSON error message
            # (``"cannot replace order in accepted status"``,
            # ``"stop price must be > 0"`` etc.) instead of the raw
            # text. Mirrors ``cancel_order`` above. Falls back to
            # raw text when the body isn't JSON.
            msg = r.text[:500]
            try:
                body = r.json()
                if isinstance(body, dict) and body.get("message"):
                    msg = body["message"]
                    if body.get("code"):
                        msg = f"(code {body['code']}) {msg}"
            except (ValueError, TypeError):
                pass
            return {"status": "error", "message": msg}, r.status_code
        return {"status": "success", "orderid": orderid}, 200
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": str(e)}, 500


def get_order_book(auth_token: str) -> tuple[dict[str, Any], int]:
    """Module-level shim — used by legacy ``services.orderbook_service``."""
    try:
        translator = AlpacaOrderTranslator()
        rows = translator.list_orders_via_token(auth_token, status="all")
        return {"status": "success", "data": rows}, 200
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": str(e)}, 500


def close_all_positions(api_key: Any, auth_token: str) -> tuple[Any, int]:
    """Liquidate every open position. Alpaca exposes
    ``DELETE /v2/positions`` which submits a closing order for each
    position atomically and returns the resulting order list.

    Used by ``services.close_position_service.close_position_with_auth``.
    Signature mirrors the legacy India shape ``(response_code, status_code)``
    so the existing service layer can dispatch into Alpaca without
    branching.

    ``api_key`` is unused — the auth handle is rebuilt from the
    session ``auth_token`` so paper-vs-live mode is honored
    independently of ambient env state.
    """
    del api_key  # not used; kept for legacy signature parity
    from broker.alpaca.api.auth_api import auth_handle_from_token

    try:
        auth = auth_handle_from_token(auth_token)
        with httpx.Client(
            base_url=auth.base_url,
            headers=dict(auth.headers),
            timeout=httpx.Timeout(15.0, connect=5.0),
        ) as c:
            r = c.delete("/v2/positions")
        if r.status_code in (200, 207):
            return {"status": "success", "data": r.json() if r.content else []}, 200
        if r.status_code == 204:
            return {"status": "success", "data": []}, 200
        return {"status": "error", "message": r.text[:300] or f"HTTP {r.status_code}"}, r.status_code
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": str(e)}, 500


def get_open_position(symbol: str, exchange: str, product: str, auth_token: str) -> Any:
    """Return the current open position quantity (positive = long,
    negative = short, 0 = flat) for a symbol on a venue. Used by the
    `/close_position` UI flow which must know the current direction
    before submitting an opposing order.

    Alpaca's ``GET /v2/positions/<symbol>`` returns 404 when flat.
    """
    del exchange, product  # Alpaca position lookup is symbol-keyed only
    from broker.alpaca.api.auth_api import auth_handle_from_token

    auth = auth_handle_from_token(auth_token)
    with httpx.Client(
        base_url=auth.base_url,
        headers=dict(auth.headers),
        timeout=httpx.Timeout(10.0, connect=5.0),
    ) as c:
        r = c.get(f"/v2/positions/{symbol.upper()}")
    if r.status_code == 404:
        return "0"
    r.raise_for_status()
    body = r.json() or {}
    qty = body.get("qty") or "0"
    side = (body.get("side") or "long").lower()
    if side == "short" and not str(qty).startswith("-"):
        return f"-{qty}"
    return str(qty)


def place_smartorder_api(
    order_data: dict[str, Any], auth_token: str
) -> tuple[Any, dict[str, Any], str | None]:
    """Smart-order entry point used by the `/close_position` UI flow.

    The legacy contract: when ``position_size`` is ``"0"`` the operator
    wants to flatten the position. For Alpaca that maps to
    ``DELETE /v2/positions/<symbol>``, which Alpaca implements as
    "submit a closing market order for the full quantity". The closing
    order's id is returned so the UI can render the resulting flatten
    order in the order book.

    For non-zero ``position_size`` the legacy semantics are
    "rebalance to target" — out of MVP scope for Alpaca paper
    trading. Returns a structured error so the UI surfaces it
    instead of silently failing.
    """
    from broker.alpaca.api.auth_api import auth_handle_from_token

    symbol = (order_data.get("symbol") or "").upper()
    position_size = str(order_data.get("position_size", "")).strip()

    if not symbol:
        return None, {"message": "symbol required"}, None
    if position_size and position_size != "0":
        return None, {
            "message": (
                "place_smartorder for non-zero position_size is not "
                "implemented for Alpaca yet — use POST /api/v2/orders "
                "to place a normal order, or DELETE /v2/positions/"
                f"{symbol} to flatten."
            )
        }, None

    try:
        auth = auth_handle_from_token(auth_token)
        with httpx.Client(
            base_url=auth.base_url,
            headers=dict(auth.headers),
            timeout=httpx.Timeout(10.0, connect=5.0),
        ) as c:
            r = c.delete(f"/v2/positions/{symbol}")
    except Exception as e:  # noqa: BLE001
        return None, {"message": str(e)}, None

    if r.status_code in (200, 207):
        body = r.json() if r.content else {}
        # Alpaca's body shape: {"id": "...closing-order-id", ...}
        order_id = body.get("id")
        return r, {"message": f"Position {symbol} flatten submitted"}, order_id
    if r.status_code == 404:
        return r, {"message": f"No open position in {symbol}"}, None
    return r, {"message": f"HTTP {r.status_code}: {r.text[:200]}"}, None


def cancel_all_orders_api(
    order_data: dict[str, Any], auth_token: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Cancel every open order. Returns ``(canceled, failed)`` lists.

    Used by ``services.cancel_all_order_service`` (which is invoked
    from the React UI's "Cancel All" button). Alpaca exposes
    ``DELETE /v2/orders`` which atomically cancels every open order
    and returns a per-order status report — much more efficient than
    iterating cancels client-side.
    """
    from broker.alpaca.api.auth_api import auth_handle_from_token

    auth = auth_handle_from_token(auth_token)
    canceled: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    try:
        with httpx.Client(
            base_url=auth.base_url,
            headers=dict(auth.headers),
            timeout=httpx.Timeout(15.0, connect=5.0),
        ) as c:
            r = c.delete("/v2/orders")
        # 207 Multi-Status is what Alpaca actually returns; their docs
        # describe the response as an array of {id, status} per order.
        if r.status_code in (200, 207):
            for entry in r.json() or []:
                oid = entry.get("id")
                http_code = entry.get("status")
                if isinstance(http_code, int) and http_code < 300:
                    canceled.append({"orderid": oid})
                else:
                    failed.append({"orderid": oid, "reason": entry.get("body")})
        elif r.status_code == 204:
            # Nothing to cancel — empty success.
            pass
        else:
            failed.append({"orderid": None, "reason": f"HTTP {r.status_code}: {r.text[:200]}"})
    except Exception as e:  # noqa: BLE001
        failed.append({"orderid": None, "reason": str(e)})

    return canceled, failed


__all__ = [
    "AlpacaOrderTranslator",
    "cancel_all_orders_api",
    "cancel_order",
    "close_all_positions",
    "get_open_position",
    "get_order_book",
    "modify_order",
    "place_smartorder_api",
]
