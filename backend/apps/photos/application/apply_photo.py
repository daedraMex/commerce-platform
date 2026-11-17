"""Apply a ready individual photo by appending it to the product's carousel (ADR-0030)."""

from datetime import UTC, datetime

from apps.photos.application.ports import (
    PhotoCatalog,
    PhotoSubmissionRepository,
    UnitOfWork,
)
from apps.photos.domain.errors import CannotApply
from apps.photos.domain.submission import INDIVIDUAL_KINDS, PhotoSubmission
from apps.shared.domain.exceptions import NotFoundError
from apps.shared.domain.permissions import MANAGE_CATALOG
from apps.shared.domain.ports import Authorizer
from apps.shared.domain.store import StoreReference


class ApplyPhoto:
    """Authorize and append one ready individual result through the catalog service."""

    def __init__(
        self,
        *,
        repository: PhotoSubmissionRepository,
        catalog: PhotoCatalog,
        authorizer: Authorizer,
        unit_of_work: UnitOfWork,
    ):
        self._repository = repository
        self._catalog = catalog
        self._authorizer = authorizer
        self._unit_of_work = unit_of_work

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
            raise CannotApply("Only an individual photo can join a product's carousel.")
        if submission.result_media_id is None:
            raise CannotApply("Only a ready photo can be applied.")

        submission.apply(user_id, now or datetime.now(UTC))
        with self._unit_of_work():
            self._catalog.append_to_carousel(
                store,
                product_id=submission.target_product_id,
                media_id=submission.result_media_id,
                variant_id=submission.photographed_variant_id,
            )
            return self._repository.save(submission)
