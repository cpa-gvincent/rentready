"""
Schema contract test: silver output columns must match what gold reads.

Gold reads:
  silver_listings:       apn, listing_key, address, postal_code, property_type,
                         list_price, annual_property_tax, monthly_hoa, has_hoa
  silver_value_estimates: apn, value_estimate, estimate_source
"""

from src.pipelines.silver import SILVER_LISTINGS_COLS, SILVER_VALUE_ESTIMATES_COLS


class TestSilverListingsSchema:
    def test_columns_match_gold_contract(self):
        expected = {
            "apn", "listing_key", "address", "postal_code",
            "property_type", "list_price", "annual_property_tax",
            "monthly_hoa", "has_hoa",
        }
        assert set(SILVER_LISTINGS_COLS) == expected

    def test_no_extra_or_missing_columns(self):
        assert len(SILVER_LISTINGS_COLS) == 9


class TestSilverValueEstimatesSchema:
    def test_columns_match_gold_contract(self):
        expected = {"apn", "value_estimate", "estimate_source"}
        assert set(SILVER_VALUE_ESTIMATES_COLS) == expected

    def test_no_extra_or_missing_columns(self):
        assert len(SILVER_VALUE_ESTIMATES_COLS) == 3
