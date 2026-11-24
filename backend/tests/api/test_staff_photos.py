import json
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.services import grant_membership
from apps.catalog.models import (
    Category,
    Design,
    Media,
    Product,
    ProductMedia,
    ProductVariant,
    Supplier,
)
from apps.photos.infrastructure import processing_queue
from apps.photos.infrastructure.processing_queue import PROCESS_PHOTO_TASK
from apps.photos.models import PhotoSubmission
from apps.shared.domain.exceptions import PermissionDeniedError
from apps.stores.models import Store
from tests.api.helpers import assert_problem_details
from tests.images import image_bytes

pytestmark = pytest.mark.django_db

UPLOAD_URL = "/api/v1/staff/photos/"
DETAIL_URL = "/api/v1/staff/photos/{id}/"
PREVIEW_URL = "/api/v1/staff/photos/{id}/preview/"
ACTION_URLS = {
    "apply": "/api/v1/staff/photos/{id}/apply/",
    "links": "/api/v1/staff/photos/{id}/links/",
    "remove": "/api/v1/staff/photos/{id}/remove/",
    "redo": "/api/v1/staff/photos/{id}/redo/",
    "retry": "/api/v1/staff/photos/{id}/retry/",
    "discard": "/api/v1/staff/photos/{id}/discard/",
}

CORNERS = [
    {"x": 0.1, "y": 0.1},
    {"x": 0.9, "y": 0.1},
    {"x": 0.9, "y": 0.9},
    {"x": 0.1, "y": 0.9},
]
CROP = {"x": 1, "y": 1, "width": 8, "height": 10}


@pytest.fixture
def home():
    return Store.objects.create(slug="home", name="Home")


@pytest.fixture
def anime():
    return Store.objects.create(slug="anime", name="Anime")


@pytest.fixture
def user():
    return get_user_model().objects.create_user(email="ana@example.com", password="s3cret-pass")


@pytest.fixture
def private_storage(tmp_path, settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": tmp_path},
        },
    }
    return tmp_path


@pytest.fixture
def media_base_url(settings):
    settings.MEDIA_BASE_URL = "https://media.example.com"
    return settings.MEDIA_BASE_URL


def bearer(user):
    return f"Bearer {AccessToken.for_user(user)}"


def make_product(store, *, name="Frazada Térmica", slug=None):
    supplier = Supplier.objects.filter(store=store).first() or Supplier.objects.create(
        store=store, name="Beka"
    )
    design = Design.objects.create(
        store=store,
        supplier=supplier,
        name=name,
        supplier_design_name=f"DESIGN {Design.objects.count()}",
    )
    category = Category.objects.filter(store=store).first() or Category.objects.create(
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
        name=name,
        slug=slug or f"product-{Product.objects.count()}",
        attributes={},
    )


def make_variant(product):
    return ProductVariant.objects.create(
        product=product,
        option_values={},
        price=Decimal("499.00"),
        cost=Decimal("200.00"),
    )


def upload(client, user, *, store="home", filename="photo.jpg", content=None, **fields):
    content = content if content is not None else image_bytes(size=(12, 10))
    data = {
        "file": SimpleUploadedFile(filename, content, content_type="image/jpeg"),
        "kind": fields.pop("kind", "group"),
        **fields,
    }
    return client.post(
        UPLOAD_URL,
        data,
        HTTP_AUTHORIZATION=bearer(user),
        HTTP_X_STORE=store,
        HTTP_IDEMPOTENCY_KEY=fields.pop("idempotency_key", "key-1"),
    )


def get_detail(client, user, submission_id, store="home"):
    return client.get(
        DETAIL_URL.format(id=submission_id),
        HTTP_AUTHORIZATION=bearer(user),
        HTTP_X_STORE=store,
    )


def get_preview(client, user, submission_id, store="home"):
    return client.get(
        PREVIEW_URL.format(id=submission_id),
        HTTP_AUTHORIZATION=bearer(user),
        HTTP_X_STORE=store,
    )


