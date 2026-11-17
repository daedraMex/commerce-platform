"""Change the products an applied group photo is linked to, without deleting links."""

from collections.abc import Iterable

from apps.photos.application.group_links import (
    normalize_product_ids,
    require_products,
    synchronize_links,
)
from apps.photos.application.ports import (
    PhotoCatalog,
    PhotoSubmissionRepository,
    UnitOfWork,
)
from apps.photos.domain.errors import CannotChangeGroupLinks
from apps.photos.domain.submission import PhotoSubmission, SubmissionKind
from apps.shared.domain.exceptions import NotFoundError
from apps.shared.domain.permissions import MANAGE_CATALOG
from apps.shared.domain.ports import Authorizer
from apps.shared.domain.store import StoreReference


class ChangeGroupPhotoLinks:
    """Authorize and reconcile one group photo's product links with a new selection."""

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
        product_ids: Iterable[int],
    ) -> PhotoSubmission:
        self._authorizer.require(user_id, store, MANAGE_CATALOG)

        submission = self._repository.get(store, submission_id)
        if submission is None:
            raise NotFoundError("No photo submission matches this id in this store.")
        self._require_applied_group(submission)

        desired = normalize_product_ids(product_ids)
        with self._unit_of_work():
            submission = self._repository.get_for_update(store, submission_id)
            if submission is None:
                raise NotFoundError("No photo submission matches this id in this store.")
            self._require_applied_group(submission)

            require_products(self._catalog, store, desired)
            synchronize_links(
                self._catalog,
                store,
                media_id=submission.result_media_id,
                product_ids=desired,
            )
            return submission

    def _require_applied_group(self, submission: PhotoSubmission) -> None:
        if submission.kind is not SubmissionKind.GROUP:
            raise CannotChangeGroupLinks("Only a group photo has a product selection.")
        if submission.result_media_id is None:
            raise CannotChangeGroupLinks("Only a ready group photo has a product selection.")
        if submission.applied_at is None:
            raise CannotChangeGroupLinks("Apply the group photo before changing its links.")
