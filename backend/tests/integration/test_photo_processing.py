from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from apps.catalog.media import rendition_key
from apps.catalog.models import (
    Category,
    Design,
    Media,
    Product,
    ProductMedia,
    ProductVariant,
    Supplier,
)
from apps.catalog.repositories import DjangoCatalogRepository, DjangoMediaFiles
from apps.catalog.services import CatalogService
from apps.photos.application.process_photo import ProcessPhotoSubmission
from apps.photos.application.sweep_stale_processing import SweepStaleProcessing
from apps.photos.domain.pipeline import PIPELINE_VERSION
from apps.photos.domain.submission import SubmissionStatus
from apps.photos.infrastructure.media_uploader import get_private_storage
from apps.photos.infrastructure.private_media import StoragePrivateMediaReader
from apps.photos.infrastructure.processor import PillowPhotoProcessor
from apps.photos.infrastructure.repository import DjangoPhotoSubmissionRepository
from apps.photos.models import PhotoSubmission
from apps.shared.domain.exceptions import NotFoundError
from apps.shared.domain.store import StoreReference
from apps.stores.models import Store
from tests.images import image_bytes

pytestmark = pytest.mark.django_db

CORNERS = [
    {"x": 0.1, "y": 0.1},
    {"x": 0.9, "y": 0.1},
    {"x": 0.9, "y": 0.9},
    {"x": 0.1, "y": 0.9},
]
CROP = {"x": 40, "y": 40, "width": 440, "height": 620}


@pytest.fixture
def media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.MEDIA_BASE_URL = "https://media.example.com"
    return settings.MEDIA_ROOT


@pytest.fixture
def private_storage(settings, tmp_path):
    settings.STORAGES = {
        **settings.STORAGES,
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": tmp_path / "private"},
        },
    }
    return tmp_path / "private"


def make_store(slug="home"):
    return Store.objects.create(slug=slug, name=slug.title())


def make_user(email="staff@example.com"):
    return get_user_model().objects.create_user(email=email)


def make_product(store, *, with_size=False):
    supplier = Supplier.objects.create(store=store, name="Beka")
    design = Design.objects.create(
        store=store,
        supplier=supplier,
        name="Frazada",
        supplier_design_name=f"DESIGN {Design.objects.count()}",
    )
    option_schema = []
    if with_size:
        option_schema = [
            {
                "code": "size",
                "label": "Size",
                "values": [
                    {"code": "SM", "label": "Small", "width_cm": 60, "height_cm": 80},
                ],
            },
        ]
    category = Category.objects.create(
        store=store,
        name="Frazada",
        slug=f"frazada-{Category.objects.count()}",
        sku_code="FRZ",
        shape=Category.Shape.RECTANGLE,
        option_schema=option_schema,
    )
    product = Product.objects.create(
        store=store,
        category=category,
        design=design,
        name="Frazada",
        slug=f"frazada-{Product.objects.count()}",
        attributes={},
    )
    variant = ProductVariant.objects.create(
        product=product,
        option_values={"size": "SM"} if with_size else {},
        price=Decimal("499.00"),
        cost=Decimal("200.00"),
    )
    return product, variant


def catalog_service():
    return CatalogService(
        repository=DjangoCatalogRepository(),
        files=DjangoMediaFiles(),
        transaction=transaction.atomic,
    )


def process_photo():
    return ProcessPhotoSubmission(
        repository=DjangoPhotoSubmissionRepository(),
        catalog=catalog_service(),
        processor=PillowPhotoProcessor(),
        reader=StoragePrivateMediaReader(),
    )


def write_original(store, *, key="original.jpg", size=(600, 800)):
    storage_key = f"stores/{store.id}/photos/originals/{key}"
    get_private_storage().save(
        storage_key,
        ContentFile(image_bytes("JPEG", size=size), name="original.jpg"),
    )
    return storage_key


def make_submission(
    store,
    user,
    *,
    key,
    kind,
    product=None,
    variant=None,
    original_key,
    corners=None,
    crop=None,
    status=PhotoSubmission.Status.UPLOADED,
    attempts=0,
    discarded_at=None,
):
    return PhotoSubmission.objects.create(
        store=store,
        created_by=user,
        kind=kind,
        target_product=product if kind != PhotoSubmission.Kind.GROUP else None,
        photographed_variant=variant,
        idempotency_key=key,
        request_fingerprint="a" * 64,
        status=status,
        original_key=original_key,
        preview_key=f"stores/{store.id}/photos/previews/{key}.jpg",
        corners=corners,
        crop=crop,
        attempts=attempts,
        discarded_at=discarded_at,
    )


