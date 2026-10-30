from apps.shared.domain.exceptions import StoreHeaderMissingError
from config.dependencies import get_store_resolver


class StoreScopedMixin:
    """Opt a view into resolving request.store after authentication and permissions."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)

        slug = getattr(request, "store_slug", None)
        if slug is None:
            raise StoreHeaderMissingError("The X-Store header is required.")

        request.store = get_store_resolver().resolve(slug)
