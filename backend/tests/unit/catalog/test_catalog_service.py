from contextlib import contextmanager

import pytest
from rest_framework import status

from apps.catalog.services import (
    CatalogService,
    CatalogServiceError,
    CategoryReference,
    InvalidImageOrder,
    MediaRecord,
    NewMedia,
    ProductImageConflict,
    ProductImageNotFound,
    ProductImageRecord,
    ProductImageRole,
    ProductRecord,
    StoreMismatch,
    VariantNotFound,
    VariantRecord,
)
from apps.shared.domain.exceptions import DomainError
from apps.shared.domain.store import StoreReference
from config.exceptions import _domain_error_status

HOME = StoreReference(id=1, slug="home")
ANIME = StoreReference(id=2, slug="anime")


class FakeCatalogRepository:
    def __init__(self, *, products=(), variants=(), media=(), images=()):
        self.products = {product.id: product for product in products}
        self.variants = {variant.id: variant for variant in variants}
        self.media = {item.id: item for item in media}
        self.images = {image.id: image for image in images}
        self.next_image_id = max(self.images, default=0) + 1
        self.locked_products = []

    def lock_product(self, store_id, product_id):
        self.locked_products.append((store_id, product_id))
        product = self.products.get(product_id)
        return product is not None and product.store_id == store_id

    def media_by_content_hash(self, store_id, content_hash):
        return next(
            (
                item
                for item in self.media.values()
                if item.store_id == store_id and item.content_hash == content_hash
            ),
            None,
        )

    def media_by_id(self, store_id, media_id):
        item = self.media.get(media_id)
        return item if item is not None and item.store_id == store_id else None

    def add_media(self, store_id, media):
        record = MediaRecord(
            id=max(self.media, default=0) + 1,
            store_id=store_id,
            storage_key=media.storage_key,
            content_hash=media.content_hash,
            mime_type=media.mime_type,
            alt_text=media.alt_text,
            width=media.width,
            height=media.height,
            metadata=media.metadata,
        )
        self.media[record.id] = record
        return record

    def get_product(self, store_id, product_id):
        product = self.products.get(product_id)
        return product if product is not None and product.store_id == store_id else None

    def get_variant(self, store_id, variant_id):
        variant = self.variants.get(variant_id)
        return variant if variant is not None and variant.store_id == store_id else None

    def get_product_image(self, image_id):
        return self.images.get(image_id)

    def find_product_image(self, product_id, media_id):
        return next(
            (
                image
                for image in self.images.values()
                if image.product_id == product_id and image.media_id == media_id
            ),
            None,
        )

    def product_images(self, product_id):
        return sorted(
            (image for image in self.images.values() if image.product_id == product_id),
            key=lambda image: (image.position, image.id),
        )

    def active_main_image(self, product_id):
        return next(
            (
                image
                for image in self.images.values()
                if image.product_id == product_id
                and image.role is ProductImageRole.MAIN
                and image.is_active
            ),
            None,
        )

    def active_product_images(self, product_id):
        return sorted(
            (
                image
                for image in self.images.values()
                if image.product_id == product_id and image.is_active
            ),
            key=lambda image: (image.position, image.id),
        )

    def add_product_image(self, image):
        position = image.position
        if position is None:
            position = (
                max(
                    (
                        sibling.position
                        for sibling in self.images.values()
                        if sibling.product_id == image.product_id
                    ),
                    default=0,
                )
                + 1
            )
        product = self.products[image.product_id]
        record = ProductImageRecord(
            id=self.next_image_id,
            store_id=product.store_id,
            product_id=image.product_id,
            media_id=image.media_id,
            variant_id=image.variant_id,
            role=image.role,
            position=position,
            is_active=True,
        )
        self.next_image_id += 1
        self.images[record.id] = record
        return record

    def save_product_image(self, image):
        self.images[image.id] = image
        return image


class FakeMediaFiles:
    def __init__(self):
        self.stored = []

    def store(self, media):
        self.stored.append(media)


class FakeUnitOfWork:
    def __init__(self):
        self.depth = 0
        self.entered = 0
        self.committed = 0
        self.rolled_back = 0

    @contextmanager
    def __call__(self):
        self.depth += 1
        self.entered += 1
        try:
            yield
        except Exception:
            self.rolled_back += 1
            raise
        else:
            if self.depth == 1:
                self.committed += 1
        finally:
            self.depth -= 1


