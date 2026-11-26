"""Fail processing submissions whose processing message never arrived (ADR-0028)."""

import logging
from datetime import datetime, timedelta

from apps.photos.application.fail_exhausted_processing import mark_processing_unavailable
from apps.photos.application.ports import PhotoSubmissionRepository
from apps.photos.domain.errors import ConcurrentModification
from apps.photos.domain.submission import PhotoSubmission, SubmissionStatus
from apps.shared.domain.store import StoreReference

logger = logging.getLogger(__name__)


class SweepStaleProcessing:
    """Mark every stuck processing or uploaded submission of each store as failed."""

    def __init__(self, *, repository: PhotoSubmissionRepository, stale_after: timedelta):
        self._repository = repository
        self._stale_after = stale_after

    def __call__(
        self, now: datetime, *, store: StoreReference | None = None
    ) -> list[PhotoSubmission]:
        cutoff = now - self._stale_after
        stores = [store] if store is not None else self._stores(cutoff)
        failed = []
        for target in stores:
            for submission in self._repository.list_stale_processing(target, cutoff):
                failed_submission = self._fail(target, submission)
                if failed_submission is not None:
                    failed.append(failed_submission)
        return failed

    def _stores(self, cutoff: datetime) -> list[StoreReference]:
        return [
            StoreReference(id=store_id, slug="")
            for store_id in self._repository.store_ids_with_stale_processing(cutoff)
        ]

    def _fail(self, store: StoreReference, submission: PhotoSubmission) -> PhotoSubmission | None:
        if submission.status not in (SubmissionStatus.PROCESSING, SubmissionStatus.UPLOADED):
            return None
        if not mark_processing_unavailable(submission):
            return None
        try:
            return self._repository.save(submission)
        except ConcurrentModification:
            logger.warning(
                "Skipped photo submission %s of store %s: it changed during the sweep",
                submission.id,
                store.id,
                extra={"store_id": store.id, "submission_id": submission.id},
            )
            return None
