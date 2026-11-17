"""Read one Photo submission and its result media for the staff status API."""

from dataclasses import dataclass

from apps.catalog.services import MediaRecord
from apps.photos.application.ports import PhotoCatalog, PhotoSubmissionRepository
from apps.photos.domain.submission import PhotoSubmission, SubmissionKind
from apps.shared.domain.exceptions import NotFoundError
from apps.shared.domain.permissions import MANAGE_CATALOG
from apps.shared.domain.ports import Authorizer
from apps.shared.domain.store import StoreReference


@dataclass(frozen=True, slots=True)
class PhotoSubmissionView:
    """A submission plus the public Media it produced and the products it links."""

    submission: PhotoSubmission
    result_media: MediaRecord | None
    linked_product_ids: tuple[int, ...] = ()


def build_submission_view(
    catalog: PhotoCatalog, store: StoreReference, submission: PhotoSubmission
) -> PhotoSubmissionView:
    """Assemble the read model for one submission, including a group photo's active links."""
    result_media = None
    linked_product_ids = ()
    if submission.result_media_id is not None:
        result_media = catalog.get_media(store, submission.result_media_id)
        if submission.kind is SubmissionKind.GROUP:
            linked_product_ids = tuple(
                link.product_id
                for link in catalog.product_images_for_media(store, submission.result_media_id)
                if link.is_active
            )
    return PhotoSubmissionView(
        submission=submission,
        result_media=result_media,
        linked_product_ids=linked_product_ids,
    )


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

        return build_submission_view(self._catalog, store, submission)
