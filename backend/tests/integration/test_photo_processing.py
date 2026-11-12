from decimal import Decimal

import pytest
from celery.exceptions import Retry
from django.db import transaction

from apps.catalog.models import (
    Category,
    Design,
    Media,
    Product,
    ProductMedia,
    ProductVariant,
    Supplier,
)
from apps.catalog.repositories import DjangoCatalogRepository
from apps.catalog.services import CatalogService
from apps.photos.application.ports import RenderedPhoto
from apps.photos.domain.errors import InvalidImage
from apps.photos.domain.pipeline import PIPELINE_VERSION
from apps.photos.infrastructure.renderer import PillowPhotoRenderer
from apps.photos.interfaces.tasks import process_photo_submission, retry_countdown
from apps.photos.models import PhotoSubmission
from apps.stores.models import Store
from config import dependencies
from tests.images import image_bytes
from tests.unit.photos.fakes import FakePrivateMediaReader, FakeRenderer

pytestmark = pytest.mark.django_db

ORIGINAL_KEY = "stores/{store_id}/photos/originals/test.jpg"
CORNERS = [
    {"x": 0.1, "y": 0.1},
    {"x": 0.9, "y": 0.1},
    {"x": 0.9, "y": 0.9},
    {"x": 0.1, "y": 0.9},
]
CONTOUR_CROP = {"x": 10, "y": 10, "width": 100, "height": 80}


class RecordingMediaFiles:
    """Fake public storage: remember each NewMedia instead of writing an object."""

    def __init__(self):
        self.stored = []

    def store(self, media):
        self.stored.append(media)


@pytest.fixture
def overrides():
    yield dependencies
    dependencies.clear_overrides()


@pytest.fixture
def files():
    return RecordingMediaFiles()


@pytest.fixture
def catalog_service(files):
    return CatalogService(
        repository=DjangoCatalogRepository(),
        files=files,
        transaction=transaction.atomic,
    )


def make_store(slug="home"):
    return Store.objects.create(slug=slug, name=slug.title())


def make_user(email="staff@example.com"):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(email=email)


def make_product(store, *, name="Blanket"):
    supplier = Supplier.objects.create(store=store, name="Beka")
    design = Design.objects.create(
        store=store,
        supplier=supplier,
        name=name,
        supplier_design_name=f"DESIGN {Design.objects.count()}",
    )
    category = Category.objects.create(
        store=store,
        name="Frazada",
        slug=f"frazada-{Category.objects.count()}",
        sku_code=f"FRZ{Category.objects.count()}",
        shape=Category.Shape.RECTANGLE,
    )
    product = Product.objects.create(
        store=store,
        category=category,
        design=design,
        name=name,
        slug=f"blanket-{Product.objects.count()}",
    )
    variant = ProductVariant.objects.create(
        product=product,
        option_values={},
        price=Decimal("499.00"),
        cost=Decimal("200.00"),
    )
    return product, variant


def make_submission(store, user, *, kind, product=None, variant=None, **overrides):
    values = {
        "store": store,
        "created_by": user,
        "kind": kind,
        "idempotency_key": f"key-{PhotoSubmission.objects.count()}",
        "request_fingerprint": "a" * 64,
        "original_key": ORIGINAL_KEY.format(store_id=store.id),
    }
    values.update(overrides)
    if product is not None:
        values["target_product"] = product
    if variant is not None:
        values["photographed_variant"] = variant
    return PhotoSubmission.objects.create(**values)


def install_task_dependencies(
    *,
    overrides,
    catalog_service,
    reader,
    renderer,
):
    overrides.override(dependencies.get_catalog_service, lambda: catalog_service)
    overrides.override(dependencies.get_private_media_reader, lambda: reader)
    overrides.override(dependencies.get_photo_renderer, lambda: renderer)


def run_task(store, submission):
    return process_photo_submission.delay(store.id, submission.id).get()


@pytest.mark.parametrize("kind", ["rectangle", "contour", "group"])
def test_the_task_processes_every_mode_and_sets_statuses(overrides, catalog_service, files, kind):
    home = make_store()
    user = make_user()
    product = variant = None
    crop = corners = None
    if kind == "rectangle":
        product, variant = make_product(home)
        corners = CORNERS
    elif kind == "contour":
        product, variant = make_product(home)
        crop = CONTOUR_CROP
    submission = make_submission(
        home,
        user,
        kind=kind,
        product=product,
        variant=variant,
        crop=crop,
        corners=corners,
    )
    reader = FakePrivateMediaReader(
        files={(home.id, submission.original_key): image_bytes(size=(200, 100))}
    )
    install_task_dependencies(
        overrides=overrides,
        catalog_service=catalog_service,
        reader=reader,
        renderer=PillowPhotoRenderer(),
    )

    run_task(home, submission)

    submission.refresh_from_db()
    assert submission.status == PhotoSubmission.Status.READY
    assert submission.pipeline_version == PIPELINE_VERSION
    assert submission.attempts == 1
    assert submission.failure_code == ""
    assert submission.result_media is not None
    assert submission.result_media.store_id == home.id
    assert len(files.stored) == 1

    if product is None:
        assert not ProductMedia.objects.filter(media=submission.result_media).exists()
    else:
        link = ProductMedia.objects.get(media=submission.result_media)
        assert link.product_id == product.id
        assert link.role == ProductMedia.Role.MAIN
        assert link.variant_id == variant.id


