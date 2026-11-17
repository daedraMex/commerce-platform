"""Fakes for photo use-case tests; they never touch storage or a database."""

from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from apps.catalog.services import (
    CategoryReference,
    MediaRecord,
    ProductImageNotFound,
    ProductImageRecord,
    ProductImageRole,
    ProductRecord,
    VariantRecord,
)
from apps.photos.application.ports import UploadedPhoto
from apps.photos.domain.errors import DuplicateIdempotencyKey
from apps.photos.domain.submission import PhotoSubmission
from apps.shared.domain.exceptions import PermissionDeniedError
from apps.shared.domain.store import StoreReference

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
HOME = StoreReference(id=1, slug="home")


@dataclass
class FakeMediaUploader:
    """Record uploads and deletes, returning stable private keys."""

    upload_error: Exception | None = None
    calls: list[tuple[StoreReference, bytes]] = field(default_factory=list)
    deleted: list[tuple[StoreReference, str]] = field(default_factory=list)

    def upload(self, store: StoreReference, content: bytes) -> UploadedPhoto:
        self.calls.append((store, content))
        if self.upload_error is not None:
            raise self.upload_error
        return UploadedPhoto(
            original_key=f"stores/{store.id}/photos/originals/test.jpg",
            preview_key=f"stores/{store.id}/photos/previews/test.jpg",
            width=12,
            height=8,
        )

    def delete(self, store: StoreReference, key: str) -> None:
        self.deleted.append((store, key))


@dataclass
class FakeAuthorizer:
    """Record every rule it is asked to enforce; optionally deny them all."""

    allowed: bool = True
    calls: list[tuple[int, StoreReference, str]] = field(default_factory=list)

    def require(self, user_id: int, store: StoreReference, permission: str) -> None:
        self.calls.append((user_id, store, permission))
        if not self.allowed:
            raise PermissionDeniedError("You do not have permission to perform this action.")


@dataclass
class FakePhotoSubmissionRepository:
    """Keep submissions in memory with the same store and key scoping as the ORM."""

    rows: dict[int, PhotoSubmission] = field(default_factory=dict)
    next_id: int = 1

    def __init__(self, rows=()):
        self.rows = {row.id: row for row in rows}
        self.next_id = max(self.rows, default=0) + 1

    def get(self, store: StoreReference, submission_id: int) -> PhotoSubmission | None:
        row = self.rows.get(submission_id)
        return row if row is not None and row.store_id == store.id else None

    def get_for_update(self, store: StoreReference, submission_id: int) -> PhotoSubmission | None:
        return self.get(store, submission_id)

    def get_by_idempotency_key(
        self, store: StoreReference, created_by: int, key: str
    ) -> PhotoSubmission | None:
        return next(
            (
                row
                for row in self.rows.values()
                if row.store_id == store.id
                and row.created_by_id == created_by
                and row.idempotency_key == key
            ),
            None,
        )

    def add(self, submission: PhotoSubmission) -> PhotoSubmission:
        if self.get_by_idempotency_key(
            StoreReference(id=submission.store_id, slug=""),
            submission.created_by_id,
            submission.idempotency_key,
        ):
            raise DuplicateIdempotencyKey("This idempotency key was already used in this store.")
        submission.id = self.next_id
        submission.version = 0
        submission.created_at = NOW
        submission.updated_at = NOW
        self.rows[submission.id] = submission
        self.next_id += 1
        return submission

    def save(self, submission: PhotoSubmission) -> PhotoSubmission:
        submission.version += 1
        submission.updated_at = NOW
        self.rows[submission.id] = submission
        return submission


