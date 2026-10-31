from rest_framework.permissions import BasePermission

from apps.accounts.services import get_active_membership


class IsStoreStaff(BasePermission):
    """Allow users with an active membership in request.store, with any role.

    There is no bypass for superusers or ``is_staff`` (ADR-0019).
    """

    message = "You are not staff of this store."

    def has_permission(self, request, view):
        return get_active_membership(user=request.user, store_id=request.store.id) is not None