def make_product(product_id=10, store=HOME, *, category_shape="rectangle"):
    return ProductRecord(
        id=product_id,
        store_id=store.id,
        name="Blanket",
        slug="blanket",
        category=CategoryReference(
            id=1,
            shape=category_shape,
            option_schema=(
                {
                    "code": "size",
                    "label": "Size",
                    "values": [
                        {
                            "code": "IND",
                            "label": "Individual",
                            "width_cm": 80,
                            "height_cm": 80,
                        }
                    ],
                },
            ),
        ),
    )


def make_variant(variant_id=20, product_id=10, store=HOME):
    return VariantRecord(
        id=variant_id,
        store_id=store.id,
        product_id=product_id,
        sku="FRZ-001-IND",
        option_values={"size": "IND"},
    )


def make_media(media_id=30, store=HOME, *, content_hash="hash-1"):
    return MediaRecord(
        id=media_id,
        store_id=store.id,
        storage_key=f"stores/{store.id}/media/{content_hash}.jpg",
        content_hash=content_hash,
        mime_type="image/jpeg",
        alt_text="",
        width=800,
        height=800,
        metadata={"format": "JPEG", "bytes": 10},
    )


def make_image(
    image_id=40,
    *,
    product_id=10,
    media_id=30,
    role=ProductImageRole.GALLERY,
    position=1,
    is_active=True,
    variant_id=None,
    store=HOME,
):
    return ProductImageRecord(
        id=image_id,
        store_id=store.id,
        product_id=product_id,
        media_id=media_id,
        variant_id=variant_id,
        role=role,
        position=position,
        is_active=is_active,
    )


def new_media(*, content_hash="hash-1"):
    return NewMedia(
        content=b"image-bytes",
        content_hash=content_hash,
        storage_key=f"stores/1/media/{content_hash}.jpg",
        mime_type="image/jpeg",
        width=800,
        height=800,
        metadata={"format": "JPEG", "bytes": 11},
        alt_text="A blanket",
    )


@pytest.fixture
def repository():
    return FakeCatalogRepository(
        products=[make_product()],
        variants=[make_variant()],
        media=[make_media()],
    )


@pytest.fixture
def files():
    return FakeMediaFiles()


@pytest.fixture
def transaction():
    return FakeUnitOfWork()


@pytest.fixture
def service(repository, files, transaction):
    return CatalogService(repository=repository, files=files, transaction=transaction)


def test_create_media_reuses_a_media_with_the_same_content_hash_without_storing_it(
    service, repository, files
):
    media = service.create_media(HOME, new_media(content_hash="hash-1"))

    assert media.id == 30
    assert files.stored == []


def test_create_media_stores_the_file_then_records_the_media(service, repository, files):
    media = service.create_media(HOME, new_media(content_hash="hash-new"))

    assert media.id == 31
    assert files.stored == [new_media(content_hash="hash-new")]
    assert repository.media[31] == media


def test_create_media_for_another_store_does_not_reuse_this_stores_media(service, files):
    media = service.create_media(ANIME, new_media(content_hash="hash-1"))

    assert media.store_id == ANIME.id
    assert len(files.stored) == 1


def test_create_product_image_rejects_a_product_of_another_store(service, repository):
    repository.products[10] = make_product(store=ANIME)

    with pytest.raises(StoreMismatch):
        service.create_product_image(HOME, product_id=10, media_id=30)

    assert repository.images == {}


def test_create_product_image_rejects_media_of_another_store(service, repository):
    repository.media[30] = make_media(store=ANIME)

    with pytest.raises(StoreMismatch):
        service.create_product_image(HOME, product_id=10, media_id=30)

    assert repository.images == {}


def test_create_product_image_rejects_a_variant_of_another_product(service, repository):
    repository.variants[20] = make_variant(product_id=99)

    with pytest.raises(VariantNotFound):
        service.create_product_image(HOME, product_id=10, media_id=30, variant_id=20)

    assert repository.images == {}


def test_create_product_image_refuses_a_second_link_for_the_same_media(service, repository):
    repository.images[40] = make_image()

    with pytest.raises(ProductImageConflict):
        service.create_product_image(HOME, product_id=10, media_id=30)

    assert len(repository.images) == 1


