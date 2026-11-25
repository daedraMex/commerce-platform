"""Redo a ready or failed photo with new corners or crop, keeping the previous Media."""

import logging

from apps.photos.application.ports import (
    PhotoProcessingQueue,
    PhotoSubmissionRepository,
    UnitOfWork,
)
from apps.photos.application.record_processing_unavailable import (
    record_processing_unavailable,
)
from apps.photos.domain.submission import PhotoSubmission
from apps.shared.domain.exceptions import NotFoundError
from apps.shared.domain.permissions import MANAGE_CATALOG
from apps.shared.domain.ports import Authorizer
from apps.shared.domain.store import StoreReference

logger = logging.getLogger(__name__)


class RedoPhoto:
    """Authorize, move a ready or failed submission back to processing and re-enqueue it."""

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
        with self._unit_of_work():
            saved = self._repository.save(submission)
            try:
                self._queue.enqueue(store, saved.id)
            except Exception:
                logger.exception(
                    "Could not enqueue photo processing for store %s submission %s",
                    store.id,
                    saved.id,
                    extra={"store_id": store.id, "submission_id": saved.id},
                )
                failed = record_processing_unavailable(self._repository, store, saved.id)
                if failed is not None:
                    saved = failed
        return saved
