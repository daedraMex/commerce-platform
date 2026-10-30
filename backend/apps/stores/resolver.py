from apps.shared.domain.exceptions import StoreHeaderInvalidError, StoreNotFoundError
from apps.shared.domain.store import StoreReference, is_valid_store_slug
from apps.stores.models import Store


class DatabaseStoreResolver:
    """Resolve an X-Store slug to an active store; the slug is never normalized."""

    def resolve(self, slug: str) -> StoreReference:
        if not is_valid_store_slug(slug):
            raise StoreHeaderInvalidError("The X-Store header is not a valid store slug.")

        store = Store.objects.filter(slug=slug, is_active=True).only("id", "slug").first()
        if store is None:
            raise StoreNotFoundError("No active store matches the X-Store header.")
        return StoreReference(id=store.id, slug=store.slug)
