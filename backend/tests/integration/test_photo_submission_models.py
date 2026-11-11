from datetime import UTC, datetime
from decimal import Decimal
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.catalog.models import Category, Design, Media, Product, ProductVariant, Supplier
from apps.photos.domain.submission import PhotoSubmission as PhotoSubmissionEntity
from apps.photos.domain.submission import SubmissionKind, SubmissionStatus
from apps.photos.infrastructure.repository import DjangoPhotoSubmissionRepository
from apps.photos.models import PhotoSubmission
from apps.shared.domain.store import StoreReference
from apps.stores.models import Store

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


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
        supplier_design_name=f"JACK TODOS {Design.objects.count()}",
    )
    category = Category.objects.create(
        store=store,
        name="Frazada",
        slug=f"frazada-{Category.objects.count()}",
        sku_code="FRZ",
        shape=Category.Shape.RECTANGLE,
    )
    return Product.objects.create(
        store=store,
        category=category,
        design=design,
        name="Frazada Jack Todos",
        slug=f"frazada-jack-todos-{Product.objects.count()}",
    )


def make_variant(product):
    return ProductVariant.objects.create(
        product=product,
        option_values={},
        price=Decimal("199.00"),
        cost=Decimal("80.00"),
    )


def make_media(store, key="stores/1/media/result.jpg", content_hash="result"):
    return Media.objects.create(
        store=store,
        storage_key=key,
        content_hash=content_hash,
        mime_type="image/jpeg",
        width=800,
        height=1000,
    )


def submission_fields(store, user, **overrides):
    values = {
        "store": store,
        "created_by": user,
        "kind": PhotoSubmission.Kind.GROUP,
        "idempotency_key": "key-1",
        "request_fingerprint": "fingerprint-1",
    }
    values.update(overrides)
    return values


def make_submission(store, user, **overrides):
    return PhotoSubmission.objects.create(**submission_fields(store, user, **overrides))


def test_an_idempotency_key_is_unique_per_store_and_creator():
    home = make_store("home")
    user = make_user()
    make_submission(home, user)

    with pytest.raises(IntegrityError), transaction.atomic():
        make_submission(home, user)


def test_the_same_key_is_allowed_for_another_store_or_creator():
    home = make_store("home")
    anime = make_store("anime")
    user = make_user()
    other_user = make_user("other@example.com")
    make_submission(home, user)

    make_submission(anime, user)
    make_submission(home, other_user)

    assert PhotoSubmission.objects.count() == 3


@pytest.mark.parametrize(
    "status",
    [
        PhotoSubmission.Status.UPLOADED,
        PhotoSubmission.Status.PROCESSING,
        PhotoSubmission.Status.READY,
        PhotoSubmission.Status.FAILED,
    ],
)
def test_the_database_accepts_the_four_statuses(status):
    store = make_store("home")
    user = make_user()

    submission = make_submission(store, user, status=status, idempotency_key=f"key-{status}")

    assert submission.status == status


def test_the_database_rejects_any_other_status():
    store = make_store("home")
    user = make_user()

    with pytest.raises(IntegrityError), transaction.atomic():
        make_submission(store, user, status="applied")


def test_the_database_rejects_a_group_photo_with_a_target_product():
    store = make_store("home")
    user = make_user()
    product = make_product(store)

    with pytest.raises(IntegrityError), transaction.atomic():
        make_submission(
            store,
            user,
            kind=PhotoSubmission.Kind.GROUP,
            target_product=product,
        )


@pytest.mark.parametrize(
    "kind",
    [PhotoSubmission.Kind.RECTANGLE, PhotoSubmission.Kind.CONTOUR],
)
def test_the_database_rejects_an_individual_photo_without_a_target_product(kind):
    store = make_store("home")
    user = make_user()

    with pytest.raises(IntegrityError), transaction.atomic():
        make_submission(store, user, kind=kind, target_product=None)


def test_the_database_rejects_a_submission_that_is_applied_and_discarded():
    store = make_store("home")
    user = make_user()

    with pytest.raises(IntegrityError), transaction.atomic():
        make_submission(store, user, applied_at=NOW, applied_by=user, discarded_at=NOW)


