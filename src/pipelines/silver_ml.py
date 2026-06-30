"""
Silver ML — clean feature table for investment-candidate prediction.

Builds on ``bronze_listings`` and ``silver_value_estimates`` to produce a
single row per property with:

- Raw property features (beds, baths, sqft, price, tax, hoa, etc.)
- Computed investment metrics (DSCR, LTV, equity) using standard assumptions
- A ``heuristic_investment_grade`` target column for supervised learning

The ML pipeline should read this table for both training and inference.
"""

from __future__ import annotations

ML_FEATURE_COLS = [
    "beds", "baths", "sqft", "list_price", "price_per_sqft",
    "annual_property_tax", "tax_rate",
    "monthly_hoa", "has_hoa",
    "property_type", "postal_code",
]
ML_DERIVED_COLS = [
    "est_monthly_rent", "monthly_pi", "monthly_pitia",
    "dscr", "ltv", "instant_equity", "equity_after_close",
]
ML_METADATA_COLS = [
    "apn", "listing_key", "address", "source", "search_url",
    "value_estimate", "value_confidence",
]
ML_TARGET_COL = "heuristic_investment_grade"
ML_ALL_COLS = ML_FEATURE_COLS + ML_DERIVED_COLS + [ML_TARGET_COL] + ML_METADATA_COLS

try:
    from pyspark import pipelines as dp
    from pyspark.sql import functions as F

    spark = spark  # noqa: F821
    from src.lib import config as _config
    from src.lib.dscr import monthly_mortgage_payment

    ns = _config.from_spark(spark)

    ANNUAL_RATE = float(spark.conf.get("rentready.assumption.annual_rate", "0.075"))
    TERM_YEARS = int(spark.conf.get("rentready.assumption.term_years", "30"))
    LTV_TARGET = float(spark.conf.get("rentready.assumption.ltv_target", "0.75"))
    ANNUAL_INSURANCE = float(spark.conf.get("rentready.assumption.annual_insurance", "1800"))
    RENT_TO_PRICE = float(spark.conf.get("rentready.assumption.rent_to_price_monthly", "0.008"))
    CLOSING_PCT = float(spark.conf.get("rentready.assumption.closing_pct", "0.03"))
    DSCR_THRESHOLD = float(spark.conf.get("rentready.assumption.dscr_threshold", "1.20"))
    MAX_LTV = float(spark.conf.get("rentready.assumption.max_ltv_for_target", "0.80"))

    @dp.table(
        name="silver_ml_features",
        comment=(
            "ML-ready feature table: raw property features + derived "
            "investment metrics + heuristic investment-grade target. "
            "One row per listing_key."
        ),
    )
    def silver_ml_features():
        bronze = spark.read.table(ns.licensed("bronze_listings"))

        apn = F.when(
            F.col("ParcelNumber").isNotNull(),
            F.upper(F.regexp_replace(F.trim(F.col("ParcelNumber")), "[- ]", "")),
        )

        purchase_price = F.col("ListPrice")
        sqft = F.col("LivingArea")
        monthly_tax = F.col("TaxAnnualAmount") / F.lit(12.0)
        monthly_ins = F.lit(ANNUAL_INSURANCE / 12.0)
        hoa = F.coalesce(F.col("MonthlyHOAAmt"), F.lit(0.0))

        loan = purchase_price * F.lit(LTV_TARGET)
        n = TERM_YEARS * 12
        r = ANNUAL_RATE / 12.0
        factor = F.pow(F.lit(1 + r), F.lit(n))
        monthly_pi = F.when(
            loan <= 0, F.lit(0.0)
        ).otherwise(
            loan * F.lit(r) * factor / (factor - F.lit(1.0))
        )
        monthly_pitia = monthly_pi + monthly_tax + monthly_ins + hoa
        est_rent = purchase_price * F.lit(RENT_TO_PRICE)
        dscr_val = F.when(monthly_pitia > 0, est_rent / monthly_pitia)
        closing = purchase_price * F.lit(CLOSING_PCT)
        value = F.coalesce(F.col("value_estimate"), purchase_price)
        ltv_val = F.when(value > 0, loan / value)
        instant_eq = value - purchase_price
        equity_close = value - (purchase_price + closing)

        price_per_sqft = F.when(
            (sqft.isNotNull()) & (sqft > 0), purchase_price / sqft
        )
        tax_rate = F.when(
            (purchase_price.isNotNull()) & (purchase_price > 0),
            F.col("TaxAnnualAmount") / purchase_price,
        )

        raw = bronze.select(
            apn.alias("apn"),
            F.col("ListingKey").alias("listing_key"),
            F.col("UnparsedAddress").alias("address"),
            F.col("PostalCode").alias("postal_code"),
            F.col("PropertyType").alias("property_type"),
            F.coalesce(F.col("City"), F.lit("")).alias("city"),
            F.coalesce(F.col("State"), F.lit("")).alias("state"),
            purchase_price.alias("list_price"),
            F.col("BedroomsTotal").alias("beds"),
            F.col("BathroomsTotal").alias("baths"),
            sqft.alias("sqft"),
            F.col("TaxAnnualAmount").alias("annual_property_tax"),
            hoa.alias("monthly_hoa"),
            (hoa > 0).alias("has_hoa"),
            F.col("source").alias("source"),
            F.col("search_url").alias("search_url"),
            F.col("value_estimate").alias("value_estimate"),
            F.col("estimate_source").alias("estimate_source"),
        )

        enriched = raw.select(
            "*",
            price_per_sqft.alias("price_per_sqft"),
            tax_rate.alias("tax_rate"),
            F.round(est_rent, 2).alias("est_monthly_rent"),
            F.round(monthly_pi, 2).alias("monthly_pi"),
            F.round(monthly_pitia, 2).alias("monthly_pitia"),
            F.round(dscr_val, 3).alias("dscr"),
            F.round(ltv_val, 4).alias("ltv"),
            F.round(instant_eq, 2).alias("instant_equity"),
            F.round(equity_close, 2).alias("equity_after_close"),
        )

        result = enriched.withColumn(
            ML_TARGET_COL,
            F.when(
                (F.col("dscr") >= F.lit(DSCR_THRESHOLD))
                & (F.col("ltv") <= F.lit(MAX_LTV))
                & (F.col("instant_equity") > 0),
                True,
            ).otherwise(False),
        )

        return result.select(*ML_ALL_COLS).dropDuplicates(["listing_key"])

except NameError:
    pass