def test_upload_creates_an_uploaded_submission(client, home, user, private_storage):
    grant_membership(user=user, store=home, role_name="content_editor")
    product = make_product(home)
    variant = make_variant(product)

    response = upload(
        client,
        user,
        kind="rectangle",
        target_product=product.id,
        photographed_variant=variant.id,
        corners=json.dumps(CORNERS),
        crop=json.dumps(CROP),
        light_correction="false",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "rectangle"
    assert body["status"] == "uploaded"
    assert body["failure_code"] == ""
    assert body["failure_message"] == ""
    assert body["preview_url"] == PREVIEW_URL.format(id=body["id"])
    assert body["result"] is None
    assert body["target_product_id"] == product.id
    assert body["photographed_variant_id"] == variant.id
    assert body["corners"] == CORNERS
    assert body["crop"] == CROP
    assert body["light_correction"] is False
    assert body["pipeline_version"] == ""
    assert body["attempts"] == 0

    submission = PhotoSubmission.objects.get(pk=body["id"])
    assert submission.store_id == home.id
    assert submission.original_key.startswith(f"stores/{home.id}/photos/originals/")
    assert submission.preview_key.startswith(f"stores/{home.id}/photos/previews/")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("corners", [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}]),
        ("corners", [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.9}, {}]),
        (
            "corners",
            [
                {"x": "0.1", "y": 0.1},
                {"x": 0.9, "y": 0.1},
                {"x": 0.9, "y": 0.9},
                {"x": 0.1, "y": 0.9},
            ],
        ),
        ("corners", {point["y"]: point for point in CORNERS}),
        ("crop", {"x": 1, "y": 1, "width": 8}),
        ("crop", {"x": 1, "y": 1, "width": "8", "height": 10}),
        ("crop", [1, 1, 8, 10]),
    ],
)
def test_upload_validates_the_shape_of_corners_and_crop(
    client, home, user, private_storage, field, value
):
    grant_membership(user=user, store=home, role_name="content_editor")

    response = upload(client, user, **{field: json.dumps(value)})

    body = assert_problem_details(response, status=400, code="validation_error")
    assert body["errors"][0]["field"].startswith(field)
    assert PhotoSubmission.objects.filter(store=home).count() == 0
    assert [path for path in private_storage.rglob("*") if path.is_file()] == []


def test_upload_enqueues_processing_after_the_transaction_commits(
    client, home, user, private_storage, monkeypatch, django_capture_on_commit_callbacks
):
    grant_membership(user=user, store=home, role_name="content_editor")
    sent = []
    monkeypatch.setattr(
        processing_queue.app,
        "send_task",
        lambda name, kwargs: sent.append((name, kwargs)),
    )

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        response = upload(client, user)

    assert response.status_code == 201
    submission_id = response.json()["id"]
    assert len(callbacks) == 1
    assert sent == [(PROCESS_PHOTO_TASK, {"store_id": home.id, "submission_id": submission_id})]


def test_double_tap_returns_one_submission(client, home, user, private_storage):
    grant_membership(user=user, store=home, role_name="content_editor")

    first = upload(client, user)
    second = upload(client, user)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert PhotoSubmission.objects.filter(store=home).count() == 1


def test_the_same_key_with_a_different_payload_returns_409(client, home, user, private_storage):
    grant_membership(user=user, store=home, role_name="content_editor")
    upload(client, user, content=image_bytes(color=(10, 20, 30)))

    response = upload(client, user, content=image_bytes(color=(90, 80, 70)))

    assert_problem_details(response, status=409, code="idempotency_conflict")
    assert PhotoSubmission.objects.filter(store=home).count() == 1


def test_upload_requires_the_idempotency_key(client, home, user, private_storage):
    grant_membership(user=user, store=home, role_name="content_editor")

    response = client.post(
        UPLOAD_URL,
        {"file": SimpleUploadedFile("photo.jpg", image_bytes()), "kind": "group"},
        HTTP_AUTHORIZATION=bearer(user),
        HTTP_X_STORE="home",
    )

    body = assert_problem_details(response, status=400, code="validation_error")
    assert body["errors"][0]["field"] == "Idempotency-Key"
    assert [path for path in private_storage.rglob("*") if path.is_file()] == []


def test_upload_rejects_an_overlong_idempotency_key(client, home, user, private_storage):
    grant_membership(user=user, store=home, role_name="content_editor")

    response = client.post(
        UPLOAD_URL,
        {"file": SimpleUploadedFile("photo.jpg", image_bytes()), "kind": "group"},
        HTTP_AUTHORIZATION=bearer(user),
        HTTP_X_STORE="home",
        HTTP_IDEMPOTENCY_KEY="k" * 256,
    )

    body = assert_problem_details(response, status=400, code="validation_error")
    assert body["errors"][0]["field"] == "Idempotency-Key"
    assert [path for path in private_storage.rglob("*") if path.is_file()] == []


def test_upload_rejects_a_file_larger_than_25_mb(client, home, user, private_storage):
    grant_membership(user=user, store=home, role_name="content_editor")

    response = upload(client, user, content=b"x" * (25 * 1024 * 1024 + 1))

    assert_problem_details(response, status=400, code="too_large")
    assert PhotoSubmission.objects.filter(store=home).count() == 0
    assert [path for path in private_storage.rglob("*") if path.is_file()] == []


def test_upload_requires_authentication(client, home):
    response = client.post(UPLOAD_URL, {"kind": "group"}, HTTP_X_STORE="home")

    assert_problem_details(response, status=401, code="not_authenticated")


def test_upload_requires_the_store_header(client, home, user, private_storage):
    grant_membership(user=user, store=home, role_name="content_editor")

    response = client.post(
        UPLOAD_URL,
        {"file": SimpleUploadedFile("photo.jpg", image_bytes()), "kind": "group"},
        HTTP_AUTHORIZATION=bearer(user),
        HTTP_IDEMPOTENCY_KEY="key-1",
    )

    assert_problem_details(response, status=400, code="store_header_missing")


