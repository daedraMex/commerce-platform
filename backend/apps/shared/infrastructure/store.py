from apps.shared.domain.exceptions import StoreHeaderInvalidError
from apps.shared.domain.store import StoreReference, is_valid_store_slug


class SlugValidatingStoreResolver:
    """Phase 2 resolver: it validates the slug but cannot look a store up yet."""

    def resolve(self, slug: str) -> StoreReference:
        if not is_valid_store_slug(slug):
            raise StoreHeaderInvalidError("The X-Store header is not a valid store slug.")
        return StoreReference(slug=slug)
