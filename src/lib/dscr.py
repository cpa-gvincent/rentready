"""
Core deal math for RentReady: DSCR, PITIA, equity triangulation, confidence.

This module is the *canonical, unit-tested reference* for the formulas. It is
plain Python (no Spark) so it can be tested in isolation and reused anywhere.
The gold pipeline (src/pipelines/gold.py) mirrors these formulas as native
Spark column expressions for scale — if you change a formula here, change it
there too, and the tests in tests/test_dscr.py guard the contract.

Conventions
-----------
- All rates are annual decimals (0.075 == 7.5%).
- All "monthly_*" values are dollars per month.
- DSCR uses gross rent / PITIA by default (the common DSCR-loan convention).
  Set use_noi=True to use NOI (rent net of operating expenses) / debt service,
  which some lenders prefer. Be explicit about which one you sell on.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Optional, Sequence


# --------------------------------------------------------------------------- #
# Debt service
# --------------------------------------------------------------------------- #
def monthly_mortgage_payment(loan_amount: float, annual_rate: float, term_years: int) -> float:
    """Standard amortizing P&I payment."""
    if loan_amount <= 0:
        return 0.0
    n = term_years * 12
    r = annual_rate / 12.0
    if r == 0:
        return loan_amount / n
    factor = (1 + r) ** n
    return loan_amount * r * factor / (factor - 1)


def pitia(
    loan_amount: float,
    annual_rate: float,
    term_years: int,
    annual_property_tax: float,
    annual_insurance: float,
    monthly_hoa: float = 0.0,
) -> float:
    """Principal, Interest, Taxes, Insurance, Association dues — per month."""
    pi = monthly_mortgage_payment(loan_amount, annual_rate, term_years)
    taxes = annual_property_tax / 12.0
    insurance = annual_insurance / 12.0
    return pi + taxes + insurance + monthly_hoa


# --------------------------------------------------------------------------- #
# DSCR
# --------------------------------------------------------------------------- #
def dscr(
    monthly_rent: float,
    monthly_pitia: float,
    operating_expense_ratio: float = 0.0,
    use_noi: bool = False,
) -> Optional[float]:
    """
    Debt Service Coverage Ratio.

    use_noi=False  ->  gross monthly rent / PITIA          (DSCR-loan default)
    use_noi=True   ->  (rent * (1 - opex_ratio)) / PITIA   (NOI-based)
    """
    if monthly_pitia <= 0:
        return None
    income = monthly_rent * (1 - operating_expense_ratio) if use_noi else monthly_rent
    return income / monthly_pitia


def dscr_passes(value: Optional[float], threshold: float = 1.20) -> bool:
    """Most DSCR lenders want >= 1.20; some go to 1.0 or 0.75 with reserves."""
    return value is not None and value >= threshold


# --------------------------------------------------------------------------- #
# Value triangulation + equity
# --------------------------------------------------------------------------- #
@dataclass
class ValueTriangulation:
    estimate: float          # blended value estimate (median of sources)
    spread_pct: float        # disagreement across sources, as % of estimate
    confidence: str          # "high" | "medium" | "low"
    n_sources: int


def triangulate_value(
    estimates: Sequence[float],
    high_threshold: float = 0.05,
    medium_threshold: float = 0.12,
) -> Optional[ValueTriangulation]:
    """
    Blend independent value estimates (MLS list-derived, AVM, county) into one
    number plus a confidence flag based on how tightly the sources agree.

    Tight agreement (small spread) -> high confidence.
    """
    vals = [v for v in estimates if v and v > 0]
    if not vals:
        return None
    blended = median(vals)
    spread = (max(vals) - min(vals)) / blended if blended else 1.0
    if len(vals) < 2:
        confidence = "low"          # a single source can't be corroborated
    elif spread <= high_threshold:
        confidence = "high"
    elif spread <= medium_threshold:
        confidence = "medium"
    else:
        confidence = "low"
    return ValueTriangulation(round(blended, 2), round(spread, 4), confidence, len(vals))


def instant_equity(estimated_value: float, purchase_price: float) -> float:
    """Equity the moment you buy, before any costs: value minus what you paid."""
    return estimated_value - purchase_price


def equity_after_close(
    estimated_value: float,
    purchase_price: float,
    closing_costs: float,
    rehab_costs: float = 0.0,
) -> float:
    """Equity net of the cash it takes to actually close and make rent-ready."""
    return estimated_value - (purchase_price + closing_costs + rehab_costs)


def ltv(loan_amount: float, estimated_value: float) -> Optional[float]:
    """Loan-to-value. Lower is safer; DSCR loans often cap at 0.75–0.80."""
    if estimated_value <= 0:
        return None
    return loan_amount / estimated_value


# --------------------------------------------------------------------------- #
# One-call screen
# --------------------------------------------------------------------------- #
@dataclass
class DealScreen:
    dscr: Optional[float]
    monthly_pitia: float
    instant_equity: float
    equity_after_close: float
    ltv: Optional[float]
    value_estimate: Optional[float]
    value_confidence: Optional[str]
    passes: bool


def screen_property(
    *,
    monthly_rent: float,
    purchase_price: float,
    loan_amount: float,
    annual_rate: float,
    term_years: int,
    annual_property_tax: float,
    annual_insurance: float,
    monthly_hoa: float = 0.0,
    closing_costs: float = 0.0,
    rehab_costs: float = 0.0,
    value_estimates: Sequence[float] = (),
    dscr_threshold: float = 1.20,
    max_ltv: float = 0.80,
) -> DealScreen:
    """Run the full screen for a single property. Pure function, no I/O."""
    pit = pitia(loan_amount, annual_rate, term_years, annual_property_tax,
                annual_insurance, monthly_hoa)
    ratio = dscr(monthly_rent, pit)
    tri = triangulate_value(value_estimates)
    value = tri.estimate if tri else purchase_price
    loan_to_value = ltv(loan_amount, value)

    passes = (
        dscr_passes(ratio, dscr_threshold)
        and loan_to_value is not None
        and loan_to_value <= max_ltv
    )

    return DealScreen(
        dscr=ratio,
        monthly_pitia=round(pit, 2),
        instant_equity=round(instant_equity(value, purchase_price), 2),
        equity_after_close=round(
            equity_after_close(value, purchase_price, closing_costs, rehab_costs), 2),
        ltv=round(loan_to_value, 4) if loan_to_value is not None else None,
        value_estimate=value,
        value_confidence=tri.confidence if tri else None,
        passes=passes,
    )
