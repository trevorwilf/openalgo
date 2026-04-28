"""v6 Phase 5 — shared parity-harness builder for India v2 broker
translators.

Each per-broker harness (`parity_v2_<broker>_india`) imports
:func:`build_parity_output` and passes its translator class. The
harness output shape is identical across brokers — only the
``native`` field bodies differ — so the runner picks up drift in
any individual translator deterministically.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Dict

from broker.zerodha.translator import ZerodhaOrderTranslator  # noqa: F401
from domain.account_context import AccountContext
from domain.currency import Currency
from domain.enums import (
    OrderSide,
    OrderType,
    PositionEffect,
    QuantityUnit,
    Session,
    TimeInForce,
)
from domain.errors import UnsupportedCapability
from domain.instrument_ref import InstrumentRef
from domain.orders import NormalizedOrderRequest


def _stub_instrument(symbol: str, exchange: str, token: str = "12345") -> SimpleNamespace:
    return SimpleNamespace(
        broker_symbol=symbol,
        canonical_symbol=symbol,
        venue_code=exchange,
        broker_token=token,
        token=token,
    )


def _account_ctx(broker_code: str) -> AccountContext:
    return AccountContext(
        broker_code=broker_code,
        account_id=f"{broker_code}-test-account",
        base_currency=Currency.INR,
    )


def _build_order(**kw: Any) -> NormalizedOrderRequest:
    extra: Dict[str, Any] = {}
    if "legacy_product_hint" in kw:
        extra["legacy_product_hint"] = kw.pop("legacy_product_hint")
    return NormalizedOrderRequest(
        instrument=InstrumentRef(
            canonical_symbol=kw.get("symbol", "SBIN"),
            venue_code=kw.get("exchange", "NSE"),
        ),
        side=kw.get("side", OrderSide.BUY),
        order_type=kw.get("order_type", OrderType.MARKET),
        quantity=Decimal(kw.get("quantity", "1")),
        quantity_unit=kw.get("quantity_unit", QuantityUnit.WHOLE),
        price=Decimal(kw["price"]) if kw.get("price") else None,
        trigger_price=Decimal(kw["trigger_price"]) if kw.get("trigger_price") else None,
        time_in_force=kw.get("time_in_force", TimeInForce.DAY),
        session=kw.get("session", Session.REGULAR),
        position_effect=kw.get("position_effect", PositionEffect.NONE),
        strategy_tag=kw.get("strategy_tag"),
        extra=extra,
    )


# Standard accept cases every Indian translator handles.
ACCEPT_CASES: list[Dict[str, Any]] = [
    {
        "label": "market_buy_equity_cnc_default",
        "kwargs": {"symbol": "SBIN", "exchange": "NSE", "quantity": "10"},
    },
    {
        "label": "limit_buy_equity_mis_via_reduce_only",
        "kwargs": {
            "symbol": "RELIANCE", "exchange": "NSE",
            "order_type": OrderType.LIMIT, "quantity": "5",
            "price": "2950.50",
            "position_effect": PositionEffect.REDUCE_ONLY,
        },
    },
    {
        "label": "limit_sell_fno_nrml_hint",
        "kwargs": {
            "symbol": "BANKNIFTY24APR2447500CE", "exchange": "NFO",
            "side": OrderSide.SELL, "order_type": OrderType.LIMIT,
            "quantity": "15", "quantity_unit": QuantityUnit.LOTS,
            "price": "200.00", "legacy_product_hint": "NRML",
        },
    },
    {
        "label": "stop_limit_buy_equity",
        "kwargs": {
            "symbol": "INFY", "exchange": "NSE",
            "order_type": OrderType.STOP_LIMIT, "quantity": "20",
            "price": "1500.00", "trigger_price": "1495.00",
            "legacy_product_hint": "MIS",
        },
    },
    {
        "label": "stop_market_sell_equity",
        "kwargs": {
            "symbol": "TCS", "exchange": "NSE",
            "side": OrderSide.SELL, "order_type": OrderType.STOP,
            "quantity": "5", "trigger_price": "3800.00",
            "legacy_product_hint": "MIS",
        },
    },
    {
        "label": "ioc_market_buy",
        "kwargs": {
            "symbol": "HDFCBANK", "exchange": "NSE",
            "time_in_force": TimeInForce.IOC,
        },
    },
]

# Standard reject cases.
REJECT_CASES: list[Dict[str, Any]] = [
    {
        "label": "fok_tif_unsupported",
        "kwargs": {"symbol": "SBIN", "exchange": "NSE", "time_in_force": TimeInForce.FOK},
        "expected_dimension": "tif",
    },
    {
        "label": "pre_market_session_unsupported",
        "kwargs": {"symbol": "SBIN", "exchange": "NSE", "session": Session.PRE_MARKET},
        "expected_dimension": "session",
    },
    {
        "label": "fractional_unsupported",
        "kwargs": {
            "symbol": "SBIN", "exchange": "NSE",
            "quantity": "0.5", "quantity_unit": QuantityUnit.FRACTIONAL,
        },
        "expected_dimension": "quantity_unit",
    },
]


def build_parity_output(
    name: str,
    translator_cls: Any,
    sample_response: Dict[str, Any],
) -> Dict[str, Any]:
    translator = translator_cls()
    account_ctx = _account_ctx(translator_cls.broker_code)

    accepted = []
    for case in ACCEPT_CASES:
        order = _build_order(**case["kwargs"])
        instrument = _stub_instrument(
            order.instrument.canonical_symbol or "X",
            order.instrument.venue_code or "NSE",
        )
        accepted.append({
            "label": case["label"],
            "native": translator.to_native(order, instrument, account_ctx),
        })

    rejected = []
    for case in REJECT_CASES:
        order = _build_order(**case["kwargs"])
        instrument = _stub_instrument("SBIN", "NSE")
        try:
            translator.validate(order, instrument, account_ctx)
            rejected.append({"label": case["label"], "raised": False})
        except UnsupportedCapability as e:
            rejected.append({
                "label": case["label"],
                "raised": True,
                "broker_code": e.broker_code,
                "capability_name": e.capability_name,
                "expected_dimension": case["expected_dimension"],
            })

    instrument = _stub_instrument("SBIN", "NSE")
    response_round_trip = translator.from_native_order_response(
        sample_response, instrument
    )

    return {
        "harness": name,
        "broker_code": translator_cls.broker_code,
        "accepted": accepted,
        "rejected": rejected,
        "response_round_trip": response_round_trip,
    }
