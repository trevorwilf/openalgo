"""Legacy-Indian ↔ normalized-domain translators."""

from __future__ import annotations

from decimal import Decimal

import pytest

from domain.enums import (
    MarketFamily,
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
from domain.translators import (
    legacy_exchange_to_venue_code,
    legacy_pricetype_to_order_type,
    legacy_product_to_order_attrs,
    market_family_for_legacy_exchange,
    normalized_order_to_legacy_fields,
)

# Mirrors utils/constants.VALID_EXCHANGES + CRYPTO
LEGACY_EXCHANGES = [
    "NSE", "NFO", "CDS", "BSE", "BFO", "BCD", "MCX", "NCDEX",
    "NSE_INDEX", "BSE_INDEX", "CRYPTO",
]
LEGACY_PRODUCTS = ["CNC", "NRML", "MIS"]
LEGACY_PRICETYPES = ["MARKET", "LIMIT", "SL", "SL-M"]


# -- legacy_exchange_to_venue_code -----------------------------------------


@pytest.mark.parametrize("ex", LEGACY_EXCHANGES)
def test_legacy_exchange_identity(ex: str) -> None:
    assert legacy_exchange_to_venue_code(ex) == ex


def test_legacy_exchange_lowercased_uppercases() -> None:
    assert legacy_exchange_to_venue_code("nse") == "NSE"


def test_legacy_exchange_with_whitespace() -> None:
    assert legacy_exchange_to_venue_code("  mcx  ") == "MCX"


def test_legacy_exchange_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown legacy exchange"):
        legacy_exchange_to_venue_code("NYSE")


def test_legacy_exchange_non_string_raises() -> None:
    with pytest.raises(ValueError, match="expects str"):
        legacy_exchange_to_venue_code(42)  # type: ignore[arg-type]


# -- market_family_for_legacy_exchange -------------------------------------


@pytest.mark.parametrize(
    "ex,family",
    [
        ("NSE", MarketFamily.IN_STOCK),
        ("NFO", MarketFamily.IN_STOCK),
        ("MCX", MarketFamily.IN_STOCK),
        ("NSE_INDEX", MarketFamily.IN_STOCK),
        ("CRYPTO", MarketFamily.CRYPTO),
    ],
)
def test_market_family_mapping(ex: str, family: MarketFamily) -> None:
    assert market_family_for_legacy_exchange(ex) is family


# -- legacy_product_to_order_attrs -----------------------------------------


@pytest.mark.parametrize("product", LEGACY_PRODUCTS)
def test_legacy_product_returns_required_keys(product: str) -> None:
    attrs = legacy_product_to_order_attrs(product)
    assert set(attrs.keys()) >= {"position_effect", "time_in_force", "session"}
    assert isinstance(attrs["position_effect"], PositionEffect)
    assert isinstance(attrs["time_in_force"], TimeInForce)
    assert isinstance(attrs["session"], Session)


def test_legacy_product_mis_is_reduce_only() -> None:
    attrs = legacy_product_to_order_attrs("MIS")
    assert attrs["position_effect"] is PositionEffect.REDUCE_ONLY


def test_legacy_product_nrml_is_none_effect() -> None:
    attrs = legacy_product_to_order_attrs("NRML")
    assert attrs["position_effect"] is PositionEffect.NONE


def test_legacy_product_cnc_is_none_effect() -> None:
    attrs = legacy_product_to_order_attrs("CNC")
    assert attrs["position_effect"] is PositionEffect.NONE


def test_legacy_product_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown legacy product"):
        legacy_product_to_order_attrs("FOO")


def test_legacy_product_non_string_raises() -> None:
    with pytest.raises(ValueError, match="expects str"):
        legacy_product_to_order_attrs(0)  # type: ignore[arg-type]


# -- legacy_pricetype_to_order_type ----------------------------------------


@pytest.mark.parametrize(
    "pt,ot",
    [
        ("MARKET", OrderType.MARKET),
        ("LIMIT", OrderType.LIMIT),
        ("SL", OrderType.STOP_LIMIT),
        ("SL-M", OrderType.STOP),
    ],
)
def test_legacy_pricetype_mapping(pt: str, ot: OrderType) -> None:
    assert legacy_pricetype_to_order_type(pt) is ot


def test_legacy_pricetype_case_and_whitespace() -> None:
    assert legacy_pricetype_to_order_type("  limit  ") is OrderType.LIMIT
    assert legacy_pricetype_to_order_type("sl-m") is OrderType.STOP


def test_legacy_pricetype_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown legacy price type"):
        legacy_pricetype_to_order_type("MOO")


def test_legacy_pricetype_non_string_raises() -> None:
    with pytest.raises(ValueError, match="expects str"):
        legacy_pricetype_to_order_type(None)  # type: ignore[arg-type]


# -- Round-trip property test ---------------------------------------------


@pytest.mark.parametrize("exchange", LEGACY_EXCHANGES)
@pytest.mark.parametrize("product", LEGACY_PRODUCTS)
@pytest.mark.parametrize("pricetype", LEGACY_PRICETYPES)
def test_round_trip_every_legacy_combo(
    exchange: str, product: str, pricetype: str
) -> None:
    """Every legal legacy triple produces consistent normalized values."""
    venue = legacy_exchange_to_venue_code(exchange)
    family = market_family_for_legacy_exchange(exchange)
    attrs = legacy_product_to_order_attrs(product)
    order_type = legacy_pricetype_to_order_type(pricetype)

    assert venue == exchange
    assert isinstance(family, MarketFamily)
    assert isinstance(order_type, OrderType)
    assert isinstance(attrs["time_in_force"], TimeInForce)


# -- normalized_order_to_legacy_fields ------------------------------------


def _mk_order(**overrides) -> NormalizedOrderRequest:
    data = {
        "instrument": InstrumentRef(venue_code="NSE", canonical_symbol="SBIN"),
        "side": OrderSide.BUY,
        "order_type": OrderType.MARKET,
        "quantity": Decimal("1"),
        "quantity_unit": QuantityUnit.WHOLE,
        "time_in_force": TimeInForce.DAY,
    }
    data.update(overrides)
    return NormalizedOrderRequest(**data)


@pytest.mark.parametrize(
    "ot,expected_pt",
    [
        (OrderType.MARKET, "MARKET"),
        (OrderType.LIMIT, "LIMIT"),
        (OrderType.STOP_LIMIT, "SL"),
        (OrderType.STOP, "SL-M"),
    ],
)
def test_normalized_to_legacy_pricetype(ot: OrderType, expected_pt: str) -> None:
    overrides: dict = {"order_type": ot}
    if ot in {OrderType.LIMIT, OrderType.STOP_LIMIT}:
        overrides["price"] = Decimal("100")
    if ot in {OrderType.STOP, OrderType.STOP_LIMIT}:
        overrides["trigger_price"] = Decimal("99")
    out = normalized_order_to_legacy_fields(_mk_order(**overrides))
    assert out["pricetype"] == expected_pt


def test_normalized_to_legacy_rejects_moo() -> None:
    order = _mk_order(
        order_type=OrderType.MARKET_ON_OPEN,
        time_in_force=TimeInForce.OPG,
    )
    with pytest.raises(UnsupportedCapability, match="order_type=MARKET_ON_OPEN"):
        normalized_order_to_legacy_fields(order)


def test_normalized_to_legacy_rejects_gtc() -> None:
    order = _mk_order(time_in_force=TimeInForce.GTC)
    with pytest.raises(UnsupportedCapability, match="time_in_force=GTC"):
        normalized_order_to_legacy_fields(order)


def test_normalized_to_legacy_rejects_notional() -> None:
    order = _mk_order(quantity_unit=QuantityUnit.NOTIONAL)
    with pytest.raises(UnsupportedCapability, match="quantity_unit=NOTIONAL"):
        normalized_order_to_legacy_fields(order)


def test_normalized_to_legacy_rejects_extended_session() -> None:
    order = _mk_order(session=Session.POST_MARKET)
    with pytest.raises(UnsupportedCapability, match="session=POST_MARKET"):
        normalized_order_to_legacy_fields(order)


def test_normalized_reduce_only_maps_to_mis() -> None:
    order = _mk_order(position_effect=PositionEffect.REDUCE_ONLY)
    out = normalized_order_to_legacy_fields(order)
    assert out["product"] == "MIS"


def test_normalized_none_effect_defaults_to_cnc() -> None:
    order = _mk_order(position_effect=PositionEffect.NONE)
    out = normalized_order_to_legacy_fields(order)
    assert out["product"] == "CNC"


def test_normalized_legacy_product_hint_overrides_cnc() -> None:
    order = _mk_order(extra={"legacy_product_hint": "NRML"})
    out = normalized_order_to_legacy_fields(order)
    assert out["product"] == "NRML"


def test_normalized_to_legacy_carries_side() -> None:
    sell = _mk_order(side=OrderSide.SELL)
    out = normalized_order_to_legacy_fields(sell)
    assert out["side"] == "SELL"
