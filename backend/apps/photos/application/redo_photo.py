"""Redo a ready photo with new corners or crop, keeping the previous Media."""

from apps.photos.application.ports import PhotoProcessingQueue, PhotoSubmissionRepository
from apps.photos.domain.submission import PhotoSubmission
from apps.shared.domain.exceptions import NotFoundError
from apps.shared.domain.permissions import MANAGE_CATALOG
from apps.shared.domain.ports import Authorizer
from apps.shared.domain.store import StoreReference


class RedoPhoto:
    """Authorize, move a ready submission back to processing and re-enqueue it."""

    def __init__(
        self,
        *,
        repository: PhotoSubmissionRepository,
        queue: PhotoProcessingQueue,
        authorizer: Authorizer,
    ):
        self._repository = repository
        self._queue = queue
        self._authorizer = authorizer

    def __call__(
        self,
        store: StoreReference,
        *,
        user_id: int,
        submission_id: int,
        corners=None,
        crop=None,
    ) -> PhotoSubmission:
        self._authorizer.require(user_id, store, MANAGE_CATALOG)

        submission = self._repository.get(store, submission_id)
        if submission is None:
            raise NotFoundError("No photo submission matches this id in this store.")

        submission.redo(
            corners=submission.corners if corners is None else corners,
            crop=submission.crop if crop is None else crop,
        )
        saved = self._repository.save(submission)
        self._queue.enqueue(store, saved.id)
        return saved
