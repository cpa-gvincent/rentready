from src.lib.dscr import (
    monthly_mortgage_payment,
    pitia,
    dscr,
    dscr_passes,
    triangulate_value,
    instant_equity,
    equity_after_close,
    ltv,
    screen_property,
)


class TestMonthlyMortgagePayment:
    def test_standard_case(self):
        p = monthly_mortgage_payment(200_000, 0.075, 30)
        assert abs(p - 1398.43) < 0.01, f"{p}"

    def test_zero_loan(self):
        assert monthly_mortgage_payment(0, 0.075, 30) == 0.0

    def test_zero_rate(self):
        p = monthly_mortgage_payment(120_000, 0.0, 30)
        assert abs(p - 333.33) < 0.01, f"{p}"


class TestPitia:
    def test_combines_piti_and_hoa(self):
        p = pitia(200_000, 0.075, 30, 3_600, 1_200, 100)
        assert p > 1398 + 300 + 100, f"{p}"

    def test_no_hoa_defaults_zero(self):
        p = pitia(200_000, 0.075, 30, 3_600, 1_200)
        assert p == pitia(200_000, 0.075, 30, 3_600, 1_200, 0), f"{p}"


class TestDscr:
    def test_gross_rent_default(self):
        r = dscr(2_500, 1_800)
        assert r is not None and abs(r - 1.3889) < 0.01, f"{r}"

    def test_returns_none_when_pitia_zero(self):
        assert dscr(2_500, 0) is None
        assert dscr(2_500, -1) is None

    def test_noi_based_dscr(self):
        r = dscr(2_500, 1_800, operating_expense_ratio=0.25, use_noi=True)
        expected = (2_500 * 0.75) / 1_800
        assert r is not None and abs(r - expected) < 0.001, f"{r}"


class TestDscrPasses:
    def test_above_threshold_passes(self):
        assert dscr_passes(1.35, 1.20) is True

    def test_below_threshold_fails(self):
        assert dscr_passes(1.0, 1.20) is False

    def test_none_never_passes(self):
        assert dscr_passes(None) is False


class TestTriangulateValue:
    def test_single_source_low_confidence(self):
        tv = triangulate_value([200_000])
        assert tv is not None
        assert tv.estimate == 200_000
        assert tv.confidence == "low"
        assert tv.n_sources == 1

    def test_tight_spread_high_confidence(self):
        tv = triangulate_value([198_000, 200_000, 205_000])
        assert tv is not None
        assert tv.estimate == 200_000
        assert tv.confidence == "high"

    def test_medium_spread(self):
        tv = triangulate_value([190_000, 200_000, 210_000])
        assert tv is not None
        assert tv.estimate == 200_000
        spread = (210_000 - 190_000) / 200_000
        assert 0.05 < spread <= 0.12
        assert tv.confidence == "medium"

    def test_wide_spread_low_confidence(self):
        tv = triangulate_value([150_000, 200_000, 250_000])
        assert tv is not None
        assert tv.confidence == "low"

    def test_no_valid_values_returns_none(self):
        assert triangulate_value([0, -1, None]) is None
        assert triangulate_value([]) is None


class TestInstantEquity:
    def test_positive_equity(self):
        assert instant_equity(210_000, 200_000) == 10_000

    def test_negative_equity(self):
        assert instant_equity(190_000, 200_000) == -10_000


class TestEquityAfterClose:
    def test_subtracts_costs(self):
        eq = equity_after_close(210_000, 200_000, 6_000, 4_000)
        assert eq == 0

    def test_no_rehab_default_zero(self):
        eq = equity_after_close(210_000, 200_000, 6_000)
        assert eq == 4_000


class TestLtv:
    def test_standard_case(self):
        assert ltv(150_000, 200_000) == 0.75

    def test_zero_value_returns_none(self):
        assert ltv(100_000, 0) is None


class TestScreenProperty:
    def test_passing_screen(self):
        screen = screen_property(
            monthly_rent=2_500,
            purchase_price=200_000,
            loan_amount=150_000,
            annual_rate=0.075,
            term_years=30,
            annual_property_tax=3_600,
            annual_insurance=1_200,
            value_estimates=[198_000, 200_000, 205_000],
        )
        assert screen.passes is True
        assert screen.dscr is not None and screen.dscr > 1.0
        assert screen.monthly_pitia > 0
        assert screen.value_confidence == "high"

    def test_failing_screen_low_rent(self):
        screen = screen_property(
            monthly_rent=1_200,
            purchase_price=200_000,
            loan_amount=150_000,
            annual_rate=0.075,
            term_years=30,
            annual_property_tax=3_600,
            annual_insurance=1_200,
        )
        assert screen.passes is False

    def test_failing_screen_high_ltv(self):
        screen = screen_property(
            monthly_rent=3_000,
            purchase_price=200_000,
            loan_amount=190_000,
            annual_rate=0.075,
            term_years=30,
            annual_property_tax=3_600,
            annual_insurance=1_200,
            max_ltv=0.80,
        )
        assert screen.passes is False
