import json
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.services import grant_membership
from apps.catalog.models import Category, Design, Media, Product, ProductVariant, Supplier
from apps.photos.models import PhotoSubmission
from apps.shared.domain.exceptions import PermissionDeniedError
from apps.stores.models import Store
from tests.api.helpers import assert_problem_details
from tests.images import image_bytes

pytestmark = pytest.mark.django_db

UPLOAD_URL = "/api/v1/staff/photos/"
DETAIL_URL = "/api/v1/staff/photos/{id}/"
PREVIEW_URL = "/api/v1/staff/photos/{id}/preview/"

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
    assert {example["value"]["code"] for example in _codes(upload, 409)} == {"idempotency_conflict"}

    detail = schema["paths"][DETAIL_URL.format(id="{id}")]["get"]
    response = detail["responses"]["200"]["content"]["application/json"]
    example = next(iter(response["examples"].values()))["value"]
    assert {"status", "failure_code", "failure_message", "preview_url", "result"} <= set(example)
    assert {"url", "thumbnail_url", "medium_url"} <= set(example["result"])

    preview = schema["paths"][PREVIEW_URL.format(id="{id}")]["get"]
    assert "200" in preview["responses"]
    assert "image/jpeg" in preview["responses"]["200"]["content"]


def _codes(operation, status):
    media = operation["responses"][str(status)]["content"]["application/problem+json"]
    return media["examples"].values()
