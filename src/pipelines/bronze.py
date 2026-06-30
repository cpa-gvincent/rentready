try:
    from pyspark import pipelines as dp

    spark = spark  # noqa: F821
    from src.lib import config as _config
    from src.ingestion.reso_ingest import DEFAULT_LANDING

    ns = _config.from_spark(spark)
    LANDING_PATH = spark.conf.get("rentready.landing_path", DEFAULT_LANDING)

    @dp.streaming_table
    def bronze_listings():
        return (
            spark.readStream.format("cloudFiles")
            .option("cloudFiles.format", "jsonl")
            .option("cloudFiles.inferColumnTypes", "true")
            .option("cloudFiles.schemaEvolution", "none")
            .load(LANDING_PATH)
        )
except NameError:
    pass
