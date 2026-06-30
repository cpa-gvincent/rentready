# RentReady on Databricks

Automated screening of rental-investment properties for DSCR-loan acquisition.
Sources flow through licensed and public lanes into a Databricks medallion
lakehouse, get scored on DSCR / equity / LTV, ranked, and served to a UI and to
Google Drive for evening review.

```
Sources ──▶ Lakeflow ingestion ──▶ Bronze ─▶ Silver ─▶ Gold ──▶ SQL ──▶ App / Drive
(MLS RESO,    (Connect + Auto         (raw)   (clean,   (DSCR,         (React UI,
 AVM, county,  Loader + RESO pull)            APN-      equity,         deal sheets)
 GitHub, Drive)                               resolved) scored)
                                                  ▲
                                            ML ranking (MLflow)
        Unity Catalog · Lakeflow Jobs · GitHub CI/CD span all layers
```

## Repo layout

```
databricks.yml              Asset Bundle root (dev/staging/prod targets)
resources/
  pipelines.yml             bronze->silver->gold SDP pipeline
  jobs.yml                  scheduled job: ingest -> pipeline -> ML rank
  app.yml                   Databricks App bound to a SQL warehouse
conf/catalogs.sql           Unity Catalog setup (licensed/public split)
src/
  lib/dscr.py               CORE MATH — DSCR, PITIA, equity, confidence (tested)
  lib/config.py             catalog/schema/tenant resolution + lane boundary
  ingestion/reso_client.py  RESO Web API (OData) client
  ingestion/reso_ingest.py  incremental RESO -> bronze pull
  pipelines/bronze.py       raw streaming tables (Auto Loader + landing)
  pipelines/silver.py       clean + expectations + APN entity resolution
  pipelines/gold.py         DSCR/equity scoring (mirrors lib/dscr.py at scale)
  ml/ranking.py             MLflow ranker (falls back to deterministic rank)
app/
  app.yaml, backend/main.py FastAPI: serves gold via SQL + hosts React build
  frontend/                 drop your existing RentReady Vite app here
tests/test_dscr.py          contract tests for the math
.github/workflows/deploy.yml  test -> bundle deploy
```

## The compliance boundary (read this first)

Licensed data (MLS via RESO, licensed AVM) and public data (gov/assessor/licensed
public APIs) live in **separate Unity Catalogs** — `*_licensed` and `*_public` —
tagged by lane. This keeps provenance auditable, which is the thing you sell to
agents bound by MLS/IDX rules. Do not scrape listing portals into the public
lane: that data is MLS-derived and would breach the agreement your buyers operate
under. The split is a feature, not a constraint.

## Setup

1. **Catalogs** — run `conf/catalogs.sql` per environment (substitute `${env}`
   and `${tenant}`), or template it in CI.
2. **Secrets** — store the RESO token in a scope:
   `databricks secrets put-secret rentready reso_token`. Reference
   `rentready.reso_base_url` and `rentready.reso_token` in the pipeline config.
3. **CLI** — `pip install databricks-cli`; authenticate to your workspace.
4. **Deploy** — `databricks bundle deploy -t dev`.
5. **Run** — `databricks bundle run rentready_ingest_and_screen -t dev`.

## Local dev

```bash
pip install -r requirements.txt
pytest tests/ -q          # validates the deal math
```

## Defaults baked in (the four pre-deployment decisions)

These are set so the repo runs today; revisit them per the architecture notes:

| Decision            | Default here                                   | Where to change            |
|---------------------|------------------------------------------------|----------------------------|
| Public-data boundary| Separate licensed/public catalogs, lane-tagged | `conf/catalogs.sql`, config |
| Entity-resolution key | Normalized parcel number (APN)               | `src/pipelines/silver.py`  |
| Freshness SLA       | Scheduled batch every 2 hours                  | `resources/jobs.yml` cron  |
| Tenancy             | Single tenant per schema, isolated per catalog | `var.tenant` in bundle     |

## Underwriting assumptions

Rate, term, target LTV, insurance, rent-to-price, closing %, and DSCR threshold
are pipeline config (`resources/pipelines.yml` → `rentready.assumption.*`), so
each agent/tenant can be underwritten differently without code changes.
