from rest_framework.permissions import BasePermission

from apps.shared.domain.exceptions import StoreHeaderMissingError
from apps.shared.domain.ports import StoreResolver
from apps.shared.infrastructure.store import SlugValidatingStoreResolver


class RequireStore(BasePermission):
    """Opt a store-scoped view into resolving request.store from X-Store."""

    resolver: StoreResolver = SlugValidatingStoreResolver()

    def has_permission(self, request, view):
        slug = getattr(request, "store_slug", None)
        if slug is None:
            raise StoreHeaderMissingError("The X-Store header is required.")

        request.store = self.resolver.resolve(slug)
        return True
