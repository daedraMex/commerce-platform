"""The catalog service seam other modules use to change product images (ADR-0028).

Pure Python: the Django implementations live in ``apps.catalog.repositories`` so the
store rules can be tested with fake repositories.
"""

from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol

from apps.shared.domain.exceptions import DomainError
from apps.shared.domain.store import StoreReference


class CatalogServiceError(DomainError):
    """A catalog service command cannot be completed."""

    code = "catalog_service_error"


class StoreMismatch(CatalogServiceError):
    """A product, media row or image link does not belong to the requested store."""

    code = "catalog_store_mismatch"


class ProductImageConflict(CatalogServiceError):
    """The product is already linked to that media."""

    code = "catalog_product_image_conflict"


class ProductImageNotFound(CatalogServiceError):
    """No image link with that id belongs to the requested store."""

    code = "catalog_product_image_not_found"


class VariantNotFound(CatalogServiceError):
    """No variant with that id belongs to the requested product."""

    code = "catalog_variant_not_found"


class ProductImageRole(StrEnum):
    MAIN = "main"
    GALLERY = "gallery"


@dataclass(frozen=True, slots=True)
class NewMedia:
    """A final product image and the content-addressed key it is stored under."""

    content: bytes
    content_hash: str
    storage_key: str
    mime_type: str
    width: int
    height: int
    metadata: dict
    alt_text: str = ""


@dataclass(frozen=True, slots=True)
class MediaRecord:
    id: int
    store_id: int
    storage_key: str
    content_hash: str
    mime_type: str
    alt_text: str
    width: int
    height: int
    metadata: dict


@dataclass(frozen=True, slots=True)
class CategoryReference:
    id: int
    shape: str
    option_schema: tuple[dict, ...]


@dataclass(frozen=True, slots=True)
class ProductRecord:
    id: int
    store_id: int
    name: str
    slug: str
    category: CategoryReference


@dataclass(frozen=True, slots=True)
class VariantRecord:
    id: int
    store_id: int
    product_id: int
    sku: str
    option_values: dict


@dataclass(frozen=True, slots=True)
class NewProductImage:
    product_id: int
    media_id: int
    variant_id: int | None
    role: ProductImageRole
    position: int | None


@dataclass(frozen=True, slots=True)
class ProductImageRecord:
    id: int
    store_id: int
    product_id: int
    media_id: int
    variant_id: int | None
    role: ProductImageRole
    position: int
    is_active: bool


class UnitOfWork(Protocol):
    """Run a block of work atomically, rolling every change in it back on failure."""

    def __call__(self) -> AbstractContextManager[None]: ...


class CatalogRepository(Protocol):
    """Persistence the service needs; the service enforces the store rules."""

    def lock_product(self, store_id: int, product_id: int) -> None:
        """Lock the store's product row for the rest of the transaction, if it exists."""
        ...

    def media_by_content_hash(self, store_id: int, content_hash: str) -> MediaRecord | None:
        """Return the store's Media with that content hash, if any."""
        ...

    def media_by_id(self, store_id: int, media_id: int) -> MediaRecord | None:
        """Return the store's Media with that id, if any."""
        ...

    def add_media(self, store_id: int, media: NewMedia) -> MediaRecord:
        """Insert the media row and return it with its id."""
        ...

    def get_product(self, store_id: int, product_id: int) -> ProductRecord | None:
        """Return the product of that store, if any."""
        ...

    def get_variant(self, store_id: int, variant_id: int) -> VariantRecord | None:
        """Return the variant of that store, if any."""
        ...

    def get_product_image(self, image_id: int) -> ProductImageRecord | None:
        """Return the image link, active or retired, if any."""
        ...

    def find_product_image(self, product_id: int, media_id: int) -> ProductImageRecord | None:
        """Return the product's link to that media, active or retired, if any."""
        ...

    def active_main_image(self, product_id: int) -> ProductImageRecord | None:
        """Return the product's one active main image, if any."""
        ...

    def active_product_images(self, product_id: int) -> list[ProductImageRecord]:
        """Return the product's active image links ordered by position."""
        ...

    def add_product_image(self, image: NewProductImage) -> ProductImageRecord:
        """Insert the link, assigning a position when it has none."""
        ...

    def save_product_image(self, image: ProductImageRecord) -> ProductImageRecord:
        """Persist the changed link without changing its position."""
        ...


