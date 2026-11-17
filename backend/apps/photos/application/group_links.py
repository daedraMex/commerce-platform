"""Reconcile the product links of one group photo's shared result Media (ADR-0028)."""

from collections.abc import Iterable

from apps.catalog.services import StoreMismatch
from apps.photos.application.ports import PhotoCatalog
from apps.shared.domain.store import StoreReference


def normalize_product_ids(product_ids: Iterable[int]) -> tuple[int, ...]:
    """Order and deduplicate a selection so concurrent runs lock products in one order."""
    return tuple(sorted(set(product_ids)))


def require_products(
    catalog: PhotoCatalog, store: StoreReference, product_ids: Iterable[int]
) -> None:
    """Refuse a selection that names a product another store owns or that does not exist."""
    for product_id in product_ids:
        if catalog.get_product(store, product_id) is None:
            raise StoreMismatch("The product does not belong to this store.")


def synchronize_links(
    catalog: PhotoCatalog,
    store: StoreReference,
    *,
    media_id: int,
    product_ids: Iterable[int],
) -> None:
    """Keep retained links untouched, deactivate the rest, and add or reactivate the rest."""
    desired = set(product_ids)
    current = catalog.product_images_for_media(store, media_id)

    for link in sorted(current, key=lambda link: link.product_id):
        if link.is_active and link.product_id not in desired:
            catalog.remove_from_carousel(store, product_id=link.product_id, media_id=media_id)

    retained = {link.product_id for link in current if link.is_active}
    for product_id in sorted(desired - retained):
        catalog.append_to_carousel(store, product_id=product_id, media_id=media_id)
