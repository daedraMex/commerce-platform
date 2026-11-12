"""Read one Photo submission and its result media for the staff status API."""

from dataclasses import dataclass

from apps.catalog.services import MediaRecord
from apps.photos.application.ports import PhotoCatalog, PhotoSubmissionRepository
from apps.photos.domain.submission import PhotoSubmission
from apps.shared.domain.exceptions import NotFoundError
from apps.shared.domain.permissions import MANAGE_CATALOG
from apps.shared.domain.ports import Authorizer
from apps.shared.domain.store import StoreReference


@dataclass(frozen=True, slots=True)
class PhotoSubmissionView:
    """A submission plus the public Media it produced, if it is ready."""

    submission: PhotoSubmission
    result_media: MediaRecord | None


class GetPhotoSubmission:
    """Authorize and return one store's submission; another store's id is not found."""

    def __init__(
        self,
        *,
        repository: PhotoSubmissionRepository,
        catalog: PhotoCatalog,
        authorizer: Authorizer,
    ):
        self._repository = repository
        self._catalog = catalog
        self._authorizer = authorizer

    def __call__(
        self, store: StoreReference, *, user_id: int, submission_id: int
    ) -> PhotoSubmissionView:
        self._authorizer.require(user_id, store, MANAGE_CATALOG)

        submission = self._repository.get(store, submission_id)
        if submission is None:
            raise NotFoundError("No photo submission matches this id in this store.")

        result_media = None
        if submission.result_media_id is not None:
            result_media = self._catalog.get_media(store, submission.result_media_id)
        return PhotoSubmissionView(submission=submission, result_media=result_media)
