"""Celery interface for the photo processing use case."""

import logging

from celery import shared_task

from apps.photos.application.process_photo_submission import TransientProcessingError
from apps.photos.domain.errors import PhotoSubmissionError
from apps.photos.domain.submission import MAX_ATTEMPTS
from apps.shared.domain.exceptions import NotFoundError
from apps.shared.domain.store import StoreReference
from config.dependencies import get_process_photo_submission

logger = logging.getLogger(__name__)

RETRY_BACKOFF_SECONDS = 30


def retry_countdown(retries: int) -> int:
    """The exponential backoff before the next processing attempt."""
    return RETRY_BACKOFF_SECONDS * (2**retries)


@shared_task(bind=True, max_retries=MAX_ATTEMPTS - 1)
def process_photo_submission(self, store_id: int, submission_id: int) -> None:
    """Process one submission and record the result on it; retry only transient failures."""
    store = StoreReference(id=store_id, slug="")
    try:
        get_process_photo_submission()(store, submission_id=submission_id)
    except (PhotoSubmissionError, NotFoundError):
        # The use case recorded a readable failure code on the submission.
        logger.info("Photo submission %s finished without a result", submission_id)
    except TransientProcessingError as error:
        if self.request.retries >= self.max_retries:
            return
        raise self.retry(exc=error, countdown=retry_countdown(self.request.retries)) from error
