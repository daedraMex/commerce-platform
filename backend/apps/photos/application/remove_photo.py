"""Remove an applied photo from its product's carousel without deleting the Media."""

from apps.photos.application.ports import (
    PhotoCatalog,
    PhotoSubmissionRepository,
    UnitOfWork,
)
from apps.photos.domain.errors import CannotRemove
from apps.photos.domain.submission import PhotoSubmission, SubmissionKind
from apps.shared.domain.exceptions import NotFoundError
from apps.shared.domain.permissions import MANAGE_CATALOG
from apps.shared.domain.ports import Authorizer
from apps.shared.domain.store import StoreReference


class RemovePhoto:
    """Authorize and deactivate one applied photo's place in the carousel (ADR-0030)."""

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
        self, store: StoreReference, *, user_id: int, submission_id: int
    ) -> PhotoSubmission:
        self._authorizer.require(user_id, store, MANAGE_CATALOG)

        submission = self._repository.get(store, submission_id)
        if submission is None:
            raise NotFoundError("No photo submission matches this id in this store.")
        if submission.applied_at is None:
            raise CannotRemove("Only an applied photo can be removed.")
        if submission.kind is SubmissionKind.GROUP:
            raise CannotRemove(
                "A group photo has no carousel link of its own; change its links through "
                "the links endpoint instead."
            )

        submission.remove()
        with self._unit_of_work():
            self._catalog.remove_from_carousel(
                store,
                product_id=submission.target_product_id,
                media_id=submission.result_media_id,
            )
            return self._repository.save(submission)