def test_upload_requires_catalog_manage(client, home, user, private_storage):
    grant_membership(user=user, store=home, role_name="warehouse")

    response = upload(client, user)

    assert_problem_details(response, status=403, code="permission_denied")
    assert PhotoSubmission.objects.filter(store=home).count() == 0
    assert [path for path in private_storage.rglob("*") if path.is_file()] == []


def test_upload_goes_through_the_authorizer(
    client, home, user, private_storage, override_authorizer
):
    grant_membership(user=user, store=home, role_name="owner")

    class DenyingAuthorizer:
        def require(self, user_id, store, permission):
            raise PermissionDeniedError("You do not have permission to perform this action.")

    override_authorizer(DenyingAuthorizer())

    response = upload(client, user)

    assert_problem_details(response, status=403, code="permission_denied")


def test_an_individual_photo_rejects_a_target_from_another_store(
    client, home, anime, user, private_storage
):
    grant_membership(user=user, store=home, role_name="content_editor")
    foreign_product = make_product(anime)

    response = upload(client, user, kind="rectangle", target_product=foreign_product.id)

    assert_problem_details(response, status=400, code="submission_invalid_target")
    assert PhotoSubmission.objects.filter(store=home).count() == 0


def test_detail_returns_status_failure_and_result_renditions(client, home, user, media_base_url):
    grant_membership(user=user, store=home, role_name="content_editor")
    media = Media.objects.create(
        store=home,
        storage_key="stores/1/media/result.jpg",
        content_hash="result",
        mime_type="image/jpeg",
        width=800,
        height=1000,
    )
    submission = PhotoSubmission.objects.create(
        store=home,
        created_by=user,
        kind=PhotoSubmission.Kind.GROUP,
        idempotency_key="key-1",
        request_fingerprint="a" * 64,
        status=PhotoSubmission.Status.FAILED,
        failure_code="quad_invalid_corners",
        failure_message="The corners cross each other.",
        result_media=media,
        pipeline_version="2026-11-11.2",
        attempts=2,
        version=3,
    )

    response = get_detail(client, user, submission.pk)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["failure_code"] == "quad_invalid_corners"
    assert body["failure_message"] == "The corners cross each other."
    assert body["preview_url"] == PREVIEW_URL.format(id=submission.pk)
    assert body["result"] == {
        "media_id": media.id,
        "url": "https://media.example.com/stores/1/media/result.jpg",
        "thumbnail_url": (
            "https://media.example.com/stores/1/media/renditions/result-320w-v1.webp"
        ),
        "medium_url": ("https://media.example.com/stores/1/media/renditions/result-800w-v1.webp"),
        "width": 800,
        "height": 1000,
    }
    assert body["pipeline_version"] == "2026-11-11.2"
    assert body["attempts"] == 2
    assert body["version"] == 3


def test_detail_requires_catalog_manage(client, home, user):
    grant_membership(user=user, store=home, role_name="warehouse")
    submission = PhotoSubmission.objects.create(
        store=home,
        created_by=user,
        kind=PhotoSubmission.Kind.GROUP,
        idempotency_key="key-1",
        request_fingerprint="a" * 64,
    )

    response = get_detail(client, user, submission.pk)

    assert_problem_details(response, status=403, code="permission_denied")