class MediaFileWriter(Protocol):
    """Store a media file and its renditions under the content-addressed key."""

    def store(self, media: NewMedia) -> None:
        """Write ``media``; writing the same key twice is harmless."""
        ...


class CatalogService:
    """The catalog seam: Media creation, product-image rules and store-scoped lookup."""

    def __init__(
        self,
        *,
        repository: CatalogRepository,
        files: MediaFileWriter,
        transaction: UnitOfWork,
    ):
        self._repository = repository
        self._files = files
        self._transaction = transaction

    def create_media(self, store: StoreReference, media: NewMedia) -> MediaRecord:
        """Return the store's Media for the content, creating and storing it once."""
        existing = self._repository.media_by_content_hash(store.id, media.content_hash)
        if existing is not None:
            return existing
        self._files.store(media)
        return self._repository.add_media(store.id, media)

    def get_product(self, store: StoreReference, product_id: int) -> ProductRecord | None:
        """Return a product of the store, or None when another store owns it."""
        return self._repository.get_product(store.id, product_id)

    def get_variant(self, store: StoreReference, variant_id: int) -> VariantRecord | None:
        """Return a variant of the store, or None when another store owns it."""
        return self._repository.get_variant(store.id, variant_id)

    def get_media(self, store: StoreReference, media_id: int) -> MediaRecord | None:
        """Return a media of the store, or None when another store owns it."""
        return self._repository.media_by_id(store.id, media_id)

    def create_product_image(
        self,
        store: StoreReference,
        *,
        product_id: int,
        media_id: int,
        variant_id: int | None = None,
        role: ProductImageRole = ProductImageRole.GALLERY,
        position: int | None = None,
    ) -> ProductImageRecord:
        """Link a media to a product once, refusing a link that already exists."""
        with self._transaction():
            self._repository.lock_product(store.id, product_id)
            product = self._require_product(store, product_id)
            self._require_media(store, media_id)
            if variant_id is not None:
                self._require_variant_of_product(store, product, variant_id)
            return self._add_image(
                product.id,
                media_id=media_id,
                variant_id=variant_id,
                role=role,
                position=position,
            )

    def deactivate_product_image(
        self, store: StoreReference, *, image_id: int
    ) -> ProductImageRecord:
        """Retire one link, keeping its role and position."""
        with self._transaction():
            image = self._require_image(store, image_id)
            self._repository.lock_product(store.id, image.product_id)
            if not image.is_active:
                return image
            return self._repository.save_product_image(replace(image, is_active=False))

    def reactivate_product_image(
        self, store: StoreReference, *, image_id: int
    ) -> ProductImageRecord:
        """Restore one link, keeping its role and position."""
        with self._transaction():
            image = self._require_image(store, image_id)
            self._repository.lock_product(store.id, image.product_id)
            if image.role is ProductImageRole.MAIN:
                self._retire_other_mains(image.product_id, keep_id=image.id)
            return self._repository.save_product_image(replace(image, is_active=True))

    def append_to_carousel(
        self,
        store: StoreReference,
        *,
        product_id: int,
        media_id: int,
        variant_id: int | None = None,
    ) -> ProductImageRecord:
        """Append a media to the carousel, making it the cover when there is none (ADR-0030).

        An existing active link is returned unchanged. A retired link to the same
        media is reactivated at the end instead of inserting a duplicate.
        """
        with self._transaction():
            self._repository.lock_product(store.id, product_id)
            product = self._require_product(store, product_id)
            self._require_media(store, media_id)
            if variant_id is not None:
                self._require_variant_of_product(store, product, variant_id)

            existing = self._repository.find_product_image(product.id, media_id)
            if existing is not None and existing.is_active:
                return existing

            active = self._repository.active_product_images(product.id)
            if active:
                role = ProductImageRole.GALLERY
                position = max(image.position for image in active) + 1
            else:
                role = ProductImageRole.MAIN
                position = 1

            if existing is not None:
                return self._repository.save_product_image(
                    replace(
                        existing,
                        variant_id=variant_id,
                        role=role,
                        position=position,
                        is_active=True,
                    )
                )
            return self._repository.add_product_image(
                NewProductImage(
                    product_id=product.id,
                    media_id=media_id,
                    variant_id=variant_id,
                    role=role,
                    position=position,
                )
            )

    def remove_from_carousel(
        self,
        store: StoreReference,
        *,
        product_id: int,
        media_id: int,
    ) -> ProductImageRecord:
        """Deactivate one link, moving the main role to the next image by position."""
        with self._transaction():
            self._repository.lock_product(store.id, product_id)
            product = self._require_product(store, product_id)
            image = self._repository.find_product_image(product.id, media_id)
            if image is None:
                raise ProductImageNotFound("No product image links that media.")
            if not image.is_active:
                return image

            was_cover = image.role is ProductImageRole.MAIN
            removed = self._repository.save_product_image(
                replace(
                    image,
                    role=ProductImageRole.GALLERY if was_cover else image.role,
                    is_active=False,
                )
            )
            if was_cover:
                active = self._repository.active_product_images(product.id)
                if active:
                    self._repository.save_product_image(
                        replace(active[0], role=ProductImageRole.MAIN)
                    )
            return removed

    def set_main_product_image(
        self,
        store: StoreReference,
        *,
        product_id: int,
        media_id: int,
        variant_id: int | None = None,
        position: int | None = None,
    ) -> ProductImageRecord:
        """Make the media the product's one active main image."""
        return self.upsert_product_image(
            store,
            product_id=product_id,
            media_id=media_id,
            variant_id=variant_id,
            role=ProductImageRole.MAIN,
            position=position,
        )

    def upsert_product_image(
        self,
        store: StoreReference,
        *,
        product_id: int,
        media_id: int,
        variant_id: int | None = None,
        role: ProductImageRole = ProductImageRole.GALLERY,
        position: int | None = None,
    ) -> ProductImageRecord:
        """Create or reactivate a product's link to a media without losing its position."""
        with self._transaction():
            self._repository.lock_product(store.id, product_id)
            product = self._require_product(store, product_id)
            self._require_media(store, media_id)
            if variant_id is not None:
                self._require_variant_of_product(store, product, variant_id)

            existing = self._repository.find_product_image(product.id, media_id)
            if existing is None:
                return self._add_image(
                    product.id,
                    media_id=media_id,
                    variant_id=variant_id,
                    role=role,
                    position=position,
                )

            role = ProductImageRole(role)
            if role is ProductImageRole.MAIN:
                self._retire_other_mains(product.id, keep_id=existing.id)
            changed = replace(
                existing,
                variant_id=variant_id,
                role=role,
                position=existing.position if position is None else position,
                is_active=True,
            )
            return self._repository.save_product_image(changed)

    def _add_image(
        self,
        product_id: int,
        *,
        media_id: int,
        variant_id: int | None,
        role: ProductImageRole,
        position: int | None,
    ) -> ProductImageRecord:
        if self._repository.find_product_image(product_id, media_id) is not None:
            raise ProductImageConflict("This product already links that media.")

        role = ProductImageRole(role)
        if role is ProductImageRole.MAIN:
            self._retire_other_mains(product_id, keep_id=None)
        return self._repository.add_product_image(
            NewProductImage(
                product_id=product_id,
                media_id=media_id,
                variant_id=variant_id,
                role=role,
                position=position,
            )
        )

    def _require_product(self, store: StoreReference, product_id: int) -> ProductRecord:
        product = self._repository.get_product(store.id, product_id)
        if product is None:
            raise StoreMismatch("The product does not belong to this store.")
        return product

    def _require_media(self, store: StoreReference, media_id: int) -> MediaRecord:
        media = self._repository.media_by_id(store.id, media_id)
        if media is None:
            raise StoreMismatch("The media does not belong to this store.")
        return media

    def _require_variant_of_product(
        self, store: StoreReference, product: ProductRecord, variant_id: int
    ) -> VariantRecord:
        variant = self._repository.get_variant(store.id, variant_id)
        if variant is None or variant.product_id != product.id:
            raise VariantNotFound("The variant does not belong to this product.")
        return variant

    def _require_image(self, store: StoreReference, image_id: int) -> ProductImageRecord:
        image = self._repository.get_product_image(image_id)
        if image is None:
            raise ProductImageNotFound("No product image has that id.")
        if image.store_id != store.id:
            raise StoreMismatch("The product image does not belong to this store.")
        return image

    def _retire_other_mains(self, product_id: int, *, keep_id: int | None) -> None:
        main = self._repository.active_main_image(product_id)
        if main is not None and main.id != keep_id:
            self._repository.save_product_image(replace(main, is_active=False))
