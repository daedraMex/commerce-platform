from datetime import UTC, datetime

import pytest
from django.contrib.auth import get_user_model
from django.db import transaction

from apps.catalog.models import Category, Design, Media, Product, ProductMedia, Supplier
from apps.catalog.repositories import DjangoCatalogRepository, DjangoMediaFiles
from apps.catalog.services import CatalogService
from apps.photos.application.apply_photo import ApplyPhoto
from apps.photos.infrastructure.repository import DjangoPhotoSubmissionRepository
from apps.photos.models import PhotoSubmission
from apps.shared.domain.store import StoreReference
from apps.stores.models import Store
from tests.unit.photos.fakes import FakeAuthorizer

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def make_store(slug="home"):
    return Store.objects.create(slug=slug, name=slug.title())


def make_user(email="staff@example.com"):
    return get_user_model().objects.create_user(email=email)


def make_product(store):
    supplier = Supplier.objects.create(store=store, name="Beka")
    design = Design.objects.create(
        store=store,
        supplier=supplier,
        name="Jack Todos",
        supplier_design_name="JACK TODOS 1",
    )
    category = Category.objects.create(
        store=store,
        name="Frazada",
        slug="frazada",
        sku_code="FRZ",
        shape=Category.Shape.RECTANGLE,
    )
    return Product.objects.create(
        store=store,
        category=category,
        design=design,
        name="Frazada Jack Todos",
        slug="frazada-jack-todos",
        attributes={},
    )


def make_media(store, *, content_hash, storage_key):
    return Media.objects.create(
        store=store,
        storage_key=storage_key,
        content_hash=content_hash,
        mime_type="image/jpeg",
        width=800,
        height=1000,
    )


def make_ready_submission(store, user, product, media, *, key):
    return PhotoSubmission.objects.create(
        store=store,
        created_by=user,
        kind=PhotoSubmission.Kind.RECTANGLE,
        target_product=product,
        idempotency_key=key,
        request_fingerprint="a" * 64,
        status=PhotoSubmission.Status.READY,
        result_media=media,
        attempts=1,
        pipeline_version="2026-11-11.2",
        original_key=f"stores/{store.id}/photos/originals/{key}.jpg",
        preview_key=f"stores/{store.id}/photos/previews/{key}.jpg",
    )


def apply_photo():
    return ApplyPhoto(
        repository=DjangoPhotoSubmissionRepository(),
        catalog=CatalogService(
            repository=DjangoCatalogRepository(),
            files=DjangoMediaFiles(),
            transaction=transaction.atomic,
        ),
        authorizer=FakeAuthorizer(),
    )


def test_apply_deactivates_the_old_main_but_keeps_every_row_and_result():
    store = make_store()
    user = make_user()
    product = make_product(store)
    reference = StoreReference(id=store.id, slug=store.slug)
    old_media = make_media(store, content_hash="old", storage_key="stores/1/media/old.jpg")
    new_media = make_media(store, content_hash="new", storage_key="stores/1/media/new.jpg")
    first = make_ready_submission(store, user, product, old_media, key="first")
    second = make_ready_submission(store, user, product, new_media, key="second")
    use_case = apply_photo()

    use_case(reference, user_id=user.id, submission_id=first.pk, now=NOW)
    use_case(reference, user_id=user.id, submission_id=second.pk, now=NOW)

    first.refresh_from_db()
    second.refresh_from_db()
    old_link = ProductMedia.objects.get(product=product, media=old_media)
    new_link = ProductMedia.objects.get(product=product, media=new_media)

    assert first.applied_at == NOW
    assert second.applied_at == NOW
    assert PhotoSubmission.objects.filter(store=store).count() == 2
    assert Media.objects.filter(store=store).count() == 2
    assert ProductMedia.objects.filter(product=product).count() == 2
    assert old_link.is_active is False
    assert old_link.role == ProductMedia.Role.MAIN
    assert new_link.is_active is True
    assert new_link.role == ProductMedia.Role.MAIN
    assert (
        ProductMedia.objects.filter(
            product=product, role=ProductMedia.Role.MAIN, is_active=True
        ).count()
        == 1
    )
    assert first.result_media_id == old_media.id
    assert second.result_media_id == new_media.id
