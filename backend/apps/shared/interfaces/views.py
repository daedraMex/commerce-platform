from apps.shared.domain.exceptions import PermissionDeniedError, StoreHeaderMissingError
from config.dependencies import get_store_resolver

STORE_PERMISSION_DENIED_DETAIL = "You do not have permission to perform this action in this store."


class StoreScopedMixin:
    """Opt a view into resolving request.store and checking store-level permissions.

    The order is fixed (ADR-0019): authentication and global permissions (401), then the
    store (400), then the view's ``store_permission_classes`` (403).
    """

    store_permission_classes = ()

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)

        slug = getattr(request, "store_slug", None)
        if slug is None:
            raise StoreHeaderMissingError("The X-Store header is required.")

        request.store = get_store_resolver().resolve(slug)
        self.check_store_permissions(request)

    def check_store_permissions(self, request):
        for permission_class in self.store_permission_classes:
            permission = permission_class()
            if not permission.has_permission(request, self):
                message = getattr(permission, "message", None) or STORE_PERMISSION_DENIED_DETAIL
                raise PermissionDeniedError(message)
