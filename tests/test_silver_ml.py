"""
Schema contract + logic tests for silver_ml features.
"""

from src.pipelines.silver_ml import (
    ML_FEATURE_COLS,
    ML_DERIVED_COLS,
    ML_METADATA_COLS,
    ML_TARGET_COL,
    ML_ALL_COLS,
)


class TestSilverMlSchema:
    def test_feature_cols_are_comprehensive(self):
        raw = {"beds", "baths", "sqft", "list_price", "price_per_sqft",
               "annual_property_tax", "tax_rate", "monthly_hoa", "has_hoa",
               "property_type", "postal_code"}
        assert set(ML_FEATURE_COLS) == raw

    def test_derived_cols_include_dscr_metrics(self):
        expected = {"est_monthly_rent", "monthly_pi", "monthly_pitia",
                    "dscr", "ltv", "instant_equity", "equity_after_close"}
        assert set(ML_DERIVED_COLS) == expected

    def test_metadata_cols_track_provenance(self):
        expected = {"apn", "listing_key", "address", "source", "search_url",
                    "value_estimate", "value_confidence"}
        assert set(ML_METADATA_COLS) == expected

    def test_target_col_is_investment_grade(self):
        assert ML_TARGET_COL == "heuristic_investment_grade"

    def test_all_cols_are_unique(self):
        assert len(ML_ALL_COLS) == len(set(ML_ALL_COLS))

    def test_all_cols_contain_all_groups(self):
        combined = set(ML_FEATURE_COLS + ML_DERIVED_COLS + [ML_TARGET_COL] + ML_METADATA_COLS)
        assert set(ML_ALL_COLS) == combined


class TestInvestmentGradeHeuristic:
    """Test the heuristic logic in pure Python (mirrors the Spark expr)."""

    @staticmethod
    def _heuristic(
        dscr: float | None,
        ltv: float | None,
        instant_equity: float | None,
        *,
        dscr_threshold: float = 1.20,
        max_ltv: float = 0.80,
    ) -> bool:
        if dscr is None or ltv is None or instant_equity is None:
            return False
        return dscr >= dscr_threshold and ltv <= max_ltv and instant_equity > 0

    def test_passing_property(self):
        assert self._heuristic(dscr=1.35, ltv=0.70, instant_equity=25_000)

    def test_fails_low_dscr(self):
        assert not self._heuristic(dscr=1.0, ltv=0.70, instant_equity=25_000)

    def test_fails_high_ltv(self):
        assert not self._heuristic(dscr=1.35, ltv=0.85, instant_equity=25_000)

    def test_fails_negative_equity(self):
        assert not self._heuristic(dscr=1.35, ltv=0.70, instant_equity=-5_000)

    def test_fails_zero_equity(self):
        assert not self._heuristic(dscr=1.35, ltv=0.70, instant_equity=0)

    def test_none_dscr_is_not_grade(self):
        assert not self._heuristic(dscr=None, ltv=0.70, instant_equity=25_000)

    def test_none_ltv_is_not_grade(self):
        assert not self._heuristic(dscr=1.35, ltv=None, instant_equity=25_000)

    def test_none_equity_is_not_grade(self):
        assert not self._heuristic(dscr=1.35, ltv=0.70, instant_equity=None)
