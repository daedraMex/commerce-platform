from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction

from apps.catalog.media import prepare_for_store
from apps.catalog.models import Category, Media, Product, ProductMedia, ProductVariant
from apps.catalog.repositories import DjangoCatalogRepository, DjangoMediaFiles
from apps.catalog.services import (
    CatalogService,
    NewMedia,
    ProductImageRole,
    StoreMismatch,
)
from apps.shared.domain.store import StoreReference
from apps.stores.models import Store
from config.dependencies import get_catalog_service
from tests.images import image_bytes

pytestmark = pytest.mark.django_db


@pytest.fixture
def media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.MEDIA_BASE_URL = "https://media.example.com"
    return settings.MEDIA_ROOT


def make_store(slug):
    return Store.objects.create(slug=slug, name=slug.title())


def make_product(store):
    category = Category.objects.create(
        store=store,
        name="Frazada",
        slug="frazada",
        sku_code="FRZ",
        shape=Category.Shape.RECTANGLE,
    )
    return Product.objects.create(store=store, category=category, name="Blanket", slug="blanket")


def make_media(store, *, content_hash):
    return Media.objects.create(
        store=store,
        storage_key=f"stores/{store.pk}/media/{content_hash}.jpg",
        content_hash=content_hash,
        mime_type="image/jpeg",
        width=800,
        height=800,
    )


def new_media(store, *, content_hash):
    return NewMedia(
        content=b"image-bytes",
        content_hash=content_hash,
        storage_key=f"stores/{store.pk}/media/{content_hash}.jpg",
        mime_type="image/jpeg",
        width=800,
        height=800,
        metadata={"format": "JPEG", "bytes": 11},
        alt_text="A blanket",
    )


def test_media_creation_is_deduplicated_by_content_hash(media_root):
    home = make_store("home")
    service = get_catalog_service()
    prepared = prepare_for_store(
        home,
        SimpleUploadedFile("photo.jpg", image_bytes("JPEG"), content_type="image/jpeg"),
    )
    draft = NewMedia(
        content=prepared.content,
        content_hash=prepared.content_hash,
        storage_key=prepared.storage_key,
        mime_type=prepared.mime_type,
        width=prepared.width,
        height=prepared.height,
        metadata=prepared.metadata,
        alt_text="A blanket",
    )

    first = service.create_media(StoreReference(id=home.pk, slug=home.slug), draft)
    second = service.create_media(StoreReference(id=home.pk, slug=home.slug), draft)

    assert first.id == second.id
    assert Media.objects.filter(store=home).count() == 1
    assert len(list(media_root.rglob("*.jpg"))) == 1


def test_a_product_cannot_link_media_of_another_store(media_root):
    home = make_store("home")
    anime = make_store("anime")
    product = make_product(home)
    foreign_media = make_media(anime, content_hash="foreign")

    with pytest.raises(StoreMismatch):
        get_catalog_service().create_product_image(
            StoreReference(id=home.pk, slug=home.slug),
            product_id=product.pk,
            media_id=foreign_media.pk,
        )

    assert not ProductMedia.objects.exists()


def test_setting_a_main_retires_the_old_one_and_preserves_both_positions(media_root):
    home = make_store("home")
    product = make_product(home)
    first = make_media(home, content_hash="first")
    second = make_media(home, content_hash="second")
    service = get_catalog_service()
    store = StoreReference(id=home.pk, slug=home.slug)

    gallery = service.upsert_product_image(
        store, product_id=product.pk, media_id=first.pk, role=ProductImageRole.GALLERY
    )
    old_main = service.set_main_product_image(store, product_id=product.pk, media_id=second.pk)
    promoted = service.set_main_product_image(store, product_id=product.pk, media_id=first.pk)

    old_main_row = ProductMedia.objects.get(pk=old_main.id)
    promoted_row = ProductMedia.objects.get(pk=promoted.id)
    assert promoted_row.pk == gallery.id
    assert promoted_row.role == ProductMedia.Role.MAIN
    assert promoted_row.is_active is True
    assert promoted_row.position == gallery.position
    assert old_main_row.is_active is False
    assert old_main_row.position == old_main.position
    assert (
        ProductMedia.objects.filter(
            product=product, role=ProductMedia.Role.MAIN, is_active=True
        ).count()
        == 1
    )


