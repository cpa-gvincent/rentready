"""
FastAPI backend for RentReady.

Serves ranked deal screens from the gold layer via Databricks SQL,
and hosts the React frontend build under ``app/frontend/``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from databricks import sql as dbsql

app = FastAPI(title="RentReady")

SERVER_HOSTNAME = os.environ.get("DATABRICKS_SERVER_HOSTNAME", "")
HTTP_PATH = os.environ.get("DATABRICKS_HTTP_PATH", "")
ACCESS_TOKEN = os.environ.get("DATABRICKS_ACCESS_TOKEN", "")
CATALOG = os.environ.get("RENTREADY_CATALOG", "rentready_dev_licensed")
SCHEMA = os.environ.get("RENTREADY_SCHEMA", "demo")
TABLE = os.environ.get("RENTREADY_TABLE", "gold_deal_screen")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def _get_connection():
    return dbsql.connect(
        server_hostname=SERVER_HOSTNAME,
        http_path=HTTP_PATH,
        access_token=ACCESS_TOKEN,
    )


@app.get("/api/rankings")
def get_rankings(
    limit: int = 50,
    min_dscr: float | None = None,
    passes_only: bool = False,
) -> list[dict[str, Any]]:
    """Return ranked deals from the gold layer."""
    filters: list[str] = []
    if passes_only:
        filters.append("passes = TRUE")
    if min_dscr is not None:
        filters.append(f"dscr >= {min_dscr}")

    where = " AND ".join(filters)
    if where:
        where = f"WHERE {where}"

    query = f"""
        SELECT *
        FROM {CATALOG}.{SCHEMA}.{TABLE}
        {where}
        ORDER BY rank_score ASC
        LIMIT {limit}
    """

    try:
        with _get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                rows = cur.fetchall()
                return [dict(row) for row in rows]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/rankings/{apn}")
def get_ranking_by_apn(apn: str) -> dict[str, Any]:
    """Return a single ranked deal by APN."""
    query = f"""
        SELECT *
        FROM {CATALOG}.{SCHEMA}.{TABLE}
        WHERE apn = '{apn}'
    """
    try:
        with _get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                row = cur.fetchone()
                if row is None:
                    raise HTTPException(status_code=404, detail="APN not found")
                return dict(row)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
