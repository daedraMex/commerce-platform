"""Per-ticket model selection."""

from __future__ import annotations

from .config import FactoryConfigError

STRONG_MODEL_LABEL = "strong-model"


def select_model(
    labels: frozenset[str],
    *,
    default_model: str | None,
    strong_model: str | None,
) -> str:
    """Pick the model for a ticket; ``strong-model`` tickets get the stronger one."""
    if not default_model:
        raise FactoryConfigError(
            "FACTORY_MODEL is not set; add it to the factory user's secrets file."
        )
    if STRONG_MODEL_LABEL in labels:
        if not strong_model:
            raise FactoryConfigError(
                "FACTORY_STRONG_MODEL is not set; a ticket is labeled strong-model."
            )
        return strong_model
    return default_model
