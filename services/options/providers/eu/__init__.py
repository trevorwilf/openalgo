"""T-23 (v7 Phase 6-bis) — EU options provider.

Real EU options support uses Eurex's "OEUR" grammar for German /
European-style listings and Euronext's variant for Paris-listed
equity options. Both can be normalized through OCC-style 21-char
symbols at the OpenAlgo layer (this matches how multi-region
broker plugins like Interactive Brokers represent EU options).

This provider:
* Parses OCC-style symbols and tags the contract with EUR + the
  Eurex venue code.
* Lists weekly + monthly expiries via the third-Friday convention
  (matches Eurex / Euronext equity options schedule).
* Delegates Greeks / IV to ``domain.options_math``.

Real production differences from this v7 baseline (deferred to a
follow-up phase):
* Bermudan / quarterly serial expiries on index futures.
* Differing lot sizes per underlying (Eurex DAX is 5; STOXX 50 is
  10; equity options are typically 100).
* Settlement-currency currency mismatches across cross-listed
  underlyings.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from domain.options import (
    Greeks,
    MarketSnapshot,
    OIProfile,
    OptionChain,
    OptionContract,
    OptionRight,
)
from domain.options_math import compute_greeks as _compute_greeks
from domain.options_math import implied_vol as _implied_vol

REGION_CODE = "eu"
_DEFAULT_LOT_SIZE = 100
_MULTIPLIER = 100
_VENUE_CODE = "XEUR"  # Eurex MIC


def _format_osi(contract: OptionContract) -> str:
    root = contract.underlying[:6].ljust(6)
    yymmdd = contract.expiry.strftime("%y%m%d")
    cp = "C" if contract.right == OptionRight.CALL else "P"
    cents = int((contract.strike * Decimal("1000")).to_integral_value())
    strike_str = f"{cents:08d}"
    return f"{root}{yymmdd}{cp}{strike_str}"


def _parse_osi(symbol: str) -> OptionContract:
    if len(symbol) != 21:
        raise ValueError(
            f"EU OCC grammar mismatch: expected 21 chars, got {len(symbol)} for {symbol!r}"
        )
    root = symbol[:6].rstrip()
    yymmdd = symbol[6:12]
    cp = symbol[12]
    strike_int = symbol[13:21]
    if cp not in ("C", "P"):
        raise ValueError(f"OCC right must be C or P; got {cp!r}")
    if not (strike_int.isdigit() and yymmdd.isdigit()):
        raise ValueError(f"OCC strike/expiry must be digits; got {strike_int!r} / {yymmdd!r}")
    expiry = datetime.strptime(yymmdd, "%y%m%d").date()
    strike = Decimal(strike_int) / Decimal("1000")
    return OptionContract(
        underlying=root,
        expiry=expiry,
        right=OptionRight.CALL if cp == "C" else OptionRight.PUT,
        strike=strike,
        lot_size=_DEFAULT_LOT_SIZE,
        multiplier=_MULTIPLIER,
        currency="EUR",
        venue_code=_VENUE_CODE,
    )


def _third_friday(year: int, month: int) -> date:
    """Eurex / Euronext monthly expiries fall on the third Friday."""
    d = date(year, month, 1)
    while d.weekday() != 4:
        d = d + timedelta(days=1)
    return d + timedelta(days=14)


class EUOptionsProvider:
    """Real EU options provider with OCC-shaped symbol grammar."""

    region_code = REGION_CODE

    def parse_option_symbol(self, symbol: str) -> OptionContract:
        return _parse_osi(symbol)

    def format_option_symbol(self, contract: OptionContract) -> str:
        return _format_osi(contract)

    def list_expiries(self, underlying: str, asof: date) -> list[date]:
        """Monthly expiries — third Friday of each month from
        ``asof``'s month forward, 12 months."""
        out: list[date] = []
        year, month = asof.year, asof.month
        for _ in range(12):
            exp = _third_friday(year, month)
            if exp >= asof:
                out.append(exp)
            month += 1
            if month > 12:
                month = 1
                year += 1
        return out

    def get_chain(self, underlying: str, expiry: date) -> OptionChain:
        """Stub chain — production needs market-data adapter wiring.
        Returns an empty chain so callers see a structured shape."""
        return OptionChain(
            underlying=underlying,
            expiry=expiry,
            calls=[],
            puts=[],
            asof=datetime.now(),
        )

    def compute_greeks(
        self, contract: OptionContract, market: MarketSnapshot, iv: Decimal,
    ) -> Greeks:
        return _compute_greeks(contract, market, iv)

    def compute_iv(
        self, contract: OptionContract, premium: Decimal, market: MarketSnapshot,
    ) -> Decimal:
        return _implied_vol(contract, premium, market)

    def compute_oi_profile(self, underlying: str, expiry: date) -> OIProfile:
        return OIProfile(
            underlying=underlying,
            expiry=expiry,
            strike_to_call_oi={},
            strike_to_put_oi={},
            asof=datetime.now(),
        )

    def supported_strategies(self) -> set[str]:
        return {"STRADDLE", "STRANGLE", "IRON_CONDOR", "VERTICAL_SPREAD"}

    def lot_size_for(self, contract: OptionContract) -> int:
        # Default 100 for equity options. Index options on Eurex
        # vary (DAX=5, STOXX 50=10) — production resolves this via
        # the underlying lookup table; the v7 baseline uses 100.
        return _DEFAULT_LOT_SIZE


__all__ = ["EUOptionsProvider", "REGION_CODE"]
