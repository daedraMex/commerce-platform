from rest_framework.permissions import BasePermission

from apps.shared.domain.permissions import MANAGE_CATALOG
from apps.shared.domain.store import StoreReference
from config.dependencies import get_authorizer


class CanManageCatalog(BasePermission):
    """Allow users whose role holds ``catalog.manage`` in the request's store.

    The decision goes through the Authorizer port, so views and use cases share the same rule
    and there is no bypass for superusers or ``is_staff`` (ADR-0019, ADR-0021).
    """

    message = "You do not have permission to manage the catalog."

    def has_permission(self, request, view):
        get_authorizer().require(
            request.user.id,
            StoreReference(id=request.store.id, slug=request.store.slug),
            MANAGE_CATALOG,
        )
        return True