def test_a_deterministic_failure_sets_a_readable_code_without_retrying(overrides, catalog_service):
    home = make_store()
    user = make_user()
    submission = make_submission(home, user, kind="group")
    reader = FakePrivateMediaReader(files={(home.id, submission.original_key): b"anything"})
    renderer = FakeRenderer(error=InvalidImage("The file is not an image this service can read."))
    install_task_dependencies(
        overrides=overrides,
        catalog_service=catalog_service,
        reader=reader,
        renderer=renderer,
    )

    run_task(home, submission)

    submission.refresh_from_db()
    assert submission.status == PhotoSubmission.Status.FAILED
    assert submission.failure_code == "invalid_image"
    assert "not an image" in submission.failure_message
    assert submission.attempts == 1
    assert len(renderer.calls) == 1
    assert not Media.objects.exists()


def test_a_transient_failure_retries_and_ends_ready(overrides, catalog_service):
    class FailOnceRenderer(FakeRenderer):
        def render(self, submission, original):
            self.calls.append((submission, original))
            if len(self.calls) == 1:
                raise OSError("the private storage is down")
            return self.rendered or RenderedPhoto(
                content=b"rendered-photo",
                width=800,
                height=1000,
                mime_type="image/jpeg",
                extension="jpg",
                metadata={"format": "JPEG", "bytes": 14},
            )

    home = make_store()
    user = make_user()
    submission = make_submission(home, user, kind="group")
    reader = FakePrivateMediaReader(files={(home.id, submission.original_key): b"bytes"})
    renderer = FailOnceRenderer()
    install_task_dependencies(
        overrides=overrides,
        catalog_service=catalog_service,
        reader=reader,
        renderer=renderer,
    )

    with pytest.raises(Retry) as retry:
        process_photo_submission.delay(home.id, submission.id)

    submission.refresh_from_db()
    assert retry.value.when == 30
    assert submission.status == PhotoSubmission.Status.FAILED
    assert submission.failure_code == "processing_unavailable"
    assert submission.attempts == 1

    run_task(home, submission)

    submission.refresh_from_db()
    assert len(renderer.calls) == 2
    assert submission.status == PhotoSubmission.Status.READY
    assert submission.attempts == 2
    assert submission.failure_code == ""
    assert Media.objects.filter(store=home).count() == 1


def test_the_retry_backoff_grows_exponentially():
    assert retry_countdown(0) == 30
    assert retry_countdown(1) == 60
    assert retry_countdown(2) == 120


def test_one_store_never_receives_another_stores_media_or_links(overrides, catalog_service, files):
    home = make_store("home")
    anime = make_store("anime")
    user = make_user()
    home_product, home_variant = make_product(home, name="Home blanket")
    anime_product, anime_variant = make_product(anime, name="Anime blanket")
    home_submission = make_submission(
        home,
        user,
        kind="rectangle",
        product=home_product,
        variant=home_variant,
        corners=CORNERS,
    )
    anime_submission = make_submission(
        anime,
        user,
        kind="rectangle",
        product=anime_product,
        variant=anime_variant,
        corners=CORNERS,
    )
    original = image_bytes(size=(200, 100))
    reader = FakePrivateMediaReader(
        files={
            (home.id, home_submission.original_key): original,
            (anime.id, anime_submission.original_key): original,
        }
    )
    install_task_dependencies(
        overrides=overrides,
        catalog_service=catalog_service,
        reader=reader,
        renderer=PillowPhotoRenderer(),
    )

    run_task(home, home_submission)
    run_task(anime, anime_submission)

    home_submission.refresh_from_db()
    anime_submission.refresh_from_db()
    home_media = home_submission.result_media
    anime_media = anime_submission.result_media

    assert home_media.store_id == home.id
    assert anime_media.store_id == anime.id
    assert home_media.content_hash == anime_media.content_hash
    assert home_media.storage_key.startswith(f"stores/{home.id}/")
    assert anime_media.storage_key.startswith(f"stores/{anime.id}/")
    assert Media.objects.filter(store=home).count() == 1
    assert Media.objects.filter(store=anime).count() == 1
    home_link = ProductMedia.objects.get(media=home_media)
    anime_link = ProductMedia.objects.get(media=anime_media)
    assert home_link.product_id == home_product.id
    assert anime_link.product_id == anime_product.id
    assert not ProductMedia.objects.filter(product__store=home, media__store=anime).exists()
    assert not ProductMedia.objects.filter(product__store=anime, media__store=home).exists()
