"""Phase 9 v4 (ADR 0027) — US options provider.

OCC OSI 21-character format:

    <root[6]><yymmdd[6]><C/P[1]><strike_dollars[5]><strike_decimals[3]>

Example: ``AAPL  240419C00185000`` → AAPL / 2024-04-19 / CALL / 185.000.
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

REGION_CODE = "us"
_LOT_SIZE = 100
_MULTIPLIER = 100
_VENUE_CODE = "OPRA"


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
            f"OCC OSI grammar mismatch: expected 21 chars, got {len(symbol)} for {symbol!r}"
        )
    root = symbol[:6].rstrip()
    yymmdd = symbol[6:12]
    cp = symbol[12]
    strike_int = symbol[13:21]
    if cp not in ("C", "P"):
        raise ValueError(f"OSI right must be C or P; got {cp!r}")
    if not strike_int.isdigit():
        raise ValueError(f"OSI strike must be digits; got {strike_int!r}")
    if not yymmdd.isdigit():
        raise ValueError(f"OSI expiry must be 6 digits; got {yymmdd!r}")
    expiry = datetime.strptime(yymmdd, "%y%m%d").date()
    strike = Decimal(strike_int) / Decimal("1000")
    return OptionContract(
        underlying=root,
        expiry=expiry,
        right=OptionRight.CALL if cp == "C" else OptionRight.PUT,
        strike=strike,
        lot_size=_LOT_SIZE,
        multiplier=_MULTIPLIER,
        currency="USD",
        venue_code=_VENUE_CODE,
    )


def _strike_step_for_price(price: Decimal) -> Decimal:
    """Mock chain strike spacing heuristic."""
    if price < Decimal("25"):
        return Decimal("1")
    if price < Decimal("100"):
        return Decimal("2.5")
    if price < Decimal("500"):
        return Decimal("5")
    return Decimal("10")


class USOptionsProvider:
    region_code = REGION_CODE

    def parse_option_symbol(self, symbol: str) -> OptionContract:
        return _parse_osi(symbol)

    def format_option_symbol(self, contract: OptionContract) -> str:
        return _format_osi(contract)

    def list_expiries(self, underlying: str, asof: date) -> list[date]:
        # Standard US: weekly Fridays + monthly (third Friday).
        out: list[date] = []
        d = asof
        while d.weekday() != 4:  # Friday
            d = d + timedelta(days=1)
        for _ in range(8):
            out.append(d)
            d = d + timedelta(days=7)
        return out

    def get_chain(self, underlying: str, expiry: date) -> OptionChain:
        # Mock chain: 5 strikes around $185 (for AAPL-shaped) spaced
        # via the heuristic.
        center = Decimal("185")
        step = _strike_step_for_price(center)
        strikes = [center + step * Decimal(i) for i in range(-2, 3)]
        calls = [
            OptionContract(
                underlying=underlying,
                expiry=expiry,
                right=OptionRight.CALL,
                strike=s,
                lot_size=_LOT_SIZE,
                multiplier=_MULTIPLIER,
                currency="USD",
                venue_code=_VENUE_CODE,
            )
            for s in strikes
        ]
        puts = [
            OptionContract(
                underlying=underlying,
                expiry=expiry,
                right=OptionRight.PUT,
                strike=s,
                lot_size=_LOT_SIZE,
                multiplier=_MULTIPLIER,
                currency="USD",
                venue_code=_VENUE_CODE,
            )
            for s in strikes
        ]
        return OptionChain(underlying=underlying, expiry=expiry, calls=calls, puts=puts)

    def compute_greeks(
        self, contract: OptionContract, market: MarketSnapshot, iv: Decimal,
    ) -> Greeks:
        return _compute_greeks(contract, market, iv)

    def compute_iv(
        self, contract: OptionContract, premium: Decimal, market: MarketSnapshot,
    ) -> Decimal:
        return _implied_vol(contract, market, premium)

    def compute_oi_profile(self, underlying: str, expiry: date) -> OIProfile:
        chain = self.get_chain(underlying, expiry)
        by_strike: dict[Decimal, tuple[Decimal, Decimal]] = {}
        for call, put in zip(chain.calls, chain.puts):
            by_strike[call.strike] = (Decimal("5000"), Decimal("4500"))
        return OIProfile(underlying=underlying, expiry=expiry, by_strike=by_strike)

    def supported_strategies(self) -> set[str]:
        return {
            "STRADDLE", "STRANGLE", "IRON_CONDOR", "BUTTERFLY",
            "BULL_CALL_SPREAD", "BEAR_PUT_SPREAD", "WEEKLY_BUTTERFLY",
        }

    def lot_size_for(self, contract: OptionContract) -> int:
        return _LOT_SIZE


__all__ = ["REGION_CODE", "USOptionsProvider"]
