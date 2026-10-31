from apps.accounts.services import has_store_permission
from apps.shared.domain.exceptions import PermissionDeniedError
from apps.shared.domain.store import StoreReference


class MembershipAuthorizer:
    """Authorize store actions by the role of the user's active membership in the store.

    Implements the Authorizer port. There is no bypass for superusers or ``is_staff`` (ADR-0019).
    """

    def require(self, user_id: int, store: StoreReference, permission: str) -> None:
        if not has_store_permission(user_id=user_id, store_id=store.id, permission=permission):
            raise PermissionDeniedError("You do not have permission to perform this action.")
