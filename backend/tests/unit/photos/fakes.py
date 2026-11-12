"""Fakes for photo use-case tests; they never touch storage or a database."""

from dataclasses import dataclass, field

from apps.photos.application.ports import UploadedPhoto
from apps.shared.domain.store import StoreReference


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
