"""Phase 9 v4 (ADR 0027) — India options provider.

DDMMMYY / CE-PE grammar parsing + formatting:

* ``NIFTY28MAR2420800CE`` → underlying=NIFTY, expiry=2024-03-28,
  right=CALL, strike=20800, lot_size=50, multiplier=1, currency=INR,
  venue=NFO.
* ``BANKNIFTY24APR2447500PE`` → BANKNIFTY / 2024-04-24 / PUT / 47500.

Bit-identical with the existing
``services.option_symbol_service.parse_option_symbol`` for India
inputs (parity-protected). Greeks / IV use the shared Black-Scholes
math in :mod:`domain.options_math`.

Phase 9 v4 ships the provider; the existing option services
continue to drive India option behavior directly. Wiring the
services to dispatch through this provider is Phase 9-bis.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

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

REGION_CODE = "india"

# Lot sizes for representative India indices/stocks. Real lot sizes
# come from the master contract; this static map is the parity-
# preserving default for sandbox / framework-readiness coverage.
_LOT_SIZES: dict[str, int] = {
    "NIFTY": 50,
    "BANKNIFTY": 15,
    "FINNIFTY": 25,
    "MIDCPNIFTY": 75,
    "SENSEX": 10,
    "BANKEX": 15,
}

# Pattern: <underlying><DDMMMYY><strike><CE|PE>. Underlying is the
# longest non-digit prefix. DDMMMYY is exactly 7 chars
# (2 digits + 3 letters + 2 digits). Strike may have a decimal.
_INDIA_OPTION_RE = re.compile(
    r"^(?P<underlying>[A-Z]+)(?P<expiry>\d{2}[A-Z]{3}\d{2})(?P<strike>\d+(?:\.\d+)?)(?P<right>CE|PE)$"
)


def _parse_ddmmmyy(s: str) -> date:
    return datetime.strptime(s, "%d%b%y").date()


def _format_ddmmmyy(d: date) -> str:
    return d.strftime("%d%b%y").upper()


class IndiaOptionsProvider:
    region_code = REGION_CODE

    def parse_option_symbol(self, symbol: str) -> OptionContract:
        m = _INDIA_OPTION_RE.match(symbol.strip().upper())
        if not m:
            raise ValueError(
                f"India option grammar mismatch: {symbol!r}; expected "
                "<underlying><DDMMMYY><strike><CE|PE>"
            )
        underlying = m.group("underlying")
        expiry = _parse_ddmmmyy(m.group("expiry"))
        strike = Decimal(m.group("strike"))
        right = OptionRight.CALL if m.group("right") == "CE" else OptionRight.PUT
        return OptionContract(
            underlying=underlying,
            expiry=expiry,
            right=right,
            strike=strike,
            lot_size=_LOT_SIZES.get(underlying, 1),
            multiplier=1,
            currency="INR",
            venue_code="NFO",
        )

    def format_option_symbol(self, contract: OptionContract) -> str:
        right = "CE" if contract.right == OptionRight.CALL else "PE"
        strike = contract.strike
        if strike == strike.to_integral_value():
            strike_str = str(int(strike))
        else:
            strike_str = format(strike.normalize(), "f")
        return f"{contract.underlying}{_format_ddmmmyy(contract.expiry)}{strike_str}{right}"

    def list_expiries(self, underlying: str, asof: date) -> list[date]:
        # Indian indices have weekly + monthly expiries on Thursday.
        # Generate the next 8 Thursdays (approximate weekly expiries).
        out: list[date] = []
        d = asof
        while d.weekday() != 3:  # 3 = Thursday
            d = d + timedelta(days=1)
        for _ in range(8):
            out.append(d)
            d = d + timedelta(days=7)
        return out

    def get_chain(self, underlying: str, expiry: date) -> OptionChain:
        # Mock chain: 5 strikes around 20000 spaced 100 apart.
        center = Decimal("20000")
        strikes = [center + Decimal(i * 100) for i in range(-2, 3)]
        calls = [
            OptionContract(
                underlying=underlying,
                expiry=expiry,
                right=OptionRight.CALL,
                strike=s,
                lot_size=_LOT_SIZES.get(underlying, 1),
                currency="INR",
                venue_code="NFO",
            )
            for s in strikes
        ]
        puts = [
            OptionContract(
                underlying=underlying,
                expiry=expiry,
                right=OptionRight.PUT,
                strike=s,
                lot_size=_LOT_SIZES.get(underlying, 1),
                currency="INR",
                venue_code="NFO",
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
            by_strike[call.strike] = (Decimal("100000"), Decimal("90000"))
        return OIProfile(underlying=underlying, expiry=expiry, by_strike=by_strike)

    def supported_strategies(self) -> set[str]:
        return {
            "STRADDLE", "STRANGLE", "IRON_CONDOR", "BUTTERFLY",
            "BULL_CALL_SPREAD", "BEAR_PUT_SPREAD",
        }

    def lot_size_for(self, contract: OptionContract) -> int:
        return _LOT_SIZES.get(contract.underlying, 1)


__all__ = ["IndiaOptionsProvider", "REGION_CODE"]