def test_create_main_image_retires_the_previous_main_and_keeps_its_position(service, repository):
    repository.media[31] = make_media(media_id=31, content_hash="hash-2")
    repository.images[40] = make_image(role=ProductImageRole.MAIN, position=1)

    created = service.create_product_image(
        HOME, product_id=10, media_id=31, role=ProductImageRole.MAIN
    )

    previous = repository.images[40]
    assert previous.is_active is False
    assert previous.position == 1
    assert created.role is ProductImageRole.MAIN
    assert created.is_active is True


def test_set_main_reactivates_an_existing_gallery_without_moving_it(service, repository):
    repository.media[31] = make_media(media_id=31, content_hash="hash-2")
    repository.images[40] = make_image(
        image_id=40, media_id=31, role=ProductImageRole.GALLERY, position=3, is_active=False
    )
    repository.images[41] = make_image(
        image_id=41, media_id=30, role=ProductImageRole.MAIN, position=1
    )

    main = service.set_main_product_image(HOME, product_id=10, media_id=31)

    assert main.id == 40
    assert main.role is ProductImageRole.MAIN
    assert main.is_active is True
    assert main.position == 3
    assert repository.images[41].is_active is False


def test_upsert_updates_a_link_without_losing_its_position(service, repository):
    repository.media[31] = make_media(media_id=31, content_hash="hash-2")
    repository.images[40] = make_image(
        image_id=40, media_id=31, role=ProductImageRole.GALLERY, position=4, is_active=False
    )

    image = service.upsert_product_image(
        HOME, product_id=10, media_id=31, role=ProductImageRole.MAIN
    )

    assert image.id == 40
    assert image.role is ProductImageRole.MAIN
    assert image.is_active is True
    assert image.position == 4


def test_append_to_an_empty_carousel_makes_the_media_the_cover(service, repository):
    image = service.append_to_carousel(HOME, product_id=10, media_id=30)

    assert image.role is ProductImageRole.MAIN
    assert image.position == 1
    assert image.is_active is True


def test_append_to_a_non_empty_carousel_adds_a_gallery_image_at_the_end(service, repository):
    repository.media[31] = make_media(media_id=31, content_hash="hash-2")
    repository.images[40] = make_image(role=ProductImageRole.MAIN, position=1)

    image = service.append_to_carousel(HOME, product_id=10, media_id=31)

    assert image.role is ProductImageRole.GALLERY
    assert image.position == 2
    assert repository.images[40].role is ProductImageRole.MAIN
    assert repository.images[40].is_active is True


def test_append_reactivates_a_retired_link_at_the_end_without_duplicating_it(service, repository):
    repository.media[31] = make_media(media_id=31, content_hash="hash-2")
    repository.images[40] = make_image(
        image_id=40,
        media_id=31,
        role=ProductImageRole.GALLERY,
        position=2,
        is_active=False,
    )
    repository.images[41] = make_image(
        image_id=41, media_id=30, role=ProductImageRole.MAIN, position=1
    )

    image = service.append_to_carousel(HOME, product_id=10, media_id=31)

    assert image.id == 40
    assert image.is_active is True
    assert image.role is ProductImageRole.GALLERY
    assert image.position == 2
    assert len(repository.images) == 2


def test_append_returns_an_existing_active_link_unchanged(service, repository):
    repository.images[40] = make_image(role=ProductImageRole.MAIN, position=1)

    image = service.append_to_carousel(HOME, product_id=10, media_id=30)

    assert image.id == 40
    assert image.position == 1
    assert len(repository.images) == 1


def test_remove_the_cover_promotes_the_next_image_by_position(service, repository):
    repository.media[31] = make_media(media_id=31, content_hash="hash-2")
    repository.images[40] = make_image(
        image_id=40, media_id=30, role=ProductImageRole.MAIN, position=1
    )
    repository.images[41] = make_image(
        image_id=41, media_id=31, role=ProductImageRole.GALLERY, position=2
    )

    removed = service.remove_from_carousel(HOME, product_id=10, media_id=30)

    assert removed.is_active is False
    assert removed.role is ProductImageRole.GALLERY
    assert repository.images[41].role is ProductImageRole.MAIN
    assert repository.images[41].is_active is True


