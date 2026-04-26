"""Phase 9 v4 (ADR 0027) — Black-Scholes math used by every options provider.

Region-neutral. The India provider and US provider both call into
this module rather than re-implementing the math.
"""

from __future__ import annotations

import math
from decimal import Decimal

from domain.options import Greeks, MarketSnapshot, OptionContract, OptionRight


_SQRT_2 = math.sqrt(2.0)


def _norm_cdf(x: float) -> float:
    """Cumulative distribution function for the standard normal."""
    return 0.5 * (1.0 + math.erf(x / _SQRT_2))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _years_to_expiry(contract: OptionContract, asof) -> float:
    """Calendar-day approximation. Good enough for sandbox / test
    fixtures; production uses business days + actual settlement
    rules."""
    days = (contract.expiry - asof).days
    return max(days, 0) / 365.0


def black_scholes_price(
    contract: OptionContract,
    market: MarketSnapshot,
    iv: Decimal,
) -> Decimal:
    """Return the Black-Scholes price for the contract at ``iv``.

    Uses calendar-day time-to-expiry. ``iv`` is the annualized
    implied volatility as a decimal (0.20 = 20%).
    """
    asof = market.asof or contract.expiry
    t = _years_to_expiry(contract, asof)
    if t <= 0:
        # Intrinsic value at expiry.
        intrinsic = (
            float(market.underlying_price) - float(contract.strike)
            if contract.right == OptionRight.CALL
            else float(contract.strike) - float(market.underlying_price)
        )
        return Decimal(str(max(intrinsic, 0.0)))

    s = float(market.underlying_price)
    k = float(contract.strike)
    r = float(market.risk_free_rate)
    q = float(market.dividend_yield)
    sigma = float(iv)
    if sigma <= 0:
        return Decimal("0")

    sqrt_t = math.sqrt(t)
    d1 = (math.log(s / k) + (r - q + 0.5 * sigma * sigma) * t) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t

    if contract.right == OptionRight.CALL:
        price = s * math.exp(-q * t) * _norm_cdf(d1) - k * math.exp(-r * t) * _norm_cdf(d2)
    else:
        price = k * math.exp(-r * t) * _norm_cdf(-d2) - s * math.exp(-q * t) * _norm_cdf(-d1)
    return Decimal(str(max(price, 0.0)))


def compute_greeks(
    contract: OptionContract,
    market: MarketSnapshot,
    iv: Decimal,
) -> Greeks:
    """Compute Black-Scholes Greeks for the contract at ``iv``."""
    asof = market.asof or contract.expiry
    t = _years_to_expiry(contract, asof)
    if t <= 0:
        return Greeks(
            delta=Decimal("0"),
            gamma=Decimal("0"),
            theta=Decimal("0"),
            vega=Decimal("0"),
            rho=Decimal("0"),
        )

    s = float(market.underlying_price)
    k = float(contract.strike)
    r = float(market.risk_free_rate)
    q = float(market.dividend_yield)
    sigma = float(iv)
    if sigma <= 0:
        return Greeks(
            delta=Decimal("0"),
            gamma=Decimal("0"),
            theta=Decimal("0"),
            vega=Decimal("0"),
            rho=Decimal("0"),
        )

    sqrt_t = math.sqrt(t)
    d1 = (math.log(s / k) + (r - q + 0.5 * sigma * sigma) * t) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t

    n_d1 = _norm_pdf(d1)
    discount_q = math.exp(-q * t)
    discount_r = math.exp(-r * t)

    if contract.right == OptionRight.CALL:
        delta = discount_q * _norm_cdf(d1)
        theta = (
            -(s * n_d1 * sigma * discount_q) / (2.0 * sqrt_t)
            - r * k * discount_r * _norm_cdf(d2)
            + q * s * discount_q * _norm_cdf(d1)
        )
        rho = k * t * discount_r * _norm_cdf(d2)
    else:
        delta = discount_q * (_norm_cdf(d1) - 1.0)
        theta = (
            -(s * n_d1 * sigma * discount_q) / (2.0 * sqrt_t)
            + r * k * discount_r * _norm_cdf(-d2)
            - q * s * discount_q * _norm_cdf(-d1)
        )
        rho = -k * t * discount_r * _norm_cdf(-d2)

    gamma = (discount_q * n_d1) / (s * sigma * sqrt_t)
    vega = s * discount_q * n_d1 * sqrt_t / 100.0  # per 1% change in vol

    return Greeks(
        delta=Decimal(str(delta)),
        gamma=Decimal(str(gamma)),
        theta=Decimal(str(theta / 365.0)),  # per-day
        vega=Decimal(str(vega)),
        rho=Decimal(str(rho)),
    )


def implied_vol(
    contract: OptionContract,
    market: MarketSnapshot,
    target_premium: Decimal,
    *,
    tolerance: float = 1e-4,
    max_iterations: int = 64,
) -> Decimal:
    """Solve for implied vol via bisection. Returns 0 when no solution."""
    target = float(target_premium)
    lo, hi = 0.0001, 5.0
    for _ in range(max_iterations):
        mid = (lo + hi) / 2.0
        price = float(black_scholes_price(contract, market, Decimal(str(mid))))
        if abs(price - target) < tolerance:
            return Decimal(str(mid))
        if price < target:
            lo = mid
        else:
            hi = mid
    return Decimal(str((lo + hi) / 2.0))


__all__ = [
    "black_scholes_price",
    "compute_greeks",
    "implied_vol",
]