def rendition_path(media_root, storage_key, width):
    return media_root / rendition_key(storage_key, width=width, version=1)


def assert_renditions(media_root, media):
    thumbnail = rendition_path(media_root, media.storage_key, 320)
    medium = rendition_path(media_root, media.storage_key, 800)
    assert thumbnail.is_file()
    assert medium.is_file()
    assert thumbnail.read_bytes()[:4] == b"RIFF"
    assert thumbnail.read_bytes()[8:12] == b"WEBP"
    assert medium.read_bytes()[:4] == b"RIFF"
    assert medium.read_bytes()[8:12] == b"WEBP"


def test_processing_a_rectangle_photo_creates_media_and_renditions(media_root, private_storage):
    store = make_store()
    user = make_user()
    product, variant = make_product(store, with_size=True)
    original = write_original(store)
    submission = make_submission(
        store,
        user,
        key="rect",
        kind=PhotoSubmission.Kind.RECTANGLE,
        product=product,
        variant=variant,
        original_key=original,
        corners=CORNERS,
    )
    reference = StoreReference(id=store.id, slug=store.slug)

    saved = process_photo()(reference, submission.pk)

    assert saved.status is SubmissionStatus.READY
    assert saved.attempts == 1
    assert saved.pipeline_version == PIPELINE_VERSION
    assert saved.result_media_id is not None

    media = Media.objects.get(pk=saved.result_media_id)
    assert media.store_id == store.id
    assert media.mime_type == "image/jpeg"
    assert media.content_hash
    assert media.storage_key == f"stores/{store.id}/media/{media.content_hash}.jpg"
    assert_renditions(media_root, media)
    assert not ProductMedia.objects.filter(media=media).exists()

    submission.refresh_from_db()
    assert submission.status == PhotoSubmission.Status.READY
    assert submission.pipeline_version == PIPELINE_VERSION


def test_processing_a_contour_photo_creates_media_and_renditions(media_root, private_storage):
    store = make_store()
    user = make_user()
    product, variant = make_product(store, with_size=True)
    original = write_original(store, key="contour.jpg", size=(500, 700))
    submission = make_submission(
        store,
        user,
        key="contour",
        kind=PhotoSubmission.Kind.CONTOUR,
        product=product,
        variant=variant,
        original_key=original,
        crop=CROP,
    )
    reference = StoreReference(id=store.id, slug=store.slug)

    saved = process_photo()(reference, submission.pk)

    assert saved.status is SubmissionStatus.READY
    media = Media.objects.get(pk=saved.result_media_id)
    assert_renditions(media_root, media)


def test_processing_a_group_photo_creates_media_and_renditions(media_root, private_storage):
    store = make_store()
    user = make_user()
    original = write_original(store, key="group.jpg", size=(600, 800))
    submission = make_submission(
        store,
        user,
        key="group",
        kind=PhotoSubmission.Kind.GROUP,
        original_key=original,
    )
    reference = StoreReference(id=store.id, slug=store.slug)

    saved = process_photo()(reference, submission.pk)

    assert saved.status is SubmissionStatus.READY
    media = Media.objects.get(pk=saved.result_media_id)
    assert media.store_id == store.id
    assert_renditions(media_root, media)


def test_a_discarded_submission_is_a_deterministic_failure(private_storage):
    store = make_store()
    user = make_user()
    submission = make_submission(
        store,
        user,
        key="discarded",
        kind=PhotoSubmission.Kind.GROUP,
        original_key=f"stores/{store.id}/photos/originals/discarded.jpg",
    )
    from django.utils import timezone

    submission.discarded_at = timezone.now()
    submission.save(update_fields=["discarded_at"])
    reference = StoreReference(id=store.id, slug=store.slug)

    saved = process_photo()(reference, submission.pk)

    assert saved.status is SubmissionStatus.FAILED
    assert saved.failure_code == "photo_submission_discarded"
    assert saved.result_media_id is None
    assert Media.objects.filter(store=store).count() == 0


def test_a_missing_original_is_a_deterministic_failure(private_storage):
    store = make_store()
    user = make_user()
    submission = make_submission(
        store,
        user,
        key="missing",
        kind=PhotoSubmission.Kind.GROUP,
        original_key=f"stores/{store.id}/photos/originals/missing.jpg",
    )
    reference = StoreReference(id=store.id, slug=store.slug)

    saved = process_photo()(reference, submission.pk)

    assert saved.status is SubmissionStatus.FAILED
    assert saved.failure_code == "photo_original_missing"
    assert saved.result_media_id is None
    assert Media.objects.filter(store=store).count() == 0