def test_remove_a_gallery_image_keeps_the_cover(service, repository):
    repository.media[31] = make_media(media_id=31, content_hash="hash-2")
    repository.images[40] = make_image(
        image_id=40, media_id=30, role=ProductImageRole.MAIN, position=1
    )
    repository.images[41] = make_image(
        image_id=41, media_id=31, role=ProductImageRole.GALLERY, position=2
    )

    removed = service.remove_from_carousel(HOME, product_id=10, media_id=31)

    assert removed.is_active is False
    assert repository.images[40].role is ProductImageRole.MAIN
    assert repository.images[40].is_active is True


def test_remove_rejects_a_media_that_is_not_linked(service):
    with pytest.raises(ProductImageNotFound):
        service.remove_from_carousel(HOME, product_id=10, media_id=99)


def test_append_runs_in_a_transaction_and_locks_the_product(service, repository, transaction):
    service.append_to_carousel(HOME, product_id=10, media_id=30)

    assert transaction.entered == 1
    assert transaction.committed == 1
    assert repository.locked_products == [(HOME.id, 10)]


def test_remove_runs_in_a_transaction_and_locks_the_product(service, repository, transaction):
    repository.images[40] = make_image()

    service.remove_from_carousel(HOME, product_id=10, media_id=30)

    assert transaction.entered == 1
    assert transaction.committed == 1
    assert repository.locked_products == [(HOME.id, 10)]


def test_deactivate_and_reactivate_preserve_the_position(service, repository):
    repository.images[40] = make_image(position=2)

    retired = service.deactivate_product_image(HOME, image_id=40)
    restored = service.reactivate_product_image(HOME, image_id=40)

    assert retired.is_active is False
    assert retired.position == 2
    assert restored.is_active is True
    assert restored.position == 2


def test_deactivate_rejects_a_link_of_another_store(service, repository):
    repository.products[10] = make_product(store=ANIME)
    repository.images[40] = make_image(store=ANIME)

    with pytest.raises(StoreMismatch):
        service.deactivate_product_image(HOME, image_id=40)

    assert repository.images[40].is_active is True


def test_reactivate_rejects_a_missing_link(service):
    with pytest.raises(ProductImageNotFound):
        service.reactivate_product_image(HOME, image_id=999)


def test_lookup_for_another_store_returns_none(service, repository):
    repository.products[10] = make_product(store=ANIME)
    repository.variants[20] = make_variant(store=ANIME)
    repository.media[30] = make_media(store=ANIME)

    assert service.get_product(HOME, product_id=10) is None
    assert service.get_variant(HOME, variant_id=20) is None
    assert service.get_media(HOME, media_id=30) is None


def test_lookup_returns_the_product_with_its_category_schema(service):
    product = service.get_product(HOME, product_id=10)
    variant = service.get_variant(HOME, variant_id=20)
    media = service.get_media(HOME, media_id=30)

    assert product.category.shape == "rectangle"
    assert product.category.option_schema[0]["code"] == "size"
    assert variant.option_values == {"size": "IND"}
    assert media.content_hash == "hash-1"


def test_create_product_image_runs_in_a_transaction_and_locks_the_product(
    service, repository, transaction
):
    service.create_product_image(HOME, product_id=10, media_id=30)

    assert transaction.entered == 1
    assert transaction.committed == 1
    assert repository.locked_products == [(HOME.id, 10)]


def test_deactivate_runs_in_a_transaction_and_locks_the_product(service, repository, transaction):
    repository.images[40] = make_image()

    service.deactivate_product_image(HOME, image_id=40)

    assert transaction.entered == 1
    assert transaction.committed == 1
    assert repository.locked_products == [(HOME.id, 10)]


def test_reactivate_runs_in_a_transaction_and_locks_the_product(service, repository, transaction):
    repository.images[40] = make_image(is_active=False)

    service.reactivate_product_image(HOME, image_id=40)

    assert transaction.entered == 1
    assert transaction.committed == 1
    assert repository.locked_products == [(HOME.id, 10)]


def test_upsert_runs_in_a_transaction_and_locks_the_product(service, repository, transaction):
    service.upsert_product_image(HOME, product_id=10, media_id=30)

    assert transaction.entered == 1
    assert transaction.committed == 1
    assert repository.locked_products == [(HOME.id, 10)]


def test_set_main_runs_in_one_transaction_and_locks_the_product(service, repository, transaction):
    service.set_main_product_image(HOME, product_id=10, media_id=30)

    assert transaction.entered == 1
    assert transaction.committed == 1
    assert repository.locked_products == [(HOME.id, 10)]


