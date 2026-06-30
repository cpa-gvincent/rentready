"""
Test the ranking module — deterministic fallback and MLflow model loading.

The tests use a fake Spark session to verify the module handles both
paths without crashing.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def fake_spark():
    spark = MagicMock()
    gold = MagicMock()
    gold.columns = [
        "apn", "listing_key", "passes", "equity_after_close", "rank_score",
    ]
    gold.collect.return_value = [
        MagicMock(apn="1", listing_key="L1", passes=True, equity_after_close=50000, rank_score=1),
        MagicMock(apn="2", listing_key="L2", passes=False, equity_after_close=20000, rank_score=2),
        MagicMock(apn="3", listing_key="L3", passes=True, equity_after_close=30000, rank_score=3),
    ]
    spark.read.table.return_value = gold
    return spark


class TestRanking:
    def test_fallback_when_no_model(self, fake_spark):
        from src.ml.ranking import rank

        with patch("src.ml.ranking._try_load_model", return_value=None):
            rank(fake_spark, licensed_catalog="test_catalog", tenant="test_tenant")

            fake_spark.read.table.assert_called_once()
            # Should have written target table
            fake_spark.read.table.return_value.write.mode.assert_called_once_with("overwrite")
            fake_spark.read.table.return_value.write.mode.return_value.saveAsTable.assert_called_once()

    def test_uses_model_when_available(self, fake_spark):
        from src.ml.ranking import rank

        model = MagicMock()
        transformed = MagicMock()
        transformed.columns = ["apn", "rank_score"]
        model.transform.return_value = transformed

        with patch("src.ml.ranking._try_load_model", return_value=model):
            rank(fake_spark, licensed_catalog="test_catalog", tenant="test_tenant")

            model.transform.assert_called_once_with(fake_spark.read.table.return_value)
            transformed.write.mode.return_value.saveAsTable.assert_called_once()

    def test_fallback_when_model_missing_rank_score(self, fake_spark):
        from src.ml.ranking import rank

        model = MagicMock()
        transformed = MagicMock()
        transformed.columns = ["apn"]  # no rank_score
        model.transform.return_value = transformed

        with patch("src.ml.ranking._try_load_model", return_value=model):
            rank(fake_spark, licensed_catalog="test_catalog", tenant="test_tenant")

            # Should fall back to original df
            fake_spark.read.table.return_value.write.mode.return_value.saveAsTable.assert_called_once()

    def test_try_load_model_returns_none_on_error(self):
        from src.ml.ranking import _try_load_model

        with patch("mlflow.pyfunc.load_model", side_effect=Exception("no model")):
            result = _try_load_model(MagicMock(), "test_model", "production")
            assert result is None
