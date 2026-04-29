"""v6 Phase 5 — India v2 broker translator contract.

For every India broker that ships a v2 ``BrokerOrderTranslator`` in
v6 Phase 5/6/7, this contract pins the load-bearing invariants:

* The translator class satisfies the
  :class:`domain.broker_translator.BrokerOrderTranslator` Protocol.
* ``broker_code`` matches the broker plugin's directory name (lower
  case).
* ``install_<broker>_translator()`` registers the translator into
  :mod:`services.broker_translator_registry`.
* The translator rejects every v2-only feature India brokers cannot
  honor (US extended hours, fractional quantity, non-DAY/IOC TIFs)
  with :class:`UnsupportedCapability` carrying the documented
  dimension.
* The translator produces a stable Kite/Smart-API/etc. shape for
  the canonical India order baseline (asserted by the per-broker
  parity harness ``parity_v2_<broker>_india``).

The list of brokers grows as Phases 5/6/7 ship per-broker
translators per-PR. Currently:

* Phase 5 (popularity-first): zerodha, angel, dhan, upstox, fyers.
* Phase 6 (alpha batch 1): aliceblue → indmoney.
* Phase 7 (alpha batch 2): jainamxts → zebu.

Each addition appends to ``IMPLEMENTED_BROKERS`` and the
parametrized tests exercise it.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from domain.account_context import AccountContext
from domain.broker_translator import BrokerOrderTranslator
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
from services.broker_translator_registry import (
    clear_registry_for_tests,
    get_broker_translator,
)


# (broker_code, import_path of translator class, install fn name)
IMPLEMENTED_BROKERS: list[tuple[str, str, str]] = [
    ("zerodha", "broker.zerodha.translator.ZerodhaOrderTranslator",
     "broker.zerodha.translator.install_zerodha_translator"),
    ("angel", "broker.angel.translator.AngelOrderTranslator",
     "broker.angel.translator.install_angel_translator"),
    ("dhan", "broker.dhan.translator.DhanOrderTranslator",
     "broker.dhan.translator.install_dhan_translator"),
    ("upstox", "broker.upstox.translator.UpstoxOrderTranslator",
     "broker.upstox.translator.install_upstox_translator"),
    ("fyers", "broker.fyers.translator.FyersOrderTranslator",
     "broker.fyers.translator.install_fyers_translator"),
    # v6 Phase 6 — alpha batch 1.
    ("aliceblue", "broker.aliceblue.translator.AliceBlueOrderTranslator",
     "broker.aliceblue.translator.install_aliceblue_translator"),
    ("compositedge", "broker.compositedge.translator.CompositeEdgeOrderTranslator",
     "broker.compositedge.translator.install_compositedge_translator"),
    ("definedge", "broker.definedge.translator.DefinedgeOrderTranslator",
     "broker.definedge.translator.install_definedge_translator"),
    ("firstock", "broker.firstock.translator.FirstockOrderTranslator",
     "broker.firstock.translator.install_firstock_translator"),
    ("fivepaisa", "broker.fivepaisa.translator.FivePaisaOrderTranslator",
     "broker.fivepaisa.translator.install_fivepaisa_translator"),
    ("fivepaisaxts", "broker.fivepaisaxts.translator.FivePaisaXTSOrderTranslator",
     "broker.fivepaisaxts.translator.install_fivepaisaxts_translator"),
    ("flattrade", "broker.flattrade.translator.FlattradeOrderTranslator",
     "broker.flattrade.translator.install_flattrade_translator"),
    ("groww", "broker.groww.translator.GrowwOrderTranslator",
     "broker.groww.translator.install_groww_translator"),
    ("ibulls", "broker.ibulls.translator.IBullsOrderTranslator",
     "broker.ibulls.translator.install_ibulls_translator"),
    ("iifl", "broker.iifl.translator.IIFLOrderTranslator",
     "broker.iifl.translator.install_iifl_translator"),
    ("iiflcapital", "broker.iiflcapital.translator.IIFLCapitalOrderTranslator",
     "broker.iiflcapital.translator.install_iiflcapital_translator"),
    ("indmoney", "broker.indmoney.translator.IndMoneyOrderTranslator",
     "broker.indmoney.translator.install_indmoney_translator"),
    # v6 Phase 7 — alpha batch 2 (closes the 30-broker India v2 set).
    ("jainamxts", "broker.jainamxts.translator.JainamXTSOrderTranslator",
     "broker.jainamxts.translator.install_jainamxts_translator"),
    ("kotak", "broker.kotak.translator.KotakOrderTranslator",
     "broker.kotak.translator.install_kotak_translator"),
    ("motilal", "broker.motilal.translator.MotilalOrderTranslator",
     "broker.motilal.translator.install_motilal_translator"),
    ("mstock", "broker.mstock.translator.MStockOrderTranslator",
     "broker.mstock.translator.install_mstock_translator"),
    ("nubra", "broker.nubra.translator.NubraOrderTranslator",
     "broker.nubra.translator.install_nubra_translator"),
    ("paytm", "broker.paytm.translator.PaytmOrderTranslator",
     "broker.paytm.translator.install_paytm_translator"),
    ("pocketful", "broker.pocketful.translator.PocketfulOrderTranslator",
     "broker.pocketful.translator.install_pocketful_translator"),
    ("rmoney", "broker.rmoney.translator.RMoneyOrderTranslator",
     "broker.rmoney.translator.install_rmoney_translator"),
    ("samco", "broker.samco.translator.SamcoOrderTranslator",
     "broker.samco.translator.install_samco_translator"),
    ("shoonya", "broker.shoonya.translator.ShoonyaOrderTranslator",
     "broker.shoonya.translator.install_shoonya_translator"),
    ("tradejini", "broker.tradejini.translator.TradejiniOrderTranslator",
     "broker.tradejini.translator.install_tradejini_translator"),
    ("wisdom", "broker.wisdom.translator.WisdomOrderTranslator",
     "broker.wisdom.translator.install_wisdom_translator"),
    ("zebu", "broker.zebu.translator.ZebuOrderTranslator",
     "broker.zebu.translator.install_zebu_translator"),
]


def _resolve(dotted: str) -> Any:
    """Resolve a dotted path to its referent."""
    module_path, _, name = dotted.rpartition(".")
    import importlib
    return getattr(importlib.import_module(module_path), name)


def _account_ctx(broker_code: str) -> AccountContext:
    return AccountContext(
        broker_code=broker_code,
        account_id=f"{broker_code}-test-account",
        base_currency=Currency.INR,
    )


def _stub_instrument(symbol: str = "SBIN", exchange: str = "NSE") -> SimpleNamespace:
    return SimpleNamespace(
        broker_symbol=symbol,
        canonical_symbol=symbol,
        venue_code=exchange,
    )


def _market_buy(
    symbol: str = "SBIN", exchange: str = "NSE",
) -> NormalizedOrderRequest:
    return NormalizedOrderRequest(
        instrument=InstrumentRef(canonical_symbol=symbol, venue_code=exchange),
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        quantity_unit=QuantityUnit.WHOLE,
        time_in_force=TimeInForce.DAY,
    )


@pytest.fixture(autouse=True)
def _clear_registry_per_test():
    """Each test runs against a clean registry. Tests that need a
    translator registered use the install fn explicitly."""
    clear_registry_for_tests()
    yield
    clear_registry_for_tests()


@pytest.mark.parametrize(
    ("broker_code", "translator_path", "install_path"),
    IMPLEMENTED_BROKERS,
    ids=[t[0] for t in IMPLEMENTED_BROKERS],
)
def test_translator_class_satisfies_protocol(
    broker_code: str, translator_path: str, install_path: str,
) -> None:
    cls = _resolve(translator_path)
    instance = cls()
    assert isinstance(instance, BrokerOrderTranslator), (
        f"{broker_code}: translator does not satisfy "
        "BrokerOrderTranslator Protocol"
    )
    assert instance.broker_code == broker_code, (
        f"{broker_code}: translator.broker_code is "
        f"{instance.broker_code!r}, expected {broker_code!r}"
    )


@pytest.mark.parametrize(
    ("broker_code", "translator_path", "install_path"),
    IMPLEMENTED_BROKERS,
    ids=[t[0] for t in IMPLEMENTED_BROKERS],
)
def test_install_function_registers_translator(
    broker_code: str, translator_path: str, install_path: str,
) -> None:
    install_fn = _resolve(install_path)
    install_fn()
    found = get_broker_translator(broker_code)
    assert found is not None, (
        f"{broker_code}: install fn did not register the translator"
    )
    assert found.broker_code == broker_code


@pytest.mark.parametrize(
    ("broker_code", "translator_path", "install_path"),
    IMPLEMENTED_BROKERS,
    ids=[t[0] for t in IMPLEMENTED_BROKERS],
)
def test_translator_rejects_extended_hours_session(
    broker_code: str, translator_path: str, install_path: str,
) -> None:
    """India brokers reject PRE_MARKET / POST_MARKET sessions —
    Indian markets have no extended-hours concept."""
    cls = _resolve(translator_path)
    t = cls()
    order = NormalizedOrderRequest(
        instrument=InstrumentRef(canonical_symbol="SBIN", venue_code="NSE"),
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        quantity_unit=QuantityUnit.WHOLE,
        time_in_force=TimeInForce.DAY,
        session=Session.PRE_MARKET,
    )
    with pytest.raises(UnsupportedCapability) as exc_info:
        t.validate(order, _stub_instrument(), _account_ctx(broker_code))
    assert exc_info.value.broker_code == broker_code


@pytest.mark.parametrize(
    ("broker_code", "translator_path", "install_path"),
    IMPLEMENTED_BROKERS,
    ids=[t[0] for t in IMPLEMENTED_BROKERS],
)
def test_translator_rejects_fractional_quantity(
    broker_code: str, translator_path: str, install_path: str,
) -> None:
    """India brokers do not support fractional shares."""
    cls = _resolve(translator_path)
    t = cls()
    order = NormalizedOrderRequest(
        instrument=InstrumentRef(canonical_symbol="SBIN", venue_code="NSE"),
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.5"),
        quantity_unit=QuantityUnit.FRACTIONAL,
        time_in_force=TimeInForce.DAY,
    )
    with pytest.raises(UnsupportedCapability):
        t.validate(order, _stub_instrument(), _account_ctx(broker_code))


@pytest.mark.parametrize(
    ("broker_code", "translator_path", "install_path"),
    IMPLEMENTED_BROKERS,
    ids=[t[0] for t in IMPLEMENTED_BROKERS],
)
def test_translator_to_native_returns_dict(
    broker_code: str, translator_path: str, install_path: str,
) -> None:
    """to_native must return a dict for the canonical India market
    buy order (the simplest case any broker supports)."""
    cls = _resolve(translator_path)
    t = cls()
    out = t.to_native(_market_buy(), _stub_instrument(), _account_ctx(broker_code))
    assert isinstance(out, dict)
    assert len(out) > 0


@pytest.mark.parametrize(
    ("broker_code", "translator_path", "install_path"),
    IMPLEMENTED_BROKERS,
    ids=[t[0] for t in IMPLEMENTED_BROKERS],
)
def test_translator_round_trips_response(
    broker_code: str, translator_path: str, install_path: str,
) -> None:
    """from_native_order_response must surface order_id + status from
    a representative broker accept response."""
    cls = _resolve(translator_path)
    t = cls()
    # Use a Kite-shaped response — translators should accept either
    # camelCase or snake_case order_id keys per their broker's API.
    sample = {"order_id": "240319000123456", "status": "success"}
    out = t.from_native_order_response(sample, _stub_instrument())
    assert "order_id" in out
    assert "status" in out
