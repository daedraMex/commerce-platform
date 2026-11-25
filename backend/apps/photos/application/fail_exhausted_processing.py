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


def mark_processing_unavailable(submission: PhotoSubmission) -> bool:
    """Apply the exhausted-processing failure to one loaded submission.

    Returns whether the submission changed. A discarded one records the discarded
    failure; an uploaded one records the attempt the worker never saved; a processing
    one keeps its attempts; any other state is left unchanged.
    """
    if submission.discarded_at is not None:
        submission.mark_failed(DISCARDED_FAILURE_CODE, DISCARDED_FAILURE_MESSAGE)
        return True

    if submission.status is SubmissionStatus.UPLOADED:
        submission.start_processing()
    elif submission.status is not SubmissionStatus.PROCESSING:
        return False

    submission.mark_failed(PROCESSING_UNAVAILABLE_CODE, PROCESSING_UNAVAILABLE_MESSAGE)
    return True


class FailExhaustedProcessing:
    """Mark a submission whose retries ran out as failed.

    A still-processing submission keeps its attempt count; an uploaded one never got
    its start saved, so this records the attempt the worker did make.
    """

    def __init__(self, *, repository: PhotoSubmissionRepository):
        self._repository = repository

    def __call__(self, store: StoreReference, submission_id: int) -> PhotoSubmission:
        submission = self._repository.get(store, submission_id)
        if submission is None:
            raise NotFoundError("No photo submission matches this id in this store.")

        if not mark_processing_unavailable(submission):
            return submission
        return self._repository.save(submission)
