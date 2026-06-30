"""
Gold layer — the screened, ranked shortlist served to the UI.

This mirrors src/lib/dscr.py as native Spark expressions for scale. The math
must match the unit-tested reference there; tests/test_dscr.py is the contract.

Output: one row per property with DSCR, PITIA, instant/after-close equity, LTV,
a blended value estimate, and a confidence flag from source agreement.
"""

from pyspark import pipelines as dp
from pyspark.sql import functions as F
from pyspark.sql import Window

from src.lib import config

spark = spark  # noqa: F821
ns = config.from_spark(spark)

# Loan + assumption parameters (set per tenant via pipeline config).
ANNUAL_RATE = float(spark.conf.get("rentready.assumption.annual_rate", "0.075"))
TERM_YEARS = int(spark.conf.get("rentready.assumption.term_years", "30"))
LTV_TARGET = float(spark.conf.get("rentready.assumption.ltv_target", "0.75"))
ANNUAL_INSURANCE = float(spark.conf.get("rentready.assumption.annual_insurance", "1800"))
RENT_TO_PRICE = float(spark.conf.get("rentready.assumption.rent_to_price_monthly", "0.008"))
CLOSING_PCT = float(spark.conf.get("rentready.assumption.closing_pct", "0.03"))
DSCR_THRESHOLD = float(spark.conf.get("rentready.assumption.dscr_threshold", "1.20"))


def _monthly_pi(loan, rate, term_years):
    """Amortizing P&I as a Spark expression (mirrors dscr.monthly_mortgage_payment)."""
    n = term_years * 12
    r = rate / 12.0
    factor = F.pow(F.lit(1 + r), F.lit(n))
    return F.when(loan <= 0, F.lit(0.0)).otherwise(
        loan * F.lit(r) * factor / (factor - F.lit(1.0))
    )


@dp.materialized_view(
    name="gold_value_triangulation",
    comment="Blended value estimate + confidence per property.",
)
def gold_value_triangulation():
    est = spark.read.table(ns.licensed("silver_value_estimates"))
    agg = est.groupBy("apn").agg(
        F.expr("percentile_approx(value_estimate, 0.5)").alias("value_estimate"),
        F.min("value_estimate").alias("_min"),
        F.max("value_estimate").alias("_max"),
        F.countDistinct("estimate_source").alias("n_sources"),
    )
    spread = (F.col("_max") - F.col("_min")) / F.col("value_estimate")
    return agg.withColumn("spread_pct", F.round(spread, 4)).withColumn(
        "value_confidence",
        F.when(F.col("n_sources") < 2, "low")
        .when(spread <= 0.05, "high")
        .when(spread <= 0.12, "medium")
        .otherwise("low"),
    ).drop("_min", "_max")


@dp.materialized_view(
    name="gold_deal_screen",
    comment="Per-property DSCR/equity screen + pass flag + rank. Served to the UI.",
)
def gold_deal_screen():
    listings = spark.read.table(ns.licensed("silver_listings"))
    values = spark.read.table(ns.licensed("gold_value_triangulation"))

    df = listings.join(values, "apn", "left")

    # Value: blended estimate if we have one, else fall back to list price.
    value = F.coalesce(F.col("value_estimate"), F.col("list_price"))
    purchase_price = F.col("list_price")
    loan = value * F.lit(LTV_TARGET)
    monthly_rent = purchase_price * F.lit(RENT_TO_PRICE)

    monthly_pi = _monthly_pi(loan, ANNUAL_RATE, TERM_YEARS)
    monthly_pitia = (
        monthly_pi
        + F.col("annual_property_tax") / F.lit(12.0)
        + F.lit(ANNUAL_INSURANCE / 12.0)
        + F.col("monthly_hoa")
    )
    dscr = F.when(monthly_pitia > 0, monthly_rent / monthly_pitia)
    closing = purchase_price * F.lit(CLOSING_PCT)

    scored = (
        df
        .withColumn("value", F.round(value, 2))
        .withColumn("est_monthly_rent", F.round(monthly_rent, 2))
        .withColumn("monthly_pitia", F.round(monthly_pitia, 2))
        .withColumn("dscr", F.round(dscr, 3))
        .withColumn("ltv", F.round(loan / value, 4))
        .withColumn("instant_equity", F.round(value - purchase_price, 2))
        .withColumn("equity_after_close", F.round(value - (purchase_price + closing), 2))
        .withColumn(
            "passes",
            (F.col("dscr") >= F.lit(DSCR_THRESHOLD)) & (F.col("ltv") <= F.lit(LTV_TARGET) + 0.001),
        )
    )

    # Default ranking: passing deals first, then by after-close equity. The ML
    # model (src/ml/ranking.py) can overwrite `rank_score` downstream.
    w = Window.orderBy(F.col("passes").desc(), F.col("equity_after_close").desc())
    return scored.withColumn("rank_score", F.row_number().over(w)).select(
        "apn", "listing_key", "address", "postal_code", "property_type",
        "value", "value_confidence", "est_monthly_rent", "monthly_pitia",
        "dscr", "ltv", "instant_equity", "equity_after_close",
        "has_hoa", "monthly_hoa", "passes", "rank_score",
    )
