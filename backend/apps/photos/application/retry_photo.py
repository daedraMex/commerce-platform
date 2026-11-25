"""Retry a failed photo submission with another processing attempt."""

from apps.photos.application.ports import (
    PhotoProcessingQueue,
    PhotoSubmissionRepository,
    UnitOfWork,
)
from apps.photos.domain.errors import CannotStartProcessing
from apps.photos.domain.submission import PhotoSubmission, SubmissionStatus
from apps.shared.domain.exceptions import NotFoundError
from apps.shared.domain.permissions import MANAGE_CATALOG
from apps.shared.domain.ports import Authorizer
from apps.shared.domain.store import StoreReference


class RetryPhoto:
    """Authorize, start a new attempt and re-enqueue the failed submission."""

    def __init__(
        self,
        *,
        repository: PhotoSubmissionRepository,
        queue: PhotoProcessingQueue,
        authorizer: Authorizer,
        unit_of_work: UnitOfWork,
    ):
        self._repository = repository
        self._queue = queue
        self._authorizer = authorizer
        self._unit_of_work = unit_of_work

    def __call__(
        self, store: StoreReference, *, user_id: int, submission_id: int
    ) -> PhotoSubmission:
        self._authorizer.require(user_id, store, MANAGE_CATALOG)

        submission = self._repository.get(store, submission_id)
        if submission is None:
            raise NotFoundError("No photo submission matches this id in this store.")
        if submission.status is not SubmissionStatus.FAILED:
            raise CannotStartProcessing("Only a failed photo can be retried.")

        submission.start_processing()
        with self._unit_of_work():
            saved = self._repository.save(submission)
            self._queue.enqueue(store, saved.id)
        return saved
