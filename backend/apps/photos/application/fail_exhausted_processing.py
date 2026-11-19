"""Record the failure of a processing attempt whose Celery retries ran out."""

from apps.photos.application.failures import (
    DISCARDED_FAILURE_CODE,
    DISCARDED_FAILURE_MESSAGE,
    PROCESSING_UNAVAILABLE_CODE,
    PROCESSING_UNAVAILABLE_MESSAGE,
)
from apps.photos.application.ports import PhotoSubmissionRepository
from apps.photos.domain.submission import PhotoSubmission, SubmissionStatus
from apps.shared.domain.exceptions import NotFoundError
from apps.shared.domain.store import StoreReference


class FailExhaustedProcessing:
    """Mark a still-processing submission failed without spending another attempt."""

    def __init__(self, *, repository: PhotoSubmissionRepository):
        self._repository = repository

    def __call__(self, store: StoreReference, submission_id: int) -> PhotoSubmission:
        submission = self._repository.get(store, submission_id)
        if submission is None:
            raise NotFoundError("No photo submission matches this id in this store.")

        if submission.discarded_at is not None:
            submission.mark_failed(DISCARDED_FAILURE_CODE, DISCARDED_FAILURE_MESSAGE)
            return self._repository.save(submission)

        if submission.status is not SubmissionStatus.PROCESSING:
            return submission

        submission.mark_failed(PROCESSING_UNAVAILABLE_CODE, PROCESSING_UNAVAILABLE_MESSAGE)
        return self._repository.save(submission)