@dataclass
class FakeCatalog:
    """Answer the photo use cases' catalog lookups and keep a small carousel."""

    products: dict[int, ProductRecord] = field(default_factory=dict)
    variants: dict[int, VariantRecord] = field(default_factory=dict)
    media: dict[int, MediaRecord] = field(default_factory=dict)
    images: dict[int, ProductImageRecord] = field(default_factory=dict)

    append_calls: list[dict] = field(default_factory=list)
    remove_calls: list[dict] = field(default_factory=list)

    def __init__(self, *, products=(), variants=(), media=(), images=()):
        self.products = {product.id: product for product in products}
        self.variants = {variant.id: variant for variant in variants}
        self.media = {item.id: item for item in media}
        self.images = {image.id: image for image in images}
        self.append_calls = []
        self.remove_calls = []

    def get_product(self, store: StoreReference, product_id: int) -> ProductRecord | None:
        product = self.products.get(product_id)
        return product if product is not None and product.store_id == store.id else None

    def get_variant(self, store: StoreReference, variant_id: int) -> VariantRecord | None:
        variant = self.variants.get(variant_id)
        return variant if variant is not None and variant.store_id == store.id else None

    def get_media(self, store: StoreReference, media_id: int) -> MediaRecord | None:
        item = self.media.get(media_id)
        return item if item is not None and item.store_id == store.id else None

    def product_images_for_media(
        self, store: StoreReference, media_id: int
    ) -> list[ProductImageRecord]:
        return sorted(
            (
                image
                for image in self.images.values()
                if image.store_id == store.id and image.media_id == media_id
            ),
            key=lambda image: (image.product_id, image.position, image.id),
        )

    def append_to_carousel(
        self,
        store: StoreReference,
        *,
        product_id: int,
        media_id: int,
        variant_id: int | None = None,
    ) -> ProductImageRecord:
        self.append_calls.append(
            {
                "store": store,
                "product_id": product_id,
                "media_id": media_id,
                "variant_id": variant_id,
            }
        )
        existing = next(
            (
                image
                for image in self.images.values()
                if image.product_id == product_id and image.media_id == media_id
            ),
            None,
        )
        if existing is not None and existing.is_active:
            return existing

        active = self._active_images(product_id)
        role = ProductImageRole.GALLERY if active else ProductImageRole.MAIN
        position = max((image.position for image in active), default=0) + 1
        if existing is not None:
            restored = replace(
                existing,
                variant_id=variant_id,
                role=role,
                position=position,
                is_active=True,
            )
            self.images[existing.id] = restored
            return restored

        image_id = max(self.images, default=0) + 1
        image = ProductImageRecord(
            id=image_id,
            store_id=store.id,
            product_id=product_id,
            media_id=media_id,
            variant_id=variant_id,
            role=role,
            position=position,
            is_active=True,
        )
        self.images[image_id] = image
        return image

    def remove_from_carousel(
        self,
        store: StoreReference,
        *,
        product_id: int,
        media_id: int,
    ) -> ProductImageRecord:
        self.remove_calls.append({"store": store, "product_id": product_id, "media_id": media_id})
        image = next(
            (
                candidate
                for candidate in self.images.values()
                if candidate.product_id == product_id and candidate.media_id == media_id
            ),
            None,
        )
        if image is None:
            raise ProductImageNotFound("No product image links that media.")
        was_cover = image.role is ProductImageRole.MAIN
        removed = replace(
            image,
            role=ProductImageRole.GALLERY if was_cover else image.role,
            is_active=False,
        )
        self.images[image.id] = removed
        if was_cover:
            active = self._active_images(product_id)
            if active:
                next_cover = active[0]
                self.images[next_cover.id] = replace(next_cover, role=ProductImageRole.MAIN)
        return removed

    def _active_images(self, product_id: int) -> list[ProductImageRecord]:
        return sorted(
            (
                image
                for image in self.images.values()
                if image.product_id == product_id and image.is_active
            ),
            key=lambda image: (image.position, image.id),
        )


@dataclass
class FakeUnitOfWork:
    """Track whether a unit of work committed or rolled back."""

    depth: int = 0
    entered: int = 0
    committed: int = 0
    rolled_back: int = 0

    @contextmanager
    def __call__(self):
        self.depth += 1
        self.entered += 1
        try:
            yield
        except Exception:
            self.rolled_back += 1
            raise
        else:
            if self.depth == 1:
                self.committed += 1
        finally:
            self.depth -= 1


@dataclass
class FakeProcessingQueue:
    """Record every submission enqueued for processing."""

    calls: list[tuple[StoreReference, int]] = field(default_factory=list)

    def enqueue(self, store: StoreReference, submission_id: int) -> None:
        self.calls.append((store, submission_id))


def make_product(product_id=10, store=HOME):
    return ProductRecord(
        id=product_id,
        store_id=store.id,
        name="Blanket",
        slug="blanket",
        category=CategoryReference(id=1, shape="rectangle", option_schema=()),
    )


def make_variant(variant_id=20, product_id=10, store=HOME):
    return VariantRecord(
        id=variant_id,
        store_id=store.id,
        product_id=product_id,
        sku="FRZ-001-IND",
        option_values={},
    )


def make_media(media_id=30, store=HOME, *, content_hash="hash-1"):
    return MediaRecord(
        id=media_id,
        store_id=store.id,
        storage_key=f"stores/{store.id}/media/{content_hash}.jpg",
        content_hash=content_hash,
        mime_type="image/jpeg",
        alt_text="",
        width=800,
        height=1000,
        metadata={"format": "JPEG", "bytes": 10},
    )
