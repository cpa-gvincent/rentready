"""
Tests for the public portal search module.

Tests focus on the data model, bronze-row mapping, orchestrator
logic, and the search-URL fallback.  Live Playwright scrapers are
exercised by the GitHub Actions integration test.
"""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import patch

from src.ingestion.public_search import (
    SearchCriteria,
    Listing,
    search,
    search_urls,
    main,
)


class TestSearchCriteria:
    def test_defaults(self):
        c = SearchCriteria()
        assert c.city == "Richardson"
        assert c.state == "TX"
        assert c.beds == 3
        assert c.baths == 2


class TestSearchUrls:
    def test_returns_urls_for_all_sources(self):
        urls = search_urls(SearchCriteria())
        assert "redfin" in urls
        assert "zillow" in urls
        assert "movoto" in urls
        assert "richardson" in urls["redfin"].lower()
        assert "3-beds" in urls["zillow"].lower()


class TestListing:
    def test_to_bronze_row_has_expected_keys(self):
        l = Listing(
            source="redfin",
            listing_key="123",
            address="123 Main St",
            city="Richardson",
            state="TX",
            list_price=300_000.0,
            property_type="house",
        )
        row = l.to_bronze_row()
        assert row["ParcelNumber"] == "PUBLIC-redfin-123"
        assert row["ListingKey"] == "redfin_123"
        assert row["UnparsedAddress"] == "123 Main St"
        assert row["ListPrice"] == 300_000.0
        assert row["source"] == "redfin"

    def test_apn_used_when_present(self):
        l = Listing(
            source="zillow",
            listing_key="456",
            address="456 Oak Ave",
            city="Richardson",
            state="TX",
            apn="123456789",
        )
        row = l.to_bronze_row()
        assert row["ParcelNumber"] == "123456789"

    def test_value_estimate_falls_back_to_list_price(self):
        l = Listing(
            source="redfin",
            listing_key="789",
            address="789 Elm St",
            city="Richardson",
            state="TX",
            list_price=250_000.0,
            value_estimate=None,
        )
        row = l.to_bronze_row()
        assert row["value_estimate"] == 250_000.0


class TestSearchOrchestrator:
    def test_fallback_urls_when_scrapers_return_empty(self):
        """When scrapers are blocked, search-URL fallback records are created."""
        with patch("src.ingestion.public_search._redfin_search", return_value=[]):
            with patch("src.ingestion.public_search._zillow_search", return_value=[]):
                with patch("src.ingestion.public_search._movoto_search", return_value=[]):
                    with tempfile.TemporaryDirectory() as landing:
                        count = search(SearchCriteria(), landing=landing)
                        # One fallback URL record per source
                        assert count == 3
                        files = [f for f in os.listdir(landing) if f.endswith(".jsonl")]
                        assert len(files) == 1
                        with open(os.path.join(landing, files[0])) as f:
                            rows = [json.loads(line) for line in f]
                            assert len(rows) == 3
                            assert all(r.get("search_url") for r in rows)
                            # Verify all bronze schema fields present
                            for r in rows:
                                assert "ParcelNumber" in r
                                assert "ListingKey" in r
                                assert "UnparsedAddress" in r
                                assert "PostalCode" in r
                                assert "PropertyType" in r
                                assert "ListPrice" in r
                                assert "TaxAnnualAmount" in r
                                assert "MonthlyHOAAmt" in r
                                assert "BedroomsTotal" in r
                                assert "BathroomsTotal" in r

    def test_writes_jsonl_when_records_found(self):
        records = [
            {"ListingKey": "test_1", "ListPrice": 300000, "source": "test"},
            {"ListingKey": "test_2", "ListPrice": 350000, "source": "test"},
        ]
        with patch.dict("src.ingestion.public_search.SOURCES",
                        {"test": lambda c: records}, clear=True):
            with tempfile.TemporaryDirectory() as landing:
                count = search(SearchCriteria(), landing=landing)
                assert count == 2
                jsonl_files = [f for f in os.listdir(landing) if f.endswith(".jsonl")]
                assert len(jsonl_files) == 1
                with open(os.path.join(landing, jsonl_files[0])) as f:
                    lines = f.readlines()
                    assert len(lines) == 2

    def test_dry_run_writes_nothing(self):
        records = [{"ListingKey": "test_1", "ListPrice": 300000, "source": "test"}]
        with patch.dict("src.ingestion.public_search.SOURCES",
                        {"test": lambda c: records}, clear=True):
            with tempfile.TemporaryDirectory() as landing:
                count = search(SearchCriteria(), landing=landing, dry_run=True)
                assert count == 1
                assert len(os.listdir(landing)) == 0

    def test_skips_unknown_source(self, caplog):
        import logging
        caplog.set_level(logging.WARNING)
        with tempfile.TemporaryDirectory() as landing:
            count = search(SearchCriteria(), sources=["nonexistent"], landing=landing, dry_run=True)
            assert count == 0
            assert "Unknown source" in caplog.text


class TestCli:
    def test_main_returns_count(self):
        with patch("src.ingestion.public_search.search", return_value=5) as mock_search:
            count = main(["--city", "Dallas", "--state", "TX", "--dry-run"])
            assert count == 5
            mock_search.assert_called_once()
            args, kwargs = mock_search.call_args
            assert args[0].city == "Dallas"
            assert kwargs["dry_run"] is True

    def test_main_defaults(self):
        with patch("src.ingestion.public_search.search", return_value=0) as mock_search:
            main([])
            args, kwargs = mock_search.call_args
            assert args[0].city == "Richardson"
            assert args[0].beds == 3
