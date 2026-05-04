"""Regression: v1 bridge /quotes /depth /multiquotes use real OHLC
from quote.metadata when available, instead of stamping ``last``
into every field.

The Alpaca quote adapter (post-snapshot-endpoint switch) populates
``open``, ``high``, ``low``, ``close``, ``prev_close``, ``volume`` in
``NormalizedQuote.metadata``. The v1 bridge must surface those
through the v1 response shape rather than always echoing ``last``.

Adapters that don't populate the metadata (older paths or other
brokers) keep the legacy behavior — ``last`` is the fallback.
"""

from __future__ import annotations

from decimal import Decimal

from services.v1_compat_bridge import _meta_float


def test_meta_float_returns_value_when_present():
    meta = {"high": Decimal("175.10")}
    assert _meta_float(meta, "high", 0.0) == 175.10


def test_meta_float_returns_default_when_missing():
    assert _meta_float({}, "high", 100.0) == 100.0


def test_meta_float_returns_default_when_value_is_none():
    """Adapters that pre-allocate keys with None when the upstream
    field is absent — must not crash, falls back to ``last``.
    """
    assert _meta_float({"high": None}, "high", 100.0) == 100.0


def test_meta_float_returns_default_when_value_unparseable():
    assert _meta_float({"high": "n/a"}, "high", 100.0) == 100.0


def test_meta_float_handles_string_decimals():
    """OHLC values may arrive as Decimal strings (typical Alpaca shape)."""
    assert _meta_float({"open": "174.50"}, "open", 0.0) == 174.50


def test_meta_float_handles_integer_volume():
    assert _meta_float({"volume": 12345678}, "volume", 0) == 12345678.0
