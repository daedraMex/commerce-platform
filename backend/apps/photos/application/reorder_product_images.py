"""Reorder a product's carousel, moving the cover to the first image (ADR-0030)."""

from apps.photos.application.get_product_images import (
    ProductCarousel,
    build_product_carousel,
)
from apps.photos.application.ports import PhotoCatalog, PhotoSubmissionRepository
from apps.shared.domain.permissions import MANAGE_CATALOG
from apps.shared.domain.ports import Authorizer
from apps.shared.domain.store import StoreReference


class ReorderProductImages:
    """Authorize and save the full active order through the catalog service."""

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

    def __call__(
        self, store: StoreReference, *, user_id: int, product_id: int, image_ids: list[int]
    ) -> ProductCarousel:
        self._authorizer.require(user_id, store, MANAGE_CATALOG)
        self._catalog.reorder_carousel(store, product_id=product_id, image_ids=image_ids)
        return build_product_carousel(self._catalog, self._repository, store, product_id)
