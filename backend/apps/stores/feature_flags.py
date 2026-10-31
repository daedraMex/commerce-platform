from apps.shared.domain.store import StoreReference
from apps.stores.models import StoreFeatureFlag


class DatabaseFeatureFlags:
    """Read per-store flags from the database on every call, with no caching (ADR-0013)."""

    def is_enabled(self, store: StoreReference, code: str) -> bool:
        return StoreFeatureFlag.objects.filter(store_id=store.id, code=code, enabled=True).exists()
