from __future__ import annotations

import os
import tempfile

from unittest.mock import MagicMock

from src.ingestion.reso_ingest import incremental_pull, _read_watermark


class TestIncrementalPull:
    def test_pulls_new_records_and_advances_watermark(self):
        client = MagicMock()
        client.fetch_listings.return_value = [
            {"ListingKey": "1", "ListPrice": 200_000},
            {"ListingKey": "2", "ListPrice": 300_000},
        ]

        with tempfile.TemporaryDirectory() as landing:
            count = incremental_pull(client, landing=landing, select=["ListingKey", "ListPrice"])
            assert count == 2

            files = os.listdir(landing)
            jsonl_files = [f for f in files if f.endswith(".jsonl")]
            assert len(jsonl_files) == 1

            watermark = _read_watermark(landing)
            assert watermark is not None
            assert watermark.endswith("Z")

    def test_no_new_records_returns_zero(self):
        client = MagicMock()
        client.fetch_listings.return_value = []

        with tempfile.TemporaryDirectory() as landing:
            count = incremental_pull(client, landing=landing)
            assert count == 0

    def test_dry_run_does_not_write_files(self):
        client = MagicMock()
        client.fetch_listings.return_value = [
            {"ListingKey": "1"},
        ]

        with tempfile.TemporaryDirectory() as landing:
            count = incremental_pull(client, landing=landing, dry_run=True)
            assert count == 1
            assert len(os.listdir(landing)) == 0  # nothing written
