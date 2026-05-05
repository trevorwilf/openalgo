"""Regression: ``_quote_dict`` stringifies Decimal values in
``NormalizedQuote.metadata`` so Flask's default JSON encoder can
serialize the response.

Bug: ``AlpacaQuoteAdapter`` post-snapshot fix populates ``open``,
``high``, ``low``, ``close``, ``prev_close``, ``volume``, and
``trade_size`` as ``Decimal`` in the metadata dict. The previous
``_quote_dict`` only stringified the top-level Decimal fields
(``bid`` / ``ask`` / ``last`` / ``*_size``), leaving metadata
Decimals raw. Flask's JSON encoder doesn't handle Decimal — every
``/api/v2/quotes`` request returned HTTP 500::

    TypeError: Object of type Decimal is not JSON serializable
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from restx_api.v2.quotes import _quote_dict


@dataclass
class _FakeQuote:
    instrument_id: str = "x"
    venue_code: str = "XNAS"
    canonical_symbol: str = "AAPL"
    bid: Decimal | None = Decimal("100.00")
    ask: Decimal | None = Decimal("100.05")
    last: Decimal | None = Decimal("100.02")
    bid_size: Decimal | None = Decimal("100")
    ask_size: Decimal | None = Decimal("200")
    timestamp: datetime | None = None
    currency: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


def test_quote_dict_stringifies_decimal_metadata():
    q = _FakeQuote(
        timestamp=datetime(2026, 5, 4, 14, 30, tzinfo=timezone.utc),
        metadata={
            "open": Decimal("174.50"),
            "high": Decimal("175.10"),
            "low": Decimal("174.20"),
            "close": Decimal("175.01"),
            "prev_close": Decimal("174.55"),
            "volume": Decimal("12345678"),
            "raw_exchange": "XNAS",
        },
    )
    d = _quote_dict(q)

    # Round-trip through json.dumps to prove the result is
    # serializable (Flask's encoder doesn't handle Decimal).
    serialized = json.dumps(d)
    assert "174.50" in serialized
    assert "12345678" in serialized

    # Spot-check the metadata is now str.
    assert d["metadata"]["open"] == "174.50"
    assert d["metadata"]["volume"] == "12345678"
    # Non-Decimal metadata values pass through unchanged.
    assert d["metadata"]["raw_exchange"] == "XNAS"


def test_quote_dict_handles_empty_metadata():
    q = _FakeQuote(metadata={})
    d = _quote_dict(q)
    assert d["metadata"] == {}


def test_quote_dict_handles_none_metadata():
    """Defensive: some adapters might not set ``metadata`` at all."""
    q = _FakeQuote()
    object.__setattr__(q, "metadata", None)
    d = _quote_dict(q)
    # Should not crash; metadata becomes empty dict.
    assert d.get("metadata") in (None, {})
