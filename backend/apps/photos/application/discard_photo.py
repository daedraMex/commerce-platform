"""Discard an unapplied photo submission and delete only its private files."""

from datetime import UTC, datetime

from apps.photos.application.ports import MediaUploader, PhotoSubmissionRepository
from apps.photos.domain.submission import PhotoSubmission
from apps.shared.domain.exceptions import NotFoundError
from apps.shared.domain.permissions import MANAGE_CATALOG
from apps.shared.domain.ports import Authorizer
from apps.shared.domain.store import StoreReference


class DiscardPhoto:
    """Authorize, stamp the submission discarded and remove its private files."""

    def __init__(
        self,
        *,
        repository: PhotoSubmissionRepository,
        uploader: MediaUploader,
        authorizer: Authorizer,
    ):
        self._repository = repository
        self._uploader = uploader
        self._authorizer = authorizer

    def __call__(
        self,
        store: StoreReference,
        *,
        user_id: int,
        submission_id: int,
        now: datetime | None = None,
    ) -> PhotoSubmission:
        self._authorizer.require(user_id, store, MANAGE_CATALOG)

        submission = self._repository.get(store, submission_id)
        if submission is None:
            raise NotFoundError("No photo submission matches this id in this store.")

        submission.discard(now or datetime.now(UTC))
        saved = self._repository.save(submission)
        for key in (saved.original_key, saved.preview_key):
            if key:
                self._uploader.delete(store, key)
        return saved
