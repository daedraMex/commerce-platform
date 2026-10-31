from rest_framework.permissions import BasePermission

from apps.accounts.services import get_active_membership


class IsStoreStaff(BasePermission):
    """Allow users with an active membership in request.store, with any role.

    There is no bypass for superusers or ``is_staff`` (ADR-0019). The membership it finds is
    kept on ``request.store_membership`` so the view reads the same row it was authorized by.
    """

    message = "You are not staff of this store."

    def has_permission(self, request, view):
        request.store_membership = get_active_membership(
            user=request.user, store_id=request.store.id
        )
        return request.store_membership is not None
