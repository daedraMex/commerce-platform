"""Read one product's carousel with its active and inactive photos (ADR-0030)."""

from dataclasses import dataclass

from apps.catalog.services import MediaRecord
from apps.photos.application.ports import PhotoCatalog, PhotoSubmissionRepository
from apps.photos.domain.submission import PhotoSubmission, SubmissionStatus
from apps.shared.domain.exceptions import NotFoundError
from apps.shared.domain.permissions import MANAGE_CATALOG
from apps.shared.domain.ports import Authorizer
from apps.shared.domain.store import StoreReference


@dataclass(frozen=True, slots=True)
class CarouselImage:
    """One tile of the staff carousel: a linked image or a ready unapproved photo."""

    id: int | None
    media: MediaRecord
    active: bool
    role: str | None
    position: int | None
    photo_submission_id: int | None


@dataclass(frozen=True, slots=True)
class ProductCarousel:
    """The product id and its carousel tiles in display order."""

    product_id: int
    images: tuple[CarouselImage, ...]


def _submission_for_media(
    submissions: list[PhotoSubmission], media_id: int, product_id: int
) -> int | None:
    best = None
    for submission in submissions:
        if submission.status is not SubmissionStatus.READY:
            continue
        if submission.result_media_id != media_id:
            continue
        if submission.target_product_id == product_id:
            return submission.id
        if submission.target_product_id is None and best is None:
            best = submission.id
    return best


def build_product_carousel(
    catalog: PhotoCatalog,
    repository: PhotoSubmissionRepository,
    store: StoreReference,
    product_id: int,
) -> ProductCarousel:
    """Assemble active links, retired links and ready unapproved photos for one product."""
    product = catalog.get_product(store, product_id)
    if product is None:
        raise NotFoundError("No product matches this id in this store.")

    links = catalog.product_images(store, product_id)
    media_ids = list(dict.fromkeys(link.media_id for link in links))
    submissions = repository.list_for_product(store, product_id, media_ids)

    images: list[CarouselImage] = []
    active = sorted(
        (link for link in links if link.is_active),
        key=lambda link: (link.position, link.id),
    )
    inactive = sorted(
        (link for link in links if not link.is_active),
        key=lambda link: (link.position, link.id),
    )
    for link in [*active, *inactive]:
        media = catalog.get_media(store, link.media_id)
        if media is None:
            continue
        images.append(
            CarouselImage(
                id=link.id,
                media=media,
                active=link.is_active,
                role=link.role.value,
                position=link.position,
                photo_submission_id=_submission_for_media(submissions, link.media_id, product_id),
            )
        )

    linked_media_ids = set(media_ids)
    seen_pending: set[int] = set()
    for submission in submissions:
        if (
            submission.target_product_id != product_id
            or submission.status is not SubmissionStatus.READY
            or submission.applied_at is not None
            or submission.result_media_id is None
        ):
            continue
        if (
            submission.result_media_id in linked_media_ids
            or submission.result_media_id in seen_pending
        ):
            continue
        media = catalog.get_media(store, submission.result_media_id)
        if media is None:
            continue
        seen_pending.add(submission.result_media_id)
        images.append(
            CarouselImage(
                id=None,
                media=media,
                active=False,
                role=None,
                position=None,
                photo_submission_id=submission.id,
            )
        )

    return ProductCarousel(product_id=product_id, images=tuple(images))


class GetProductImages:
    """Authorize and return one product's carousel, active images first."""

    def __init__(
        self,
        *,
        catalog: PhotoCatalog,
        repository: PhotoSubmissionRepository,
        authorizer: Authorizer,
    ):
        self._catalog = catalog
        self._repository = repository
        self._authorizer = authorizer

    def __call__(self, store: StoreReference, *, user_id: int, product_id: int) -> ProductCarousel:
        self._authorizer.require(user_id, store, MANAGE_CATALOG)
        return build_product_carousel(self._catalog, self._repository, store, product_id)
