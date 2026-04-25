"""Phase 5 — telegram_bot_service._cs reads currency from broker capabilities.

Replaces the prior `broker in CRYPTO_BROKERS → $; else → ₹` inference
with a capability-aware lookup: the user's symbol comes from
``BrokerCapabilities.base_currency`` when available, broker_type=crypto
falls through to $, and only legacy India brokers (no plugin metadata)
keep ₹.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.fixture
def service(monkeypatch):
    """Build a minimal TelegramBotService stub with the helper bound."""
    # Avoid loading the full bot module — we only need the _cs method.
    # Import from the live module so we exercise the real logic.
    import services.telegram_bot_service as mod

    cls = mod.TelegramBotService
    obj = cls.__new__(cls)
    return obj


def _stub_caps(monkeypatch, broker_code: str, **kwargs):
    caps = SimpleNamespace(
        base_currency=kwargs.get("base_currency"),
        broker_type=kwargs.get("broker_type", "IN_stock"),
        supported_regions=kwargs.get("supported_regions", []),
    )

    def _fake(name):
        return caps if name == broker_code else None

    monkeypatch.setattr("utils.plugin_loader.get_broker_capabilities", _fake)


def test_inr_for_india_broker(service, monkeypatch):
    _stub_caps(
        monkeypatch,
        "zerodha",
        base_currency=SimpleNamespace(value="INR"),
        broker_type="IN_stock",
        supported_regions=["india"],
    )
    assert service._cs({"broker": "zerodha"}) == "₹"


def test_usd_for_us_broker(service, monkeypatch):
    _stub_caps(
        monkeypatch,
        "alpaca",
        base_currency=SimpleNamespace(value="USD"),
        broker_type="US_stock",
        supported_regions=["us"],
    )
    assert service._cs({"broker": "alpaca"}) == "$"


def test_eur_for_eu_broker(service, monkeypatch):
    _stub_caps(
        monkeypatch,
        "fakeeu",
        base_currency=SimpleNamespace(value="EUR"),
        broker_type="EU_stock",
        supported_regions=["eu"],
    )
    assert service._cs({"broker": "fakeeu"}) == "€"


def test_gbp_for_uk_broker(service, monkeypatch):
    _stub_caps(
        monkeypatch,
        "fakeuk",
        base_currency=SimpleNamespace(value="GBP"),
        broker_type="UK_stock",
        supported_regions=["uk"],
    )
    assert service._cs({"broker": "fakeuk"}) == "£"


def test_btc_for_crypto_broker_with_btc_base(service, monkeypatch):
    _stub_caps(
        monkeypatch,
        "fakecx",
        base_currency=SimpleNamespace(value="BTC"),
        broker_type="crypto",
    )
    assert service._cs({"broker": "fakecx"}) == "₿"


def test_unknown_currency_returns_code(service, monkeypatch):
    _stub_caps(
        monkeypatch,
        "fakejp",
        base_currency=SimpleNamespace(value="JPY"),
        broker_type="JP_stock",
        supported_regions=["jp"],
    )
    # ¥ for JPY is in the symbol map.
    assert service._cs({"broker": "fakejp"}) == "¥"


def test_no_capabilities_legacy_fallback_returns_inr(service, monkeypatch):
    monkeypatch.setattr(
        "utils.plugin_loader.get_broker_capabilities", lambda b: None
    )
    # Broker not in CRYPTO_BROKERS → legacy fallback returns ₹.
    assert service._cs({"broker": "unknown_broker"}) == "₹"


def test_no_capabilities_crypto_in_constants_returns_dollar(service, monkeypatch):
    monkeypatch.setattr(
        "utils.plugin_loader.get_broker_capabilities", lambda b: None
    )
    from utils.constants import CRYPTO_BROKERS

    if not CRYPTO_BROKERS:  # pragma: no cover
        pytest.skip("CRYPTO_BROKERS empty in this build")
    sample = next(iter(CRYPTO_BROKERS))
    assert service._cs({"broker": sample}) == "$"
