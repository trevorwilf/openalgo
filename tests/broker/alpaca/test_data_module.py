"""broker/alpaca/api/data.py — legacy v1 BrokerData shim."""

from __future__ import annotations

import pytest

from broker.alpaca.api.data import BrokerData


def test_broker_data_constructible_with_auth_token():
    bd = BrokerData("dummy-token")
    assert bd.auth_token == "dummy-token"


def test_timeframe_map_is_superset_of_bar_adapter_keys():
    """Regression: /api/v1/intervals reads ``timeframe_map.keys()``.
    The data shim's set must INCLUDE every interval the bar adapter
    serves (otherwise /intervals would advertise less than the bar
    adapter can produce), but MAY add aliases like ``D`` that the
    intervals-service categorizer requires.
    """
    from broker.alpaca.api.bar_api import _TIMEFRAME_MAP

    bd = BrokerData("token")
    bar_keys = set(_TIMEFRAME_MAP.keys())
    shim_keys = set(bd.timeframe_map.keys())
    missing = bar_keys - shim_keys
    assert missing == set(), f"data shim missing intervals from bar adapter: {missing}"


def test_timeframe_map_native_values_consistent_with_bar_adapter():
    """For every interval key the bar adapter knows, the data shim
    must emit the same Alpaca-native string so a v1-routed /history
    call would request the same Alpaca timeframe as a v2 /bars call.
    """
    from broker.alpaca.api.bar_api import _TIMEFRAME_MAP

    bd = BrokerData("token")
    for key, native in _TIMEFRAME_MAP.items():
        assert bd.timeframe_map.get(key) == native


def test_timeframe_map_includes_legacy_D_alias_for_intervals_service():
    """The legacy intervals service categorizes daily by exact ``"D"``
    key. Without the alias, /api/v1/intervals would return an empty
    ``days`` list for Alpaca even though the bar adapter serves 1d.
    """
    bd = BrokerData("token")
    assert "D" in bd.timeframe_map
    assert bd.timeframe_map["D"] == bd.timeframe_map["1d"]


def test_market_timings_default_us_session():
    bd = BrokerData("token")
    assert bd.get_market_timings("NASDAQ") == {
        "start": "09:30:00",
        "end": "16:00:00",
    }
    assert bd.get_market_timings("NYSE") == bd.get_market_timings("NASDAQ")
    # Lowercase still resolves.
    assert bd.get_market_timings("nasdaq") == bd.get_market_timings("NASDAQ")


def test_market_timings_unknown_exchange_returns_default():
    bd = BrokerData("token")
    assert bd.get_market_timings("XLON") == bd.default_market_timings


def test_intervals_service_can_import_and_consume():
    """End-to-end smoke: the legacy v1 service hits this exact path.
    Pre-fix, ``importlib.import_module('broker.alpaca.api.data')``
    raised ImportError and the service returned 404
    "Broker-specific module not found".
    """
    import importlib

    mod = importlib.import_module("broker.alpaca.api.data")
    handler = mod.BrokerData("token")
    keys = list(handler.timeframe_map.keys())
    assert "1m" in keys
    assert "1h" in keys
    # Either the bar-adapter form OR the legacy D alias must be present
    # for daily; the data shim provides both.
    assert "D" in keys
    assert "1d" in keys
