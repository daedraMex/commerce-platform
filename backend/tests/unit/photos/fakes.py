"""Fakes for photo use-case tests; they never touch storage or a database."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from apps.catalog.services import (
    CategoryReference,
    MediaRecord,
    NewMedia,
    ProductImageRecord,
    ProductImageRole,
    ProductRecord,
    VariantRecord,
)
from apps.photos.application.ports import RenderedPhoto, UploadedPhoto
from apps.photos.domain.errors import DuplicateIdempotencyKey
from apps.photos.domain.submission import PhotoSubmission
from apps.shared.domain.exceptions import PermissionDeniedError
from apps.shared.domain.store import StoreReference

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
HOME = StoreReference(id=1, slug="home")


@dataclass
class FakeMediaUploader:
    """Record uploads and return stable private keys for later use-case tests."""

    upload_error: Exception | None = None
    calls: list[tuple[StoreReference, bytes]] = field(default_factory=list)

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
    """Answer the photo use cases' catalog lookups, scoped by store."""

    products: dict[int, ProductRecord] = field(default_factory=dict)
    variants: dict[int, VariantRecord] = field(default_factory=dict)
    media: dict[int, MediaRecord] = field(default_factory=dict)
    created_media: list[NewMedia] = field(default_factory=list)
    links: list[tuple[int, int, int | None]] = field(default_factory=list)
    next_media_id: int = 100

    def __init__(self, *, products=(), variants=(), media=()):
        self.products = {product.id: product for product in products}
        self.variants = {variant.id: variant for variant in variants}
        self.media = {item.id: item for item in media}
        self.created_media = []
        self.links = []
        self.next_media_id = max(self.media, default=99) + 1

    def get_product(self, store: StoreReference, product_id: int) -> ProductRecord | None:
        product = self.products.get(product_id)
        return product if product is not None and product.store_id == store.id else None

    def get_variant(self, store: StoreReference, variant_id: int) -> VariantRecord | None:
        variant = self.variants.get(variant_id)
        return variant if variant is not None and variant.store_id == store.id else None

    def get_media(self, store: StoreReference, media_id: int) -> MediaRecord | None:
        item = self.media.get(media_id)
        return item if item is not None and item.store_id == store.id else None

    def create_media(self, store: StoreReference, media: NewMedia) -> MediaRecord:
        existing = next(
            (
                item
                for item in self.media.values()
                if item.store_id == store.id and item.content_hash == media.content_hash
            ),
            None,
        )
        if existing is not None:
            return existing
        self.created_media.append(media)
        record = MediaRecord(
            id=self.next_media_id,
            store_id=store.id,
            storage_key=media.storage_key,
            content_hash=media.content_hash,
            mime_type=media.mime_type,
            alt_text=media.alt_text,
            width=media.width,
            height=media.height,
            metadata=media.metadata,
        )
        self.media[record.id] = record
        self.next_media_id += 1
        return record

    def set_main_product_image(
        self,
        store: StoreReference,
        *,
        product_id: int,
        media_id: int,
        variant_id: int | None = None,
    ) -> ProductImageRecord:
        self.links.append((product_id, media_id, variant_id))
        return ProductImageRecord(
            id=len(self.links),
            store_id=store.id,
            product_id=product_id,
            media_id=media_id,
            variant_id=variant_id,
            role=ProductImageRole.MAIN,
            position=1,
            is_active=True,
        )


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


@dataclass
class FakeProcessingQueue:
    """Record the submissions a use case enqueues."""

    calls: list[tuple[StoreReference, int]] = field(default_factory=list)

    def enqueue(self, store: StoreReference, submission_id: int) -> None:
        self.calls.append((store, submission_id))


@dataclass
class FakePrivateMediaReader:
    """Return stored bytes for a private key, or raise a configured error."""

    files: dict[tuple[int, str], bytes] = field(default_factory=dict)
    error: Exception | None = None

    def open(self, store: StoreReference, key: str):
        if self.error is not None:
            raise self.error
        from io import BytesIO

        return BytesIO(self.files[(store.id, key)])


@dataclass
class FakeRenderer:
    """Return one rendered result, or raise a configured error on every call."""

    rendered: RenderedPhoto | None = None
    error: Exception | None = None
    calls: list[tuple[PhotoSubmission, bytes]] = field(default_factory=list)

    def render(self, submission: PhotoSubmission, original: bytes) -> RenderedPhoto:
        self.calls.append((submission, original))
        if self.error is not None:
            raise self.error
        return self.rendered or RenderedPhoto(
            content=b"rendered-photo",
            width=800,
            height=1000,
            mime_type="image/jpeg",
            extension="jpg",
            metadata={"format": "JPEG", "bytes": 14},
        )
