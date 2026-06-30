from dataclasses import dataclass

DEFAULT_TENANT = "demo"
DEFAULT_LICENSED = "rentready_dev_licensed"
DEFAULT_PUBLIC = "rentready_dev_public"


@dataclass
class Namespace:
    tenant: str
    licensed_catalog: str
    public_catalog: str

    def licensed(self, table: str) -> str:
        return f"{self.licensed_catalog}.{self.tenant}_{table}"

    def public(self, table: str) -> str:
        return f"{self.public_catalog}.{self.tenant}_{table}"


def from_spark(spark) -> Namespace:
    return Namespace(
        tenant=spark.conf.get("rentready.tenant", DEFAULT_TENANT),
        licensed_catalog=spark.conf.get("rentready.licensed_catalog", DEFAULT_LICENSED),
        public_catalog=spark.conf.get("rentready.public_catalog", DEFAULT_PUBLIC),
    )
