from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

from src.ingestion.reso_client import ResoClient

logger = logging.getLogger(__name__)

DEFAULT_LANDING = "/tmp/rentready/bronze_landing"


def _watermark_path(landing: str) -> str:
    return os.path.join(landing, "_watermark.txt")


def _read_watermark(landing: str) -> Optional[str]:
    path = _watermark_path(landing)
    if os.path.exists(path):
        with open(path) as f:
            return f.read().strip() or None
    return None


def _write_watermark(landing: str, watermark: str) -> None:
    os.makedirs(landing, exist_ok=True)
    with open(_watermark_path(landing), "w") as f:
        f.write(watermark)


def _write_batch(landing: str, records: list[dict], batch_label: str) -> str:
    os.makedirs(landing, exist_ok=True)
    path = os.path.join(landing, f"listings_{batch_label}.jsonl")
    with open(path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")
    return path


def incremental_pull(
    client: ResoClient,
    *,
    landing: str = DEFAULT_LANDING,
    select: Optional[list[str]] = None,
    top: int = 1000,
    dry_run: bool = False,
) -> int:
    """
    Perform an incremental pull of listings since the last watermark.

    Reads the stored watermark from *landing*, fetches newer records via
    *client*, writes them to JSONL files in the landing directory, and
    advances the watermark to the current timestamp.

    Returns the number of records written (0 if dry_run).
    """
    since = _read_watermark(landing)
    watermark = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    records = client.fetch_listings(select=select, top=top, since=since)
    if not records:
        logger.info("No new records since %s", since or "beginning of time")
        return 0

    if not dry_run:
        batch_label = watermark.replace(":", "").replace("-", "").replace("T", "_").rstrip("Z")
        path = _write_batch(landing, records, batch_label)
        _write_watermark(landing, watermark)
        logger.info("Wrote %d records to %s; watermark advanced to %s", len(records), path, watermark)
    else:
        logger.info("Dry-run: %d records would be written", len(records))

    return len(records)
