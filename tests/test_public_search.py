"""
Tests for the public portal search module.

Tests cover the data model, bronze-row mapping, CLI parsing, and
orchestrator logic (with mocked HTTP). Live-scraper functions are tested
with stubbed responses.
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
    main,
)


class TestSearchCriteria:
    def test_defaults(self):
        c = SearchCriteria()
        assert c.city == "Richardson"
        assert c.state == "TX"
        assert c.beds == 3
        assert c.baths == 2


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


REDFIN_HOMES_PAYLOAD = json.dumps({
    "payload": {
        "homes": [
            {
                "id": 12345,
                "streetLine": "123 Main St",
                "city": "Richardson",
                "state": "TX",
                "zip": "75080",
                "price": 350000,
                "beds": 3,
                "baths": 2,
                "sqFt": 1800,
                "lotSize": 7200,
                "url": "/tx/richardson/123-main-st",
                "parcelNumber": "123456789012",
            }
        ]
    }
})


class TestRedfinSearch:
    def test_parses_home(self):
        with patch("src.ingestion.public_search._fetch", return_value=REDFIN_HOMES_PAYLOAD):
            from src.ingestion.public_search import _redfin_search
            records = _redfin_search(SearchCriteria())
            assert len(records) == 1
            assert records[0]["ListingKey"] == "redfin_12345"
            assert records[0]["ListPrice"] == 350000
            assert records[0]["ParcelNumber"] == "123456789012"
            assert records[0]["BedroomsTotal"] == 3


ZILLOW_PAYLOAD = json.dumps({
    "cat1": {
        "searchResults": [
            {
                "zpid": 67890,
                "address": "456 Oak Ave",
                "city": "Richardson",
                "state": "TX",
                "zipcode": "75081",
                "price": "$375,000",
                "beds": 3,
                "baths": 2,
                "area": 1700,
                "detailUrl": "https://www.zillow.com/homedetails/456-Oak-Ave",
            }
        ]
    }
})


class TestZillowSearch:
    def test_parses_listing(self):
        with patch("src.ingestion.public_search._fetch", return_value=ZILLOW_PAYLOAD):
            from src.ingestion.public_search import _zillow_search
            records = _zillow_search(SearchCriteria())
            assert len(records) == 1
            assert records[0]["ListingKey"] == "zillow_67890"
            assert records[0]["ListPrice"] == 375000


class TestSearchOrchestrator:
    def test_skips_unknown_source(self, caplog):
        import logging
        caplog.set_level(logging.WARNING)
        with tempfile.TemporaryDirectory() as landing:
            count = search(SearchCriteria(), sources=["nonexistent"], landing=landing, dry_run=True)
            assert count == 0
            assert "Unknown source" in caplog.text

    def test_writes_jsonl_when_records_found(self):
        records = [
            {"ListingKey": "test_1", "ListPrice": 300000, "source": "test"},
            {"ListingKey": "test_2", "ListPrice": 350000, "source": "test"},
        ]
        with patch.dict("src.ingestion.public_search.SOURCES",
                        {"test": lambda c: records}):
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
                        {"test": lambda c: records}):
            with tempfile.TemporaryDirectory() as landing:
                count = search(SearchCriteria(), landing=landing, dry_run=True)
                assert count == 1
                assert len(os.listdir(landing)) == 0


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
