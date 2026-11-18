"""Open private original and preview files for the authorized preview endpoint."""

from apps.photos.infrastructure.media_uploader import get_private_storage
from apps.shared.domain.store import StoreReference


class StoragePrivateMediaReader:
    """The PrivateMediaReader adapter over the configured private storage."""

    def open(self, store: StoreReference, key: str):
        if not self._belongs_to(store, key):
            raise FileNotFoundError("The private file is not available.")
        return get_private_storage().open(key, "rb")

    @staticmethod
    def _belongs_to(store: StoreReference, key) -> bool:
        """Fail closed for anything outside the store's own private area."""
        if not isinstance(key, str) or not key or key.startswith("/") or "\\" in key:
            return False
        if ".." in key.split("/"):
            return False
        return key.startswith(f"stores/{store.id}/")
