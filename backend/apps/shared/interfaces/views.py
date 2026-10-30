from apps.shared.domain.exceptions import StoreHeaderMissingError
from apps.shared.domain.ports import StoreResolver
from apps.shared.infrastructure.store import SlugValidatingStoreResolver


class StoreScopedMixin:
    """Opt a view into resolving request.store after authentication and permissions."""

    resolver: StoreResolver = SlugValidatingStoreResolver()

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)

        slug = getattr(request, "store_slug", None)
        if slug is None:
            raise StoreHeaderMissingError("The X-Store header is required.")

        request.store = self.resolver.resolve(slug)
