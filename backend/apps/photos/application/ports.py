"""Ports the photo application layer needs, implemented in infrastructure.

Pure Python: no Django, DRF or infrastructure imports belong here.
"""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
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
class ProcessedPhoto:
    """The final product image one processing run produced."""

    content: bytes
    width: int
    height: int


class MediaUploader(Protocol):
    """Normalize an upload and store it privately, scoped to one store."""

    def upload(self, store: StoreReference, content: bytes) -> UploadedPhoto:
        """Return the private original and preview keys for ``content``."""
        ...

    def delete(self, store: StoreReference, key: str) -> None:
        """Remove one private file of ``store``; a missing file is harmless."""
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
        """Create or reuse the store's content-addressed Media and its renditions."""
        ...

    def product_images_for_media(
        self, store: StoreReference, media_id: int
    ) -> list[ProductImageRecord]:
        """Return the store's product links to one media, active or retired."""
        ...

    def product_images(self, store: StoreReference, product_id: int) -> list[ProductImageRecord]:
        """Return every link of a product of the store, active or retired."""
        ...

    def reorder_carousel(
        self,
        store: StoreReference,
        *,
        product_id: int,
        image_ids: list[int],
    ) -> list[ProductImageRecord]:
        """Renumber the carousel and move the main role to the first image."""
        ...

    def append_to_carousel(
        self,
        store: StoreReference,
        *,
        product_id: int,
        media_id: int,
        variant_id: int | None = None,
    ) -> ProductImageRecord:
        """Append the media to the product's carousel, or make it the cover when empty."""
        ...

    def remove_from_carousel(
        self,
        store: StoreReference,
        *,
        product_id: int,
        media_id: int,
    ) -> ProductImageRecord:
        """Deactivate the product's link to the media, promoting the next cover."""
        ...


class UnitOfWork(Protocol):
    """Run a block of work atomically, rolling every change in it back on failure."""

    def __call__(self) -> AbstractContextManager[None]: ...


class PhotoProcessingQueue(Protocol):
    """Enqueue one submission for asynchronous processing, always with its store."""

    def enqueue(self, store: StoreReference, submission_id: int) -> None:
        """Put the submission on the processing queue; the task receives the store id."""
        ...


class PhotoProcessor(Protocol):
    """Turn a private original into the final product image (crop, straighten, colour)."""

    def process(
        self,
        submission: PhotoSubmission,
        size: tuple[float, float] | None,
        original: bytes,
    ) -> ProcessedPhoto:
        """Return the encoded final image for one submission; raise a domain error to fail."""
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

    def get_for_update(self, store: StoreReference, submission_id: int) -> PhotoSubmission | None:
        """Return and lock the submission until the surrounding transaction ends."""
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

    def list_for_product(
        self,
        store: StoreReference,
        product_id: int,
        media_ids: list[int],
    ) -> list[PhotoSubmission]:
        """Return the store's live submissions targeting the product or producing its media."""
        ...

    def store_ids_with_stale_processing(self, updated_before: datetime) -> list[int]:
        """Return ids of stores with a stale processing or uploaded submission."""
        ...

    def list_stale_processing(
        self, store: StoreReference, updated_before: datetime
    ) -> list[PhotoSubmission]:
        """Return the store's stale processing or uploaded submissions."""
        ...
