from src.lib.config import Namespace


class FakeSparkConf:
    def __init__(self, mapping=None):
        self._d = mapping or {}

    def get(self, key, default=None):
        return self._d.get(key, default)


class FakeSpark:
    def __init__(self, mapping=None):
        self.conf = FakeSparkConf(mapping)


def test_from_spark_uses_defaults():
    from src.lib.config import from_spark
    spark = FakeSpark()
    ns = from_spark(spark)
    assert ns.tenant == "demo"
    assert ns.licensed_catalog == "rentready_dev_licensed"
    assert ns.public_catalog == "rentready_dev_public"


def test_from_spark_reads_conf():
    from src.lib.config import from_spark
    spark = FakeSpark({
        "rentready.tenant": "agent42",
        "rentready.licensed_catalog": "rentready_prod_licensed",
        "rentready.public_catalog": "rentready_prod_public",
    })
    ns = from_spark(spark)
    assert ns.tenant == "agent42"


def test_licensed_returns_qualified_name():
    from src.lib.config import from_spark
    spark = FakeSpark({
        "rentready.tenant": "demo",
        "rentready.licensed_catalog": "rentready_dev_licensed",
    })
    ns = from_spark(spark)
    assert ns.licensed("silver_listings") == "rentready_dev_licensed.demo_silver_listings"
    assert ns.licensed("silver_value_estimates") == "rentready_dev_licensed.demo_silver_value_estimates"


def test_public_returns_qualified_name():
    from src.lib.config import from_spark
    spark = FakeSpark({
        "rentready.tenant": "demo",
        "rentready.public_catalog": "rentready_dev_public",
    })
    ns = from_spark(spark)
    assert ns.public("tax_records") == "rentready_dev_public.demo_tax_records"


def test_namespace_never_crosses_lanes():
    ns = Namespace(
        tenant="acme",
        licensed_catalog="rentready_staging_licensed",
        public_catalog="rentready_staging_public",
    )
    lic = ns.licensed("listings")
    pub = ns.public("listings")
    assert "licensed" in lic and "public" not in lic
    assert "public" in pub and "licensed" not in pub
    assert lic != pub
