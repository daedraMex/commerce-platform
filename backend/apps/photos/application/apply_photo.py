"""Apply a ready individual photo as the product's active main image."""

from datetime import UTC, datetime

from apps.photos.application.ports import PhotoCatalog, PhotoSubmissionRepository
from apps.photos.domain.errors import CannotApply
from apps.photos.domain.submission import INDIVIDUAL_KINDS, PhotoSubmission
from apps.shared.domain.exceptions import NotFoundError
from apps.shared.domain.permissions import MANAGE_CATALOG
from apps.shared.domain.ports import Authorizer
from apps.shared.domain.store import StoreReference


class ApplyPhoto:
    """Authorize and link one ready individual result through the catalog service."""

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
        if submission.kind not in INDIVIDUAL_KINDS:
            raise CannotApply("Only an individual photo can become a product's main image.")
        if submission.result_media_id is None:
            raise CannotApply("Only a ready photo can be applied.")

        submission.apply(user_id, now or datetime.now(UTC))
        self._catalog.set_main_product_image(
            store,
            product_id=submission.target_product_id,
            media_id=submission.result_media_id,
            variant_id=submission.photographed_variant_id,
        )
        return self._repository.save(submission)
