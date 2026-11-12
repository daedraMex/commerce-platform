"""Ports the photo application layer needs, implemented in infrastructure.

Pure Python: no Django, DRF or infrastructure imports belong here.
"""

from dataclasses import dataclass
from typing import Protocol

from apps.photos.domain.submission import PhotoSubmission
from apps.shared.domain.store import StoreReference


@dataclass(frozen=True, slots=True)
class UploadedPhoto:
    """The private keys and dimensions an upload produced."""

    original_key: str
    preview_key: str
    width: int
    height: int


class MediaUploader(Protocol):
    """Normalize an upload and store it privately, scoped to one store."""

    def upload(self, store: StoreReference, content: bytes) -> UploadedPhoto:
        """Return the private original and preview keys for ``content``."""
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