def test_detail_never_returns_another_stores_submission(client, home, anime, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    grant_membership(user=user, store=anime, role_name="content_editor")
    submission = PhotoSubmission.objects.create(
        store=home,
        created_by=user,
        kind=PhotoSubmission.Kind.GROUP,
        idempotency_key="key-1",
        request_fingerprint="a" * 64,
    )

    response = get_detail(client, user, submission.pk, store="anime")

    assert_problem_details(response, status=404, code="not_found")


def test_preview_streams_the_private_file_after_authorization(client, home, user, private_storage):
    grant_membership(user=user, store=home, role_name="content_editor")
    upload_response = upload(client, user)
    submission_id = upload_response.json()["id"]

    response = get_preview(client, user, submission_id)

    assert response.status_code == 200
    assert response["Content-Type"] == "image/jpeg"
    assert response["Cache-Control"] == "private, no-store"
    assert response["X-Content-Type-Options"] == "nosniff"
    content = b"".join(response.streaming_content)
    assert content.startswith(b"\xff\xd8")


def test_preview_requires_authentication(client, home, user):
    submission = PhotoSubmission.objects.create(
        store=home,
        created_by=user,
        kind=PhotoSubmission.Kind.GROUP,
        idempotency_key="key-1",
        request_fingerprint="a" * 64,
        preview_key="stores/1/photos/previews/preview.jpg",
    )

    response = client.get(PREVIEW_URL.format(id=submission.pk), HTTP_X_STORE="home")

    assert_problem_details(response, status=401, code="not_authenticated")


def test_preview_requires_catalog_manage(client, home, user):
    grant_membership(user=user, store=home, role_name="warehouse")
    submission = PhotoSubmission.objects.create(
        store=home,
        created_by=user,
        kind=PhotoSubmission.Kind.GROUP,
        idempotency_key="key-1",
        request_fingerprint="a" * 64,
        preview_key="stores/1/photos/previews/preview.jpg",
    )

    response = get_preview(client, user, submission.pk)

    assert_problem_details(response, status=403, code="permission_denied")


def test_preview_never_streams_another_stores_submission(
    client, home, anime, user, private_storage
):
    grant_membership(user=user, store=home, role_name="content_editor")
    grant_membership(user=user, store=anime, role_name="content_editor")
    upload_response = upload(client, user)
    submission_id = upload_response.json()["id"]

    response = get_preview(client, user, submission_id, store="anime")

    assert_problem_details(response, status=404, code="not_found")


def test_schema_documents_the_photo_upload_and_status_api(client):
    schema = client.get("/api/v1/schema/", HTTP_ACCEPT="application/json").json()

    upload = schema["paths"][UPLOAD_URL]["post"]
    assert ("Idempotency-Key", "header") in {
        (parameter["name"], parameter["in"]) for parameter in upload["parameters"]
    }
    assert ("X-Store", "header") in {
        (parameter["name"], parameter["in"]) for parameter in upload["parameters"]
    }
    request_schema = upload["requestBody"]["content"]["multipart/form-data"]["schema"]
    component = schema["components"]["schemas"][request_schema["$ref"].rsplit("/", 1)[-1]]
    assert {"file", "kind", "target_product", "photographed_variant", "corners", "crop"} <= set(
        component["properties"]
    )
    assert "light_correction" in component["properties"]
    _assert_adjustment_shapes(schema, component)
    assert {example["value"]["code"] for example in _codes(upload, 409)} == {"idempotency_conflict"}

    detail = schema["paths"][DETAIL_URL.format(id="{id}")]["get"]
    response = detail["responses"]["200"]["content"]["application/json"]
    example = next(iter(response["examples"].values()))["value"]
    assert {"status", "failure_code", "failure_message", "preview_url", "result"} <= set(example)
    assert {"url", "thumbnail_url", "medium_url"} <= set(example["result"])
    assert "linked_product_ids" in example

    preview = schema["paths"][PREVIEW_URL.format(id="{id}")]["get"]
    assert "200" in preview["responses"]
    assert "image/jpeg" in preview["responses"]["200"]["content"]


def _codes(operation, status):
    media = operation["responses"][str(status)]["content"]["application/problem+json"]
    return media["examples"].values()


def _resolved(schema, value):
    if "$ref" not in value:
        return value
    name = value["$ref"].rsplit("/", 1)[-1]
    return schema["components"]["schemas"][name]


def _assert_adjustment_shapes(schema, component):
    corners = _resolved(schema, component["properties"]["corners"])
    assert corners["type"] == "array"
    assert corners["minItems"] == 4
    assert corners["maxItems"] == 4
    point = _resolved(schema, corners["items"])
    assert set(point["properties"]) == {"x", "y"}
    assert point["properties"]["x"]["type"] == "number"
    assert point["properties"]["y"]["type"] == "number"

    crop = _resolved(schema, component["properties"]["crop"])
    assert set(crop["properties"]) == {"x", "y", "width", "height"}
    assert {value["type"] for value in crop["properties"].values()} == {"number"}


def make_submission(
    store,
    user,
    *,
    product,
    status=PhotoSubmission.Status.READY,
    result_media=None,
    attempts=1,
    idempotency_key="action-key",
    corners=None,
    crop=None,
    applied_at=None,
    applied_by=None,
):
    return PhotoSubmission.objects.create(
        store=store,
        created_by=user,
        kind=PhotoSubmission.Kind.RECTANGLE,
        target_product=product,
        idempotency_key=idempotency_key,
        request_fingerprint="a" * 64,
        status=status,
        result_media=result_media,
        attempts=attempts,
        original_key=f"stores/{store.id}/photos/originals/{idempotency_key}.jpg",
        preview_key=f"stores/{store.id}/photos/previews/{idempotency_key}.jpg",
        corners=corners,
        crop=crop,
        applied_at=applied_at,
        applied_by=applied_by,
    )


def make_group_submission(store, user, *, result_media, idempotency_key="group-key"):
    return PhotoSubmission.objects.create(
        store=store,
        created_by=user,
        kind=PhotoSubmission.Kind.GROUP,
        idempotency_key=idempotency_key,
        request_fingerprint="a" * 64,
        status=PhotoSubmission.Status.READY,
        result_media=result_media,
        attempts=1,
        original_key=f"stores/{store.id}/photos/originals/{idempotency_key}.jpg",
        preview_key=f"stores/{store.id}/photos/previews/{idempotency_key}.jpg",
    )


def make_media(store, *, key="stores/1/media/result.jpg", content_hash="result"):
    return Media.objects.create(
        store=store,
        storage_key=key,
        content_hash=content_hash,
        mime_type="image/jpeg",
        width=800,
        height=1000,
    )


def post_action(client, user, action, submission_id, *, store="home", data=None):
    return client.post(
        ACTION_URLS[action].format(id=submission_id),
        data=json.dumps(data or {}),
        content_type="application/json",
        HTTP_AUTHORIZATION=bearer(user),
        HTTP_X_STORE=store,
    )


def test_apply_appends_the_result_and_makes_it_the_cover_on_an_empty_carousel(client, home, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    product = make_product(home)
    media = make_media(home, key="stores/1/media/new.jpg", content_hash="new")
    submission = make_submission(
        home, user, product=product, result_media=media, idempotency_key="apply-key"
    )

    response = post_action(client, user, "apply", submission.pk)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["applied_at"] is not None
    assert body["discarded_at"] is None
    assert body["result"]["media_id"] == media.id

    submission.refresh_from_db()
    link = ProductMedia.objects.get(product=product, media=media)
    assert submission.applied_at is not None
    assert submission.applied_by_id == user.id
    assert link.role == ProductMedia.Role.MAIN
    assert link.position == 1
    assert link.is_active is True
    assert Media.objects.filter(pk=media.pk).exists()


def test_apply_appends_a_second_photo_and_keeps_the_existing_cover(client, home, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    product = make_product(home)
    cover_media = make_media(home, key="stores/1/media/cover.jpg", content_hash="cover")
    cover_link = ProductMedia.objects.create(
        product=product, media=cover_media, role=ProductMedia.Role.MAIN
    )
    new_media = make_media(home, key="stores/1/media/new.jpg", content_hash="new")
    submission = make_submission(
        home, user, product=product, result_media=new_media, idempotency_key="apply-key"
    )

    response = post_action(client, user, "apply", submission.pk)

    assert response.status_code == 200
    cover_link.refresh_from_db()
    new_link = ProductMedia.objects.get(product=product, media=new_media)
    assert cover_link.is_active is True
    assert cover_link.role == ProductMedia.Role.MAIN
    assert new_link.role == ProductMedia.Role.GALLERY
    assert new_link.position == 2
    assert new_link.is_active is True


def test_remove_takes_the_photo_out_and_promotes_the_next_cover(client, home, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    product = make_product(home)
    cover_media = make_media(home, key="stores/1/media/cover.jpg", content_hash="cover")
    cover_submission = make_submission(
        home,
        user,
        product=product,
        result_media=cover_media,
        idempotency_key="cover-key",
    )
    second_media = make_media(home, key="stores/1/media/second.jpg", content_hash="second")
    second_submission = make_submission(
        home,
        user,
        product=product,
        result_media=second_media,
        idempotency_key="second-key",
    )
    post_action(client, user, "apply", cover_submission.pk)
    post_action(client, user, "apply", second_submission.pk)

    response = post_action(client, user, "remove", cover_submission.pk)

    assert response.status_code == 200
    body = response.json()
    assert body["applied_at"] is None
    cover_submission.refresh_from_db()
    cover_link = ProductMedia.objects.get(product=product, media=cover_media)
    second_link = ProductMedia.objects.get(product=product, media=second_media)
    assert cover_submission.applied_at is None
    assert cover_submission.applied_by_id is None
    assert cover_link.is_active is False
    assert second_link.role == ProductMedia.Role.MAIN
    assert second_link.is_active is True
    assert Media.objects.filter(pk=cover_media.pk).exists()
    assert ProductMedia.objects.filter(pk=cover_link.pk).exists()
    assert (
        ProductMedia.objects.filter(
            product=product, role=ProductMedia.Role.MAIN, is_active=True
        ).count()
        == 1
    )


def test_remove_refuses_a_submission_that_is_not_applied(client, home, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    product = make_product(home)
    media = make_media(home)
    submission = make_submission(home, user, product=product, result_media=media)

    response = post_action(client, user, "remove", submission.pk)

    assert_problem_details(response, status=409, code="submission_cannot_remove")


def test_remove_requires_catalog_manage(client, home, user):
    grant_membership(user=user, store=home, role_name="warehouse")
    product = make_product(home)
    media = make_media(home)
    submission = make_submission(
        home,
        user,
        product=product,
        result_media=media,
        applied_at=timezone.now(),
        applied_by=user,
    )

    response = post_action(client, user, "remove", submission.pk)

    assert_problem_details(response, status=403, code="permission_denied")


def test_remove_never_reaches_another_stores_applied_submission(client, home, anime, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    grant_membership(user=user, store=anime, role_name="content_editor")
    product = make_product(home)
    media = make_media(home)
    submission = make_submission(
        home,
        user,
        product=product,
        result_media=media,
        applied_at=timezone.now(),
        applied_by=user,
        idempotency_key="isolation-remove",
    )

    response = post_action(client, user, "remove", submission.pk, store="anime")

    assert_problem_details(response, status=404, code="not_found")
    submission.refresh_from_db()
    assert submission.applied_at is not None


def test_remove_refuses_an_applied_group_photo_and_keeps_its_links(client, home, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    product = make_product(home)
    media = make_media(home, key="stores/1/media/group.jpg", content_hash="group")
    submission = make_group_submission(home, user, result_media=media)
    post_action(client, user, "apply", submission.pk, data={"product_ids": [product.pk]})
    link = ProductMedia.objects.get(product=product, media=media)
    assert link.is_active is True

    response = post_action(client, user, "remove", submission.pk)

    body = assert_problem_details(response, status=409, code="submission_cannot_remove")
    assert "links" in body["detail"]
    link.refresh_from_db()
    submission.refresh_from_db()
    assert link.is_active is True
    assert submission.applied_at is not None


def test_apply_requires_a_ready_individual_photo(client, home, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    product = make_product(home)
    submission = make_submission(
        home,
        user,
        product=product,
        status=PhotoSubmission.Status.PROCESSING,
        result_media=None,
        idempotency_key="processing-key",
    )

    response = post_action(client, user, "apply", submission.pk)

    assert_problem_details(response, status=409, code="submission_cannot_apply")


def test_redo_reuses_the_engine_with_new_corners_and_keeps_the_old_media(
    client, home, user, override_photo_processing_queue
):
    grant_membership(user=user, store=home, role_name="content_editor")
    product = make_product(home)
    old_media = make_media(home, key="stores/1/media/old.jpg", content_hash="old")
    submission = make_submission(
        home,
        user,
        product=product,
        result_media=old_media,
        idempotency_key="redo-key",
        corners=CORNERS,
        crop=CROP,
    )
    queued = []

    class RecordingQueue:
        def enqueue(self, store, submission_id):
            queued.append((store.id, submission_id))

    override_photo_processing_queue(RecordingQueue())

    response = post_action(
        client,
        user,
        "redo",
        submission.pk,
        data={
            "corners": [
                {"x": 0.2, "y": 0.2},
                {"x": 0.8, "y": 0.2},
                {"x": 0.8, "y": 0.8},
                {"x": 0.2, "y": 0.8},
            ],
            "crop": {"x": 2, "y": 2, "width": 6, "height": 8},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processing"
    assert body["result"] is None
    assert body["corners"][0] == {"x": 0.2, "y": 0.2}
    assert body["crop"] == {"x": 2, "y": 2, "width": 6, "height": 8}
    assert queued == [(home.id, submission.pk)]

    submission.refresh_from_db()
    assert submission.status == PhotoSubmission.Status.PROCESSING
    assert submission.result_media is None
    assert Media.objects.filter(pk=old_media.pk).exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("corners", [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}]),
        ("corners", [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.9}, None]),
        ("corners", None),
        ("crop", {"x": 1, "y": 1, "width": 8}),
        ("crop", {"x": 1, "y": True, "width": 8, "height": 10}),
        ("crop", None),
    ],
)
def test_redo_validates_the_shape_of_corners_and_crop(client, home, user, field, value):
    grant_membership(user=user, store=home, role_name="content_editor")
    product = make_product(home)
    submission = make_submission(
        home,
        user,
        product=product,
        idempotency_key="redo-shape-key",
        corners=CORNERS,
        crop=CROP,
    )

    response = post_action(client, user, "redo", submission.pk, data={field: value})

    body = assert_problem_details(response, status=400, code="validation_error")
    assert body["errors"][0]["field"].startswith(field)
    submission.refresh_from_db()
    assert submission.status == PhotoSubmission.Status.READY
    assert submission.corners == CORNERS
    assert submission.crop == CROP


def test_redo_refuses_a_photo_that_is_not_ready(client, home, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    product = make_product(home)
    submission = make_submission(
        home,
        user,
        product=product,
        status=PhotoSubmission.Status.FAILED,
        result_media=None,
        idempotency_key="redo-failed-key",
    )

    response = post_action(client, user, "redo", submission.pk, data={"crop": CROP})

    assert_problem_details(response, status=409, code="submission_cannot_redo")


def test_retry_enqueues_a_failed_submission_with_another_attempt(
    client, home, user, override_photo_processing_queue
):
    grant_membership(user=user, store=home, role_name="content_editor")
    product = make_product(home)
    submission = make_submission(
        home,
        user,
        product=product,
        status=PhotoSubmission.Status.FAILED,
        result_media=None,
        attempts=1,
        idempotency_key="retry-key",
    )
    queued = []

    class RecordingQueue:
        def enqueue(self, store, submission_id):
            queued.append((store.id, submission_id))

    override_photo_processing_queue(RecordingQueue())

    response = post_action(client, user, "retry", submission.pk)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processing"
    assert body["attempts"] == 2
    assert queued == [(home.id, submission.pk)]


def test_retry_refuses_a_submission_that_did_not_fail(client, home, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    product = make_product(home)
    submission = make_submission(home, user, product=product, idempotency_key="retry-ready-key")

    response = post_action(client, user, "retry", submission.pk)

    assert_problem_details(response, status=409, code="submission_cannot_start_processing")


def test_discard_deletes_only_the_private_original_and_preview(client, home, user, private_storage):
    grant_membership(user=user, store=home, role_name="content_editor")
    submission_id = upload(client, user).json()["id"]
    submission = PhotoSubmission.objects.get(pk=submission_id)
    original_path = private_storage / submission.original_key
    preview_path = private_storage / submission.preview_key
    assert original_path.exists()
    assert preview_path.exists()

    response = post_action(client, user, "discard", submission_id)

    assert response.status_code == 200
    body = response.json()
    assert body["discarded_at"] is not None
    assert not original_path.exists()
    assert not preview_path.exists()

    submission.refresh_from_db()
    assert submission.discarded_at is not None
    assert PhotoSubmission.objects.filter(pk=submission.pk).exists()


def test_discard_refuses_an_applied_submission(client, home, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    product = make_product(home)
    media = make_media(home)
    submission = make_submission(
        home, user, product=product, result_media=media, idempotency_key="applied-key"
    )
    post_action(client, user, "apply", submission.pk)

    response = post_action(client, user, "discard", submission.pk)

    assert_problem_details(response, status=409, code="submission_cannot_discard")


@pytest.mark.parametrize(
    ("action", "status"),
    [
        ("apply", PhotoSubmission.Status.READY),
        ("redo", PhotoSubmission.Status.READY),
        ("retry", PhotoSubmission.Status.FAILED),
        ("discard", PhotoSubmission.Status.UPLOADED),
    ],
)
def test_actions_never_reach_another_stores_submission(client, home, anime, user, action, status):
    grant_membership(user=user, store=home, role_name="content_editor")
    grant_membership(user=user, store=anime, role_name="content_editor")
    product = make_product(home)
    media = make_media(home) if status == PhotoSubmission.Status.READY else None
    submission = make_submission(
        home,
        user,
        product=product,
        status=status,
        result_media=media,
        attempts=1 if status == PhotoSubmission.Status.FAILED else 0,
        idempotency_key=f"isolation-{action}",
    )

    response = post_action(
        client,
        user,
        action,
        submission.pk,
        store="anime",
        data={"crop": CROP},
    )

    assert_problem_details(response, status=404, code="not_found")
    submission.refresh_from_db()
    assert submission.applied_at is None
    assert submission.discarded_at is None


def test_actions_require_catalog_manage(client, home, user):
    grant_membership(user=user, store=home, role_name="warehouse")
    product = make_product(home)
    submission = make_submission(home, user, product=product, idempotency_key="no-permission-key")

    response = post_action(client, user, "apply", submission.pk)

    assert_problem_details(response, status=403, code="permission_denied")


def test_schema_documents_the_photo_actions(client):
    schema = client.get("/api/v1/schema/", HTTP_ACCEPT="application/json").json()

    for action, url in ACTION_URLS.items():
        assert url.format(id="{id}") in schema["paths"], action
        operation = schema["paths"][url.format(id="{id}")]["post"]
        assert "200" in operation["responses"]

    redo = schema["paths"][ACTION_URLS["redo"].format(id="{id}")]["post"]
    request_schema = redo["requestBody"]["content"]["application/json"]["schema"]
    component = schema["components"]["schemas"][request_schema["$ref"].rsplit("/", 1)[-1]]
    assert {"corners", "crop"} <= set(component["properties"])
    _assert_adjustment_shapes(schema, component)


def test_group_apply_links_the_result_media_to_each_selected_product(client, home, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    first = make_product(home, name="First", slug="first")
    second = make_product(home, name="Second", slug="second")
    media = make_media(home, key="stores/1/media/group.jpg", content_hash="group")
    submission = make_group_submission(home, user, result_media=media)

    response = post_action(
        client, user, "apply", submission.pk, data={"product_ids": [first.pk, second.pk]}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["applied_at"] is not None
    assert body["linked_product_ids"] == [first.pk, second.pk]
    first_link = ProductMedia.objects.get(product=first, media=media)
    second_link = ProductMedia.objects.get(product=second, media=media)
    assert first_link.is_active is True
    assert second_link.is_active is True
    assert first_link.role == ProductMedia.Role.MAIN
    assert second_link.role == ProductMedia.Role.MAIN
    assert Media.objects.filter(pk=media.pk).count() == 1


def test_group_apply_keeps_an_existing_cover_and_appends_a_gallery_image(client, home, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    product = make_product(home)
    cover_media = make_media(home, key="stores/1/media/cover.jpg", content_hash="cover")
    cover_link = ProductMedia.objects.create(
        product=product, media=cover_media, role=ProductMedia.Role.MAIN
    )
    group_media = make_media(home, key="stores/1/media/group.jpg", content_hash="group")
    submission = make_group_submission(home, user, result_media=group_media)

    response = post_action(client, user, "apply", submission.pk, data={"product_ids": [product.pk]})

    assert response.status_code == 200
    cover_link.refresh_from_db()
    group_link = ProductMedia.objects.get(product=product, media=group_media)
    assert cover_link.is_active is True
    assert cover_link.role == ProductMedia.Role.MAIN
    assert group_link.role == ProductMedia.Role.GALLERY
    assert group_link.position == 2


def test_group_apply_without_products_is_refused(client, home, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    product = make_product(home)
    media = make_media(home)
    submission = make_group_submission(home, user, result_media=media)

    response = post_action(client, user, "apply", submission.pk, data={"product_ids": []})

    assert_problem_details(response, status=409, code="submission_cannot_apply")
    assert not ProductMedia.objects.filter(product=product, media=media).exists()


def test_group_apply_requires_catalog_manage(client, home, user):
    grant_membership(user=user, store=home, role_name="warehouse")
    product = make_product(home)
    media = make_media(home)
    submission = make_group_submission(home, user, result_media=media)

    response = post_action(client, user, "apply", submission.pk, data={"product_ids": [product.pk]})

    assert_problem_details(response, status=403, code="permission_denied")
    assert not ProductMedia.objects.filter(product=product).exists()


def test_group_links_add_remove_and_reactivate_without_duplicates(client, home, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    first = make_product(home, name="First", slug="first")
    second = make_product(home, name="Second", slug="second")
    third = make_product(home, name="Third", slug="third")
    media = make_media(home, key="stores/1/media/group.jpg", content_hash="group")
    submission = make_group_submission(home, user, result_media=media)
    post_action(client, user, "apply", submission.pk, data={"product_ids": [first.pk, second.pk]})
    first_link = ProductMedia.objects.get(product=first, media=media)
    second_link = ProductMedia.objects.get(product=second, media=media)

    added = post_action(
        client, user, "links", submission.pk, data={"product_ids": [first.pk, third.pk]}
    )

    assert added.status_code == 200
    first_link.refresh_from_db()
    second_link.refresh_from_db()
    assert added.json()["linked_product_ids"] == [first.pk, third.pk]
    assert first_link.is_active is True
    assert first_link.position == 1
    assert second_link.is_active is False
    third_link = ProductMedia.objects.get(product=third, media=media)
    assert third_link.is_active is True

    restored = post_action(
        client,
        user,
        "links",
        submission.pk,
        data={"product_ids": [first.pk, second.pk, third.pk]},
    )

    assert restored.status_code == 200
    assert restored.json()["linked_product_ids"] == [first.pk, second.pk, third.pk]
    second_link.refresh_from_db()
    assert second_link.is_active is True
    assert ProductMedia.objects.filter(product=second, media=media).count() == 1
    assert Media.objects.filter(pk=media.pk).count() == 1


def test_group_links_never_touch_another_stores_products(client, home, anime, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    grant_membership(user=user, store=anime, role_name="content_editor")
    home_product = make_product(home)
    anime_product = make_product(anime, name="Anime", slug="anime-product")
    media = make_media(home, key="stores/1/media/group.jpg", content_hash="group")
    submission = make_group_submission(home, user, result_media=media)
    post_action(client, user, "apply", submission.pk, data={"product_ids": [home_product.pk]})

    response = post_action(
        client,
        user,
        "links",
        submission.pk,
        store="anime",
        data={"product_ids": [anime_product.pk]},
    )

    assert_problem_details(response, status=404, code="not_found")
    assert not ProductMedia.objects.filter(product=anime_product).exists()
    assert ProductMedia.objects.get(product=home_product, media=media).is_active is True


def test_group_apply_refuses_another_stores_product(client, home, anime, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    anime_product = make_product(anime)
    media = make_media(home)
    submission = make_group_submission(home, user, result_media=media)

    response = post_action(
        client, user, "apply", submission.pk, data={"product_ids": [anime_product.pk]}
    )

    assert_problem_details(response, status=404, code="catalog_store_mismatch")
    assert not ProductMedia.objects.filter(product=anime_product).exists()
    submission.refresh_from_db()
    assert submission.applied_at is None


def test_group_links_require_catalog_manage(client, home, user):
    grant_membership(user=user, store=home, role_name="warehouse")
    product = make_product(home)
    media = make_media(home)
    submission = make_group_submission(home, user, result_media=media)

    response = post_action(client, user, "links", submission.pk, data={"product_ids": [product.pk]})

    assert_problem_details(response, status=403, code="permission_denied")
    assert not ProductMedia.objects.filter(product=product).exists()


def test_group_links_refuse_an_individual_photo(client, home, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    product = make_product(home)
    media = make_media(home)
    submission = make_submission(home, user, product=product, result_media=media)

    response = post_action(client, user, "links", submission.pk, data={"product_ids": [product.pk]})

    assert_problem_details(response, status=409, code="submission_cannot_change_links")
