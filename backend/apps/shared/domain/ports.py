"""Ports shared by every module.

Pure Python: no Django, DRF or infrastructure imports belong here.
"""

from typing import Protocol

from apps.shared.domain.store import StoreReference


class StoreResolver(Protocol):
    """Turn a raw X-Store value into the store a request is scoped to."""

    def resolve(self, slug: str) -> StoreReference: ...
