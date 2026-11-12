"""Ports the photo application layer needs, implemented in infrastructure.

Pure Python: no Django, DRF or infrastructure imports belong here.
"""

from dataclasses import dataclass
from typing import BinaryIO, Protocol

from apps.catalog.services import (
    MediaRecord,
    NewMedia,
    ProductImageRecord,
    ProductRecord,
    VariantRecord,
)
from apps.photos.domain.submission import PhotoSubmission
from apps.shared.domain.store import StoreReference


@dataclass(frozen=True, slots=True)
class UploadedPhoto:
    """The private keys and dimensions an upload produced."""

    original_key: str
    preview_key: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class RenderedPhoto:
    """The public image one processing run produced, before the catalog stores it."""

    content: bytes
    width: int
    height: int
    mime_type: str
    extension: str
    metadata: dict


class MediaUploader(Protocol):
    """Normalize an upload and store it privately, scoped to one store."""

    def upload(self, store: StoreReference, content: bytes) -> UploadedPhoto:
        """Return the private original and preview keys for ``content``."""
        ...


class PhotoRenderer(Protocol):
    """Apply the submission's crop, straightening and light correction to its original."""

    def render(self, submission: PhotoSubmission, original: bytes) -> RenderedPhoto:
        """Return the final public image for ``submission``."""
        ...


class PhotoCatalog(Protocol):
    """The catalog service operations photo use cases need, scoped to one store."""

    def get_product(self, store: StoreReference, product_id: int) -> ProductRecord | None:
        """Return the product of ``store``, or None when another store owns it."""
        ...

    def get_variant(self, store: StoreReference, variant_id: int) -> VariantRecord | None:
        """Return the variant of ``store``, or None when another store owns it."""
        ...

    def get_media(self, store: StoreReference, media_id: int) -> MediaRecord | None:
        """Return the media of ``store``, or None when another store owns it."""
        ...

    def create_media(self, store: StoreReference, media: NewMedia) -> MediaRecord:
        """Return the store's Media for the content, creating it once."""
        ...

    def set_main_product_image(
        self,
        store: StoreReference,
        *,
        product_id: int,
        media_id: int,
        variant_id: int | None = None,
    ) -> ProductImageRecord:
        """Make the media the product's active main image, without duplicating the link."""
        ...


class PrivateMediaReader(Protocol):
    """Open a private original or preview for an authorized streaming response."""

    def open(self, store: StoreReference, key: str) -> BinaryIO:
        """Return a readable file for ``key``, or raise OSError when it is missing."""
        ...


class PhotoSubmissionRepository(Protocol):
    """Store photo submissions, always scoped to one store; nothing is ever deleted."""

    def get(self, store: StoreReference, submission_id: int) -> PhotoSubmission | None:
        """Return the submission of ``store``, or None when another store owns it."""
        ...

    def get_by_idempotency_key(
        self, store: StoreReference, created_by: int, key: str
    ) -> PhotoSubmission | None:
        """Return the creator's submission with ``key`` in ``store``, if any."""
        ...

    def add(self, submission: PhotoSubmission) -> PhotoSubmission:
        """Insert a new submission and return it with its id and timestamps."""
        ...

    def save(self, submission: PhotoSubmission) -> PhotoSubmission:
        """Persist an existing submission's changes and return it refreshed."""
        ...


class PhotoProcessingQueue(Protocol):
    """Schedule one submission for asynchronous processing, after its transaction commits."""

    def enqueue(self, store: StoreReference, submission_id: int) -> None:
        """Enqueue the processing task exactly once for a newly created submission."""
        ...
