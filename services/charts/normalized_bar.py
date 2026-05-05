"""Phase 1 — Datafeed Foundation: NormalizedBar shape for chart datafeeds.

Mirrors ``frontend/src/charts/types/bar.ts``. Decimal fields are
``decimal.Decimal`` in Python and serialize as decimal-string at the
wire layer.

This is intentionally a NEW shape, distinct from the existing
``domain.broker_market_data.NormalizedBar`` (which is part of the v3
broker-bar-adapter contract). The two shapes round-trip into each other
via :func:`from_broker_bar` / :func:`to_dict`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class ChartNormalizedBar:
    """OHLCV bar in chart wire shape.

    All decimal fields use :class:`decimal.Decimal` for precision; the
    wire encoder converts to string at the API boundary.
    """

    t: int  # UTC seconds, epoch
    o: Decimal
    h: Decimal
    l: Decimal  # noqa: E741 — single-letter is the wire contract
    c: Decimal
    v: Decimal
    oi: Decimal | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the {t, o, h, l, c, v, oi} wire shape."""
        return {
            "t": int(self.t),
            "o": str(self.o),
            "h": str(self.h),
            "l": str(self.l),
            "c": str(self.c),
            "v": str(self.v),
            "oi": str(self.oi) if self.oi is not None else None,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ChartNormalizedBar:
        """Deserialize a {t, o, h, l, c, v, oi} dict (decimal-strings)."""
        oi_val = raw.get("oi")
        return cls(
            t=int(raw["t"]),
            o=Decimal(str(raw["o"])),
            h=Decimal(str(raw["h"])),
            l=Decimal(str(raw["l"])),
            c=Decimal(str(raw["c"])),
            v=Decimal(str(raw["v"])),
            oi=Decimal(str(oi_val)) if oi_val is not None else None,
        )


def from_broker_bar(b: Any) -> ChartNormalizedBar:
    """Project a ``domain.broker_market_data.NormalizedBar`` into the
    chart wire shape.
    """
    ts = b.ts
    if hasattr(ts, "timestamp"):
        t = int(ts.timestamp())
    else:
        t = int(ts)
    return ChartNormalizedBar(
        t=t,
        o=Decimal(str(b.open)),
        h=Decimal(str(b.high)),
        l=Decimal(str(b.low)),
        c=Decimal(str(b.close)),
        v=Decimal(str(b.volume)) if b.volume is not None else Decimal("0"),
        oi=Decimal(str(b.open_interest)) if getattr(b, "open_interest", None) is not None else None,
    )


__all__ = ["ChartNormalizedBar", "from_broker_bar"]