def test_write_commands_roll_back_the_transaction_when_the_product_is_foreign(
    service, repository, transaction
):
    repository.products[10] = make_product(store=ANIME)

    with pytest.raises(StoreMismatch):
        service.create_product_image(HOME, product_id=10, media_id=30)

    assert transaction.rolled_back == 1
    assert transaction.committed == 0


@pytest.mark.parametrize(
    ("error_class", "code", "status_code"),
    [
        (CatalogServiceError, "catalog_service_error", None),
        (StoreMismatch, "catalog_store_mismatch", status.HTTP_404_NOT_FOUND),
        (ProductImageConflict, "catalog_product_image_conflict", status.HTTP_409_CONFLICT),
        (ProductImageNotFound, "catalog_product_image_not_found", status.HTTP_404_NOT_FOUND),
        (VariantNotFound, "catalog_variant_not_found", status.HTTP_404_NOT_FOUND),
    ],
)
def test_catalog_service_errors_are_domain_errors_with_stable_codes(error_class, code, status_code):
    error = error_class("boom")

    assert isinstance(error, DomainError)
    assert error.code == code
    assert error.message == str(error) == "boom"
    assert _domain_error_status(error) == status_code


def test_reorder_renumbers_positions_and_moves_the_main_role(service, repository):
    repository.media[31] = make_media(media_id=31, content_hash="hash-2")
    repository.media[32] = make_media(media_id=32, content_hash="hash-3")
    repository.images[40] = make_image(
        image_id=40, media_id=30, role=ProductImageRole.MAIN, position=1
    )
    repository.images[41] = make_image(
        image_id=41, media_id=31, role=ProductImageRole.GALLERY, position=2
    )
    repository.images[42] = make_image(
        image_id=42, media_id=32, role=ProductImageRole.GALLERY, position=3
    )

    reordered = service.reorder_carousel(HOME, product_id=10, image_ids=[42, 40, 41])

    assert [image.id for image in reordered] == [42, 40, 41]
    assert [repository.images[image_id].position for image_id in (42, 40, 41)] == [1, 2, 3]
    assert repository.images[42].role is ProductImageRole.MAIN
    assert repository.images[40].role is ProductImageRole.GALLERY
    assert repository.images[41].role is ProductImageRole.GALLERY


def test_reorder_allows_an_empty_carousel(service, repository):
    assert service.reorder_carousel(HOME, product_id=10, image_ids=[]) == []
    assert repository.images == {}


@pytest.mark.parametrize(
    "image_ids",
    [
        [40],
        [40, 40, 41],
        [40, 41, 99],
        [40, 41, 42],
    ],
    ids=["omits", "repeats", "adds", "inactive"],
)
def test_reorder_rejects_a_list_that_is_not_the_exact_active_set(service, repository, image_ids):
    repository.media[31] = make_media(media_id=31, content_hash="hash-2")
    repository.images[40] = make_image(
        image_id=40, media_id=30, role=ProductImageRole.MAIN, position=1
    )
    repository.images[41] = make_image(
        image_id=41, media_id=31, role=ProductImageRole.GALLERY, position=2
    )
    repository.images[42] = make_image(
        image_id=42, media_id=31, role=ProductImageRole.GALLERY, position=3, is_active=False
    )

    with pytest.raises(InvalidImageOrder):
        service.reorder_carousel(HOME, product_id=10, image_ids=image_ids)

    assert repository.images[40].position == 1
    assert repository.images[40].role is ProductImageRole.MAIN


def test_reorder_rejects_an_image_of_another_product_or_store(service, repository):
    repository.products[11] = make_product(product_id=11)
    repository.media[31] = make_media(media_id=31, content_hash="hash-2")
    repository.images[40] = make_image(
        image_id=40, media_id=30, role=ProductImageRole.MAIN, position=1
    )
    repository.images[41] = make_image(
        image_id=41, product_id=11, media_id=31, role=ProductImageRole.MAIN, position=1
    )

    with pytest.raises(InvalidImageOrder):
        service.reorder_carousel(HOME, product_id=10, image_ids=[40, 41])


def test_reorder_runs_in_a_transaction_and_locks_the_product(service, repository, transaction):
    repository.images[40] = make_image(position=1)

    service.reorder_carousel(HOME, product_id=10, image_ids=[40])

    assert transaction.entered == 1
    assert transaction.committed == 1
    assert repository.locked_products == [(HOME.id, 10)]
