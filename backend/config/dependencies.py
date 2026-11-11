"""Composition root: the one place that knows which implementation backs each port (ADR-0022).

Provider functions build their port on each call and import its implementation inside the
function, so nothing is built or loaded at import time and importing shared never loads a module.
"""

from collections.abc import Callable

from apps.catalog.services import CatalogService
from apps.photos.application.ports import PhotoSubmissionRepository
from apps.shared.domain.ports import Authorizer, FeatureFlags, StoreResolver

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


def get_authorizer() -> Authorizer:
    if get_authorizer in _overrides:
        return _overrides[get_authorizer]()

    from apps.accounts.authorizer import MembershipAuthorizer

    return MembershipAuthorizer()


def get_feature_flags() -> FeatureFlags:
    if get_feature_flags in _overrides:
        return _overrides[get_feature_flags]()

    from apps.stores.feature_flags import DatabaseFeatureFlags

    return DatabaseFeatureFlags()


def get_photo_submission_repository() -> PhotoSubmissionRepository:
    if get_photo_submission_repository in _overrides:
        return _overrides[get_photo_submission_repository]()

    from apps.photos.infrastructure.repository import DjangoPhotoSubmissionRepository

    return DjangoPhotoSubmissionRepository()


def get_catalog_service() -> CatalogService:
    if get_catalog_service in _overrides:
        return _overrides[get_catalog_service]()

    from django.db import transaction

    from apps.catalog.repositories import DjangoCatalogRepository, DjangoMediaFiles

    return CatalogService(
        repository=DjangoCatalogRepository(),
        files=DjangoMediaFiles(),
        transaction=transaction.atomic,
    )