def test_the_repository_round_trips_a_submission():
    store = make_store("home")
    user = make_user()
    product = make_product(store)
    variant = make_variant(product)
    media = make_media(store)
    repository = DjangoPhotoSubmissionRepository()
    reference = StoreReference(id=store.id, slug=store.slug)
    entity = PhotoSubmissionEntity(
        store_id=store.id,
        created_by_id=user.id,
        kind=SubmissionKind.RECTANGLE,
        target_product_id=product.id,
        photographed_variant_id=variant.id,
        original_key="stores/1/photo-originals/original.jpg",
        preview_key="stores/1/photo-previews/preview.jpg",
        corners=[{"x": 1, "y": 2}],
        crop={"x": 0, "y": 0, "width": 800, "height": 1000},
        light_correction=False,
        idempotency_key="key-1",
        request_fingerprint="fingerprint-1",
    )

    added = repository.add(entity)
    loaded = repository.get(reference, added.id)

    assert added.id is not None
    assert loaded == added
    assert loaded.created_at is not None
    assert loaded.updated_at is not None
    assert loaded.kind is SubmissionKind.RECTANGLE
    assert loaded.status is SubmissionStatus.UPLOADED
    assert loaded.target_product_id == product.id
    assert loaded.photographed_variant_id == variant.id
    assert loaded.original_key == entity.original_key
    assert loaded.preview_key == entity.preview_key
    assert loaded.corners == entity.corners
    assert loaded.crop == entity.crop
    assert loaded.light_correction is False

    loaded.start_processing()
    loaded.mark_ready(result_media_id=media.id, pipeline_version="v1")
    saved = repository.save(loaded)

    assert saved.status is SubmissionStatus.READY
    assert saved.attempts == 1
    assert saved.result_media_id == media.id
    assert saved.pipeline_version == "v1"
    assert repository.get(reference, saved.id) == saved
    assert repository.get_by_idempotency_key(reference, user.id, "key-1") == saved


def test_a_submission_is_never_found_through_another_store():
    home = make_store("home")
    anime = make_store("anime")
    user = make_user()
    home_reference = StoreReference(id=home.id, slug=home.slug)
    anime_reference = StoreReference(id=anime.id, slug=anime.slug)
    repository = DjangoPhotoSubmissionRepository()

    home_submission = repository.add(
        PhotoSubmissionEntity(
            store_id=home.id,
            created_by_id=user.id,
            kind=SubmissionKind.GROUP,
            idempotency_key="shared-key",
            request_fingerprint="home-payload",
        )
    )
    anime_submission = repository.add(
        PhotoSubmissionEntity(
            store_id=anime.id,
            created_by_id=user.id,
            kind=SubmissionKind.GROUP,
            idempotency_key="shared-key",
            request_fingerprint="anime-payload",
        )
    )

    assert home_submission.id != anime_submission.id
    assert repository.get(home_reference, home_submission.id) == home_submission
    assert repository.get(anime_reference, home_submission.id) is None
    assert repository.get_by_idempotency_key(home_reference, user.id, "shared-key") == (
        home_submission
    )
    assert repository.get_by_idempotency_key(anime_reference, user.id, "shared-key") == (
        anime_submission
    )
    assert PhotoSubmission.objects.filter(store=home).get().pk == home_submission.id


def test_the_photo_submission_changes_need_no_extra_migration():
    output = StringIO()

    call_command("makemigrations", "photos", "--check", "--dry-run", stdout=output)

    assert "No changes detected" in output.getvalue()


def test_the_photo_submission_admin_is_read_only(admin_client_by_email):
    store = make_store("home")
    user = make_user()
    submission = make_submission(store, user)
    prefix = "admin:photos_photosubmission"

    changelist = admin_client_by_email.get(reverse(f"{prefix}_changelist"))
    add = admin_client_by_email.get(reverse(f"{prefix}_add"))
    change = admin_client_by_email.post(
        reverse(f"{prefix}_change", args=[submission.pk]),
        submission_fields(store, user),
    )
    delete = admin_client_by_email.post(
        reverse(f"{prefix}_delete", args=[submission.pk]),
        {"post": "yes"},
    )

    assert changelist.status_code == 200
    assert add.status_code == 403
    assert change.status_code == 403
    assert delete.status_code == 403
    assert PhotoSubmission.objects.filter(pk=submission.pk).exists()
