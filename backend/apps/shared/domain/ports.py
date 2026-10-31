"""Ports shared by every module.

Pure Python: no Django, DRF or infrastructure imports belong here.
"""

from typing import Protocol

from apps.shared.domain.store import StoreReference


class StoreResolver(Protocol):
    """Turn a raw X-Store value into the store a request is scoped to."""

    def resolve(self, slug: str) -> StoreReference: ...


class Authorizer(Protocol):
    """Decide whether a user may perform an action in a store (ADR-0019, ADR-0021)."""

    def require(self, user_id: int, store: StoreReference, permission: str) -> None:
        """Pass if the user holds ``permission`` in ``store``; else raise PermissionDeniedError."""
        ...
