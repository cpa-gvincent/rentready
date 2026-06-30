"""
ML ranking for RentReady.

Reads from ``gold_deal_screen`` and overwrites ``rank_score`` using a
registered MLflow model if one is available.  Falls back to the
deterministic ordering that gold already produces (passing deals first,
then by after-close equity descending).  Never crashes on no-model.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

MLFLOW_MODEL_NAME = "rentready_ranking"


def rank(
    spark: Any,
    *,
    model_name: str = MLFLOW_MODEL_NAME,
    model_alias: str = "production",
    licensed_catalog: str = "rentready_dev_licensed",
    tenant: str = "demo",
) -> None:
    """
    Re-rank ``gold_deal_screen`` via an MLflow model, or fall back to
    deterministic ordering.

    Writes results to ``gold_ranked`` in the licensed catalog.
    """
    ns = f"{licensed_catalog}.{tenant}"
    source = f"{ns}_gold_deal_screen"
    target = f"{ns}_gold_ranked"

    df = spark.read.table(source)

    model = _try_load_model(spark, model_name, model_alias)
    if model is None:
        logger.info("No MLflow model found; using deterministic fallback")
        result = df
    else:
        logger.info("Applying MLflow model %s:%s", model_name, model_alias)
        result = model.transform(df)
        if "rank_score" not in result.columns:
            logger.warning("MLflow model did not produce rank_score; falling back to deterministic")
            result = df

    result.write.mode("overwrite").saveAsTable(target)


def _try_load_model(
    spark: Any,
    model_name: str,
    model_alias: str,
) -> Optional[Any]:
    """Attempt to load a registered MLflow model.  Returns ``None`` if the
    model does not exist or any error occurs."""
    try:
        import mlflow.pyfunc

        model_uri = f"models:/{model_name}@{model_alias}"
        return mlflow.pyfunc.load_model(model_uri)
    except Exception:
        logger.exception("Failed to load MLflow model")
        return None
