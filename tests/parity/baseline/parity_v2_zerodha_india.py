"""Parity harness: Zerodha v2 broker translator (India bit-identical).

Exercises ``broker.zerodha.translator.ZerodhaOrderTranslator`` with
representative orders covering the order-type / TIF / product /
exchange combinations Indian users place via Zerodha. Captures the
exact native dict (sorted keys for stability) so any drift between
the v2 path and the legacy v1 ``transform_data`` shape is caught.

This harness pins the v6 Phase 5 promise: when ``API_V2_ZERODHA=1``
flips on, the order body the dispatcher hands to Kite Connect is
byte-identical to what the v1 lane sent — except for the structured
``trigger_price`` formatting (``"0"`` vs ``"0.0"``) which both lanes
already normalize to ``"0"``.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tests.parity import _common  # noqa: E402,F401

from broker.zerodha.translator import ZerodhaOrderTranslator  # noqa: E402
from domain.account_context import AccountContext  # noqa: E402
from domain.currency import Currency  # noqa: E402
from domain.enums import (  # noqa: E402
    OrderSide,
    OrderType,
    PositionEffect,
    QuantityUnit,
    Session,
    TimeInForce,
)
from domain.errors import UnsupportedCapability  # noqa: E402
from domain.instrument_ref import InstrumentRef  # noqa: E402
from domain.orders import NormalizedOrderRequest  # noqa: E402

NAME = "parity_v2_zerodha_india"


def _stub_instrument(symbol: str, exchange: str) -> SimpleNamespace:
    """Resolved-instrument shape the translator reads. The real
    promoted dispatcher passes a ResolvedInstrument; this harness
    supplies a duck-typed stub so the test stays pure / DB-free."""
    return SimpleNamespace(
        broker_symbol=symbol,
        canonical_symbol=symbol,
        venue_code=exchange,
    )


def _account_ctx() -> AccountContext:
    return AccountContext(
        broker_code="zerodha",
        account_id="zerodha-test-account",
        base_currency=Currency.INR,
    )


def _build_order(
    *,
    symbol: str = "SBIN",
    exchange: str = "NSE",
    side: OrderSide = OrderSide.BUY,
    order_type: OrderType = OrderType.MARKET,
    quantity: str = "1",
    quantity_unit: QuantityUnit = QuantityUnit.WHOLE,
    price: str | None = None,
    trigger_price: str | None = None,
    time_in_force: TimeInForce = TimeInForce.DAY,
    session: Session = Session.REGULAR,
    position_effect: PositionEffect = PositionEffect.NONE,
    legacy_product_hint: str | None = None,
    strategy_tag: str | None = None,
) -> NormalizedOrderRequest:
    extra: Dict[str, Any] = {}
    if legacy_product_hint is not None:
        extra["legacy_product_hint"] = legacy_product_hint
    return NormalizedOrderRequest(
        instrument=InstrumentRef(canonical_symbol=symbol, venue_code=exchange),
        side=side,
        order_type=order_type,
        quantity=Decimal(quantity),
        quantity_unit=quantity_unit,
        price=Decimal(price) if price is not None else None,
        trigger_price=Decimal(trigger_price) if trigger_price is not None else None,
        time_in_force=time_in_force,
        session=session,
        position_effect=position_effect,
        strategy_tag=strategy_tag,
        extra=extra,
    )


CASES: list[Dict[str, Any]] = [
    # 1. Market order, equity, CNC default (NONE position effect, no hint)
    {
        "label": "market_buy_equity_cnc_default",
        "kwargs": {
            "symbol": "SBIN",
            "exchange": "NSE",
            "side": OrderSide.BUY,
            "order_type": OrderType.MARKET,
            "quantity": "10",
            "quantity_unit": QuantityUnit.WHOLE,
            "time_in_force": TimeInForce.DAY,
        },
    },
    # 2. Limit BUY, MIS via REDUCE_ONLY position-effect
    {
        "label": "limit_buy_equity_mis_via_reduce_only",
        "kwargs": {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "side": OrderSide.BUY,
            "order_type": OrderType.LIMIT,
            "quantity": "5",
            "price": "2950.50",
            "time_in_force": TimeInForce.DAY,
            "position_effect": PositionEffect.REDUCE_ONLY,
        },
    },
    # 3. Limit SELL with explicit NRML hint (F&O carry)
    {
        "label": "limit_sell_fno_nrml_hint",
        "kwargs": {
            "symbol": "BANKNIFTY24APR2447500CE",
            "exchange": "NFO",
            "side": OrderSide.SELL,
            "order_type": OrderType.LIMIT,
            "quantity": "15",
            "quantity_unit": QuantityUnit.LOTS,
            "price": "200.00",
            "time_in_force": TimeInForce.DAY,
            "legacy_product_hint": "NRML",
        },
    },
    # 4. SL (stop-loss limit) with trigger_price
    {
        "label": "stop_limit_buy_equity",
        "kwargs": {
            "symbol": "INFY",
            "exchange": "NSE",
            "side": OrderSide.BUY,
            "order_type": OrderType.STOP_LIMIT,
            "quantity": "20",
            "price": "1500.00",
            "trigger_price": "1495.00",
            "time_in_force": TimeInForce.DAY,
            "legacy_product_hint": "MIS",
        },
    },
    # 5. SL-M (stop-loss market) with trigger_price only
    {
        "label": "stop_market_sell_equity",
        "kwargs": {
            "symbol": "TCS",
            "exchange": "NSE",
            "side": OrderSide.SELL,
            "order_type": OrderType.STOP,
            "quantity": "5",
            "trigger_price": "3800.00",
            "time_in_force": TimeInForce.DAY,
            "legacy_product_hint": "MIS",
        },
    },
    # 6. IOC market order
    {
        "label": "ioc_market_buy",
        "kwargs": {
            "symbol": "HDFCBANK",
            "exchange": "NSE",
            "side": OrderSide.BUY,
            "order_type": OrderType.MARKET,
            "quantity": "1",
            "time_in_force": TimeInForce.IOC,
        },
    },
    # 7. Strategy-tagged order
    {
        "label": "tagged_market_order",
        "kwargs": {
            "symbol": "WIPRO",
            "exchange": "NSE",
            "side": OrderSide.BUY,
            "order_type": OrderType.MARKET,
            "quantity": "100",
            "time_in_force": TimeInForce.DAY,
            "strategy_tag": "swing-v2",
        },
    },
]

# UNSUPPORTED cases — the translator must reject these with
# UnsupportedCapability + the documented dimension.
UNSUPPORTED_CASES: list[Dict[str, Any]] = [
    {
        "label": "trailing_stop_unsupported",
        "kwargs": {
            "symbol": "SBIN",
            "exchange": "NSE",
            "order_type": OrderType.TRAILING_STOP,
            "quantity": "1",
            "trigger_price": "100.00",
            "time_in_force": TimeInForce.DAY,
        },
        "extra": {
            # NormalizedOrderRequest cross-validation forces trailing_offset
            # for TRAILING_STOP, so we set it directly.
            "trailing_offset": "5.00",
        },
        "expected_dimension": "order_type",
    },
    {
        "label": "fok_tif_unsupported",
        "kwargs": {
            "symbol": "SBIN",
            "exchange": "NSE",
            "order_type": OrderType.MARKET,
            "quantity": "1",
            "time_in_force": TimeInForce.FOK,
        },
        "expected_dimension": "tif",
    },
    {
        "label": "pre_market_session_unsupported",
        "kwargs": {
            "symbol": "SBIN",
            "exchange": "NSE",
            "order_type": OrderType.MARKET,
            "quantity": "1",
            "time_in_force": TimeInForce.DAY,
            "session": Session.PRE_MARKET,
        },
        "expected_dimension": "session",
    },
    {
        "label": "fractional_unsupported",
        "kwargs": {
            "symbol": "SBIN",
            "exchange": "NSE",
            "order_type": OrderType.MARKET,
            "quantity": "0.5",
            "quantity_unit": QuantityUnit.FRACTIONAL,
            "time_in_force": TimeInForce.DAY,
        },
        "expected_dimension": "quantity_unit",
    },
]


def _build_unsupported_order(case: Dict[str, Any]) -> NormalizedOrderRequest:
    kwargs = dict(case["kwargs"])
    extra = case.get("extra", {})
    if extra:
        kwargs["extra"] = extra
    # Translate the "extra" trailing_offset into the proper field.
    trailing_offset = None
    if extra.get("trailing_offset"):
        trailing_offset = Decimal(extra["trailing_offset"])
    base_extra = {}
    return NormalizedOrderRequest(
        instrument=InstrumentRef(
            canonical_symbol=kwargs.get("symbol", "X"),
            venue_code=kwargs.get("exchange", "NSE"),
        ),
        side=kwargs.get("side", OrderSide.BUY),
        order_type=kwargs["order_type"],
        quantity=Decimal(kwargs["quantity"]),
        quantity_unit=kwargs.get("quantity_unit", QuantityUnit.WHOLE),
        price=Decimal(kwargs["price"]) if kwargs.get("price") else None,
        trigger_price=Decimal(kwargs["trigger_price"])
        if kwargs.get("trigger_price")
        else None,
        trailing_offset=trailing_offset,
        time_in_force=kwargs.get("time_in_force", TimeInForce.DAY),
        session=kwargs.get("session", Session.REGULAR),
        position_effect=kwargs.get("position_effect", PositionEffect.NONE),
        extra=base_extra,
    )


def generate() -> Dict[str, Any]:
    translator = ZerodhaOrderTranslator()
    account_ctx = _account_ctx()

    accepted = []
    for case in CASES:
        order = _build_order(**case["kwargs"])
        instrument = _stub_instrument(
            order.instrument.canonical_symbol or "X",
            order.instrument.venue_code or "NSE",
        )
        native = translator.to_native(order, instrument, account_ctx)
        accepted.append(
            {
                "label": case["label"],
                "native": native,
            }
        )

    rejected = []
    for case in UNSUPPORTED_CASES:
        order = _build_unsupported_order(case)
        instrument = _stub_instrument(
            order.instrument.canonical_symbol or "X",
            order.instrument.venue_code or "NSE",
        )
        try:
            translator.validate(order, instrument, account_ctx)
            rejected.append(
                {"label": case["label"], "raised": False, "details": None}
            )
        except UnsupportedCapability as e:
            rejected.append(
                {
                    "label": case["label"],
                    "raised": True,
                    "broker_code": e.broker_code,
                    "capability_name": e.capability_name,
                    "expected_dimension": case["expected_dimension"],
                }
            )

    # Round-trip a Kite-shaped accept response.
    sample_response = {
        "order_id": "240319000123456",
        "status": "success",
    }
    instrument = _stub_instrument("SBIN", "NSE")
    normalized_response = translator.from_native_order_response(
        sample_response, instrument
    )

    return {
        "harness": NAME,
        "broker_code": ZerodhaOrderTranslator.broker_code,
        "accepted": accepted,
        "rejected": rejected,
        "response_round_trip": normalized_response,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(generate(), indent=2, sort_keys=True))
