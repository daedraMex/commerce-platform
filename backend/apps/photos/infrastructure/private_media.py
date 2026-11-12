"""Open private original and preview files for the authorized preview endpoint."""

from apps.photos.infrastructure.media_uploader import get_private_storage
from apps.shared.domain.store import StoreReference


class StoragePrivateMediaReader:
    """The PrivateMediaReader adapter over the configured private storage."""

    def open(self, store: StoreReference, key: str):
        return get_private_storage().open(key, "rb")
