"""Apply a ready photo, appending an individual result or linking a group photo (ADR-0030)."""

from collections.abc import Iterable
from datetime import UTC, datetime

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
from apps.photos.domain.errors import CannotApply
from apps.photos.domain.submission import (
    INDIVIDUAL_KINDS,
    PhotoSubmission,
    SubmissionKind,
    SubmissionStatus,
)
from apps.shared.domain.exceptions import NotFoundError
from apps.shared.domain.permissions import MANAGE_CATALOG
from apps.shared.domain.ports import Authorizer
from apps.shared.domain.store import StoreReference


class ApplyPhoto:
    """Authorize and append one ready result through the catalog service."""

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
        product_ids: Iterable[int] | None = None,
        now: datetime | None = None,
    ) -> PhotoSubmission:
        self._authorizer.require(user_id, store, MANAGE_CATALOG)

        submission = self._repository.get(store, submission_id)
        if submission is None:
            raise NotFoundError("No photo submission matches this id in this store.")
        if submission.kind is SubmissionKind.GROUP:
            return self._apply_group(
                store,
                user_id=user_id,
                submission_id=submission_id,
                product_ids=product_ids,
                now=now,
            )

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

    def _apply_group(
        self,
        store: StoreReference,
        *,
        user_id: int,
        submission_id: int,
        product_ids: Iterable[int] | None,
        now: datetime | None,
    ) -> PhotoSubmission:
        desired = normalize_product_ids(product_ids or ())
        if not desired:
            raise CannotApply("Select at least one product for a group photo.")

        with self._unit_of_work():
            submission = self._repository.get_for_update(store, submission_id)
            if submission is None:
                raise NotFoundError("No photo submission matches this id in this store.")
            if submission.kind is not SubmissionKind.GROUP:
                raise CannotApply("Only a group photo links several products.")
            if (
                submission.status is not SubmissionStatus.READY
                or submission.result_media_id is None
            ):
                raise CannotApply("Only a ready photo can be applied.")

            require_products(self._catalog, store, desired)
            applied_now = submission.applied_at is None
            if applied_now:
                submission.apply(user_id, now or datetime.now(UTC))
            synchronize_links(
                self._catalog,
                store,
                media_id=submission.result_media_id,
                product_ids=desired,
            )
            if applied_now:
                return self._repository.save(submission)
            return submission
