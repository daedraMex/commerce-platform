"""Record a submission whose processing message could not be sent."""

import logging

from apps.photos.application.fail_exhausted_processing import FailExhaustedProcessing
from apps.photos.application.ports import PhotoSubmissionRepository
from apps.photos.domain.submission import PhotoSubmission
from apps.shared.domain.store import StoreReference

logger = logging.getLogger(__name__)


def record_processing_unavailable(
    repository: PhotoSubmissionRepository,
    store: StoreReference,
    submission_id: int,
) -> PhotoSubmission | None:
    """Mark the submission failed, logging instead of raising if that is impossible."""
    try:
        return FailExhaustedProcessing(repository=repository)(store, submission_id)
    except Exception:
        logger.exception(
            "Could not record unavailable photo processing for store %s submission %s",
            store.id,
            submission_id,
            extra={"store_id": store.id, "submission_id": submission_id},
        )
        return None
