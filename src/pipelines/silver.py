"""
Silver layer — clean, APN-resolved listings and value estimates.

Output tables match the contracts ``gold.py`` reads:

- ``silver_listings``
  (apn, listing_key, address, postal_code, property_type, list_price,
   annual_property_tax, monthly_hoa, has_hoa)

- ``silver_value_estimates``
  (apn, value_estimate, estimate_source)
"""

try:
    from pyspark import pipelines as dp
    from pyspark.sql import functions as F

    spark = spark  # noqa: F821 — Databricks notebook context
    from src.lib import config as _config
    ns = _config.from_spark(spark)
except NameError:
    dp = None
    F = None
    ns = None

SILVER_LISTINGS_COLS = [
    "apn", "listing_key", "address", "postal_code",
    "property_type", "list_price", "annual_property_tax",
    "monthly_hoa", "has_hoa",
]

SILVER_VALUE_ESTIMATES_COLS = [
    "apn", "value_estimate", "estimate_source",
]


def _normalize_apn(raw: str) -> str:
    if raw is None:
        return None
    return raw.strip().upper().replace("-", "").replace(" ", "")


if dp is not None:

    _normalize_apn_udf = F.udf(_normalize_apn)

    @dp.materialized_view(
        name="silver_listings",
        comment="Clean listings with normalised APN; one row per listing.",
    )
    def silver_listings():
        bronze = spark.read.table(ns.licensed("bronze_listings"))

        return (
            bronze
            .withColumn("apn", _normalize_apn_udf(F.col("ParcelNumber")))
            .withColumn("has_hoa", F.when(F.col("MonthlyHOAAmt").isNotNull() & (F.col("MonthlyHOAAmt") > 0), True).otherwise(False))
            .select(
                F.col("apn"),
                F.col("ListingKey").alias("listing_key"),
                F.col("UnparsedAddress").alias("address"),
                F.col("PostalCode").alias("postal_code"),
                F.col("PropertyType").alias("property_type"),
                F.col("ListPrice").alias("list_price"),
                F.col("TaxAnnualAmount").alias("annual_property_tax"),
                F.col("MonthlyHOAAmt").alias("monthly_hoa"),
                F.col("has_hoa"),
            )
            .dropDuplicates(["listing_key"])
        )

    @dp.materialized_view(
        name="silver_value_estimates",
        comment="Normalised value estimates per APN from MLS, AVM, and county.",
    )
    def silver_value_estimates():
        bronze = spark.read.table(ns.licensed("bronze_listings"))

        return (
            bronze
            .withColumn("apn", _normalize_apn_udf(F.col("ParcelNumber")))
            .select(
                F.col("apn"),
                F.col("ListPrice").alias("value_estimate"),
                F.lit("mls_list").alias("estimate_source"),
            )
            .filter(F.col("apn").isNotNull() & F.col("value_estimate").isNotNull())
            .dropDuplicates(["apn", "estimate_source"])
        )