def test_a_processing_submission_keeps_its_existing_attempt(media_root, private_storage):
    store = make_store()
    user = make_user()
    original = write_original(store, key="retry.jpg")
    submission = make_submission(
        store,
        user,
        key="retry",
        kind=PhotoSubmission.Kind.GROUP,
        original_key=original,
        status=PhotoSubmission.Status.PROCESSING,
        attempts=2,
    )
    reference = StoreReference(id=store.id, slug=store.slug)

    saved = process_photo()(reference, submission.pk)

    assert saved.status is SubmissionStatus.READY
    assert saved.attempts == 2


def test_a_worker_that_finishes_after_the_sweep_leaves_the_submission_failed(
    media_root, private_storage
):
    store = make_store()
    user = make_user()
    original = write_original(store, key="swept.jpg")
    submission = make_submission(
        store,
        user,
        key="swept",
        kind=PhotoSubmission.Kind.GROUP,
        original_key=original,
        status=PhotoSubmission.Status.PROCESSING,
        attempts=1,
    )
    reference = StoreReference(id=store.id, slug=store.slug)

    SweepStaleProcessing(
        repository=DjangoPhotoSubmissionRepository(),
        stale_after=timedelta(minutes=15),
    )(timezone.now() + timedelta(hours=1))

    saved = process_photo()(reference, submission.pk)

    assert saved.status is SubmissionStatus.FAILED
    assert saved.failure_code == "photo_processing_unavailable"
    assert saved.result_media_id is None
    assert Media.objects.filter(store=store).count() == 0


def test_a_worker_that_finishes_after_the_sweep_failed_an_uploaded_submission_leaves_it_failed(
    media_root, private_storage
):
    store = make_store()
    user = make_user()
    original = write_original(store, key="swept-uploaded.jpg")
    submission = make_submission(
        store,
        user,
        key="swept-uploaded",
        kind=PhotoSubmission.Kind.GROUP,
        original_key=original,
        status=PhotoSubmission.Status.UPLOADED,
        attempts=0,
    )
    reference = StoreReference(id=store.id, slug=store.slug)

    SweepStaleProcessing(
        repository=DjangoPhotoSubmissionRepository(),
        stale_after=timedelta(minutes=15),
    )(timezone.now() + timedelta(hours=1))

    saved = process_photo()(reference, submission.pk)

    assert saved.status is SubmissionStatus.FAILED
    assert saved.failure_code == "photo_processing_unavailable"
    assert saved.attempts == 1
    assert saved.result_media_id is None
    assert Media.objects.filter(store=store).count() == 0


def test_reprocessing_a_ready_submission_does_not_duplicate_media(media_root, private_storage):
    store = make_store()
    user = make_user()
    original = write_original(store, key="twice.jpg")
    submission = make_submission(
        store,
        user,
        key="twice",
        kind=PhotoSubmission.Kind.GROUP,
        original_key=original,
    )
    reference = StoreReference(id=store.id, slug=store.slug)

    first = process_photo()(reference, submission.pk)
    second = process_photo()(reference, submission.pk)

    assert first.result_media_id == second.result_media_id
    assert Media.objects.filter(store=store).count() == 1
    assert ProductMedia.objects.filter(product__store=store).count() == 0


def test_processing_never_writes_another_stores_media(media_root, private_storage):
    home = make_store("home")
    anime = make_store("anime")
    user = make_user()
    original = write_original(home, key="isolation.jpg")
    submission = make_submission(
        home,
        user,
        key="isolation",
        kind=PhotoSubmission.Kind.GROUP,
        original_key=original,
    )
    home_reference = StoreReference(id=home.id, slug=home.slug)
    anime_reference = StoreReference(id=anime.id, slug=anime.slug)

    saved = process_photo()(home_reference, submission.pk)

    assert saved.status is SubmissionStatus.READY
    assert Media.objects.filter(store=home).count() == 1
    assert Media.objects.filter(store=anime).count() == 0
    assert ProductMedia.objects.filter(product__store=anime).count() == 0

    with pytest.raises(NotFoundError):
        process_photo()(anime_reference, submission.pk)

    assert Media.objects.filter(store=anime).count() == 0
