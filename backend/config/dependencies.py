"""Composition root: the one place that knows which implementation backs each port (ADR-0022).

Provider functions build their port on each call and import its implementation inside the
function, so nothing is built or loaded at import time and importing shared never loads a module.
"""

from collections.abc import Callable

from apps.shared.domain.ports import StoreResolver

_overrides: dict[Callable, Callable] = {}


def override(provider: Callable, factory: Callable) -> None:
    """Make ``provider`` return ``factory()`` until clear_overrides(); for tests."""
    _overrides[provider] = factory


def clear_overrides() -> None:
    _overrides.clear()


def get_store_resolver() -> StoreResolver:
    if get_store_resolver in _overrides:
        return _overrides[get_store_resolver]()

    from apps.stores.resolver import DatabaseStoreResolver

    return DatabaseStoreResolver()