def test_upsert_reactivates_a_link_without_losing_its_position(media_root):
    home = make_store("home")
    product = make_product(home)
    media = make_media(home, content_hash="gallery")
    service = get_catalog_service()
    store = StoreReference(id=home.pk, slug=home.slug)

    link = service.upsert_product_image(
        store, product_id=product.pk, media_id=media.pk, role=ProductImageRole.GALLERY
    )
    service.deactivate_product_image(store, image_id=link.id)
    restored = service.upsert_product_image(
        store, product_id=product.pk, media_id=media.pk, role=ProductImageRole.GALLERY
    )

    assert restored.id == link.id
    assert restored.position == link.position
    assert ProductMedia.objects.get(pk=link.id).is_active is True


def test_product_and_variant_lookup_are_scoped_to_the_store(media_root):
    home = make_store("home")
    anime = make_store("anime")
    product = make_product(home)
    variant = ProductVariant.objects.create(
        product=product,
        option_values={},
        sku="FRZ-001",
        price=Decimal("199.00"),
        cost=Decimal("80.00"),
    )
    service = get_catalog_service()

    home_store = StoreReference(id=home.pk, slug=home.slug)
    anime_store = StoreReference(id=anime.pk, slug=anime.slug)

    assert service.get_product(home_store, product.pk).id == product.pk
    assert service.get_variant(home_store, variant.pk).id == variant.pk
    assert service.get_product(anime_store, product.pk) is None
    assert service.get_variant(anime_store, variant.pk) is None


class FailingAddRepository(DjangoCatalogRepository):
    def add_product_image(self, image):
        raise RuntimeError("cannot save the new main")


def test_a_failure_while_setting_the_new_main_leaves_the_old_main_active(media_root):
    home = make_store("home")
    product = make_product(home)
    old_media = make_media(home, content_hash="old-main")
    new_media = make_media(home, content_hash="new-main")
    store = StoreReference(id=home.pk, slug=home.slug)

    old_main = get_catalog_service().set_main_product_image(
        store, product_id=product.pk, media_id=old_media.pk
    )
    failing = CatalogService(
        repository=FailingAddRepository(),
        files=DjangoMediaFiles(),
        transaction=transaction.atomic,
    )

    with pytest.raises(RuntimeError):
        failing.set_main_product_image(store, product_id=product.pk, media_id=new_media.pk)

    assert ProductMedia.objects.get(pk=old_main.id).is_active is True
    assert not ProductMedia.objects.filter(product=product, media=new_media).exists()


def test_two_set_main_calls_in_turn_leave_exactly_one_active_main(media_root):
    home = make_store("home")
    product = make_product(home)
    first_media = make_media(home, content_hash="first-main")
    second_media = make_media(home, content_hash="second-main")
    service = get_catalog_service()
    store = StoreReference(id=home.pk, slug=home.slug)

    service.set_main_product_image(store, product_id=product.pk, media_id=first_media.pk)
    second = service.set_main_product_image(store, product_id=product.pk, media_id=second_media.pk)

    active_mains = ProductMedia.objects.filter(
        product=product, role=ProductMedia.Role.MAIN, is_active=True
    )
    assert active_mains.count() == 1
    assert active_mains.get().pk == second.id


def prepared_draft(store, *, color):
    prepared = prepare_for_store(
        store,
        SimpleUploadedFile(
            "photo.jpg", image_bytes("JPEG", color=color), content_type="image/jpeg"
        ),
    )
    return NewMedia(
        content=prepared.content,
        content_hash=prepared.content_hash,
        storage_key=prepared.storage_key,
        mime_type=prepared.mime_type,
        width=prepared.width,
        height=prepared.height,
        metadata=prepared.metadata,
        alt_text="A blanket",
    )


def test_create_media_reuses_the_media_a_concurrent_request_already_created(media_root):
    home = make_store("home")
    store = StoreReference(id=home.pk, slug=home.slug)
    repository = DjangoCatalogRepository()
    service = CatalogService(
        repository=repository,
        files=DjangoMediaFiles(),
        transaction=transaction.atomic,
    )
    draft = prepared_draft(home, color=(10, 20, 30))
    first = service.create_media(store, draft)

    original_lookup = repository.media_by_content_hash
    misses = {"remaining": 1}

    def racing_lookup(store_id, content_hash):
        if misses["remaining"]:
            misses["remaining"] -= 1
            return None
        return original_lookup(store_id, content_hash)

    repository.media_by_content_hash = racing_lookup

    with transaction.atomic():
        second = service.create_media(store, draft)
        after = service.create_media(store, prepared_draft(home, color=(40, 50, 60)))

    assert second.id == first.id
    assert after.id != first.id
    assert Media.objects.filter(store=home).count() == 2
