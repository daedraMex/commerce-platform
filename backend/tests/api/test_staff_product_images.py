import pytest
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.services import grant_membership
from apps.catalog.models import Category, Design, Media, Product, ProductMedia, Supplier
from apps.photos.models import PhotoSubmission
from apps.shared.domain.exceptions import PermissionDeniedError
from apps.stores.models import Store
from tests.api.helpers import assert_problem_details

pytestmark = pytest.mark.django_db

IMAGES_URL = "/api/v1/staff/products/{id}/images/"
ORDER_URL = "/api/v1/staff/products/{id}/images/order/"


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


def make_media(store, *, content_hash, alt_text="A blanket"):
    return Media.objects.create(
        store=store,
        storage_key=f"stores/{store.id}/media/{content_hash}.jpg",
        content_hash=content_hash,
        mime_type="image/jpeg",
        alt_text=alt_text,
        width=800,
        height=600,
    )


def add_link(product, store, *, role, content_hash, position=None, is_active=True):
    media = make_media(store, content_hash=content_hash)
    return ProductMedia.objects.create(
        product=product,
        media=media,
        role=role,
        position=position,
        is_active=is_active,
    )


def make_submission(store, user, product, media, *, key, status="ready", applied=False):
    return PhotoSubmission.objects.create(
        store=store,
        created_by=user,
        kind=PhotoSubmission.Kind.RECTANGLE,
        target_product=product,
        result_media=media,
        status=status,
        attempts=1,
        idempotency_key=key,
        request_fingerprint="a" * 64,
        pipeline_version="2026-11-11.2",
        original_key=f"stores/{store.id}/photos/originals/{key}.jpg",
        preview_key=f"stores/{store.id}/photos/previews/{key}.jpg",
        applied_at=None if not applied else "2026-11-12T09:32:00Z",
    )


def get_images(client, user, product_id, store="home"):
    return client.get(
        IMAGES_URL.format(id=product_id),
        HTTP_AUTHORIZATION=bearer(user),
        HTTP_X_STORE=store,
    )


def reorder(client, user, product_id, image_ids, store="home"):
    return client.put(
        ORDER_URL.format(id=product_id),
        {"image_ids": image_ids},
        content_type="application/json",
        HTTP_AUTHORIZATION=bearer(user),
        HTTP_X_STORE=store,
    )


def test_lists_active_images_in_position_order_then_inactive_removed_and_unapproved(
    client, home, user, media_base_url
):
    grant_membership(user=user, store=home, role_name="content_editor")
    product = make_product(home)
    cover = add_link(product, home, role=ProductMedia.Role.MAIN, content_hash="cover", position=1)
    second = add_link(
        product, home, role=ProductMedia.Role.GALLERY, content_hash="second", position=2
    )
    removed = add_link(
        product,
        home,
        role=ProductMedia.Role.GALLERY,
        content_hash="removed",
        position=3,
        is_active=False,
    )
    make_submission(home, user, product, cover.media, key="cover", applied=True)
    make_submission(home, user, product, removed.media, key="removed")

    pending_media = make_media(home, content_hash="pending", alt_text="Waiting photo")
    pending = make_submission(home, user, product, pending_media, key="pending")

    response = get_images(client, user, product.id)

    assert response.status_code == 200
    body = response.json()
    assert body["product_id"] == product.id
    images = body["images"]
    assert [image["id"] for image in images] == [cover.id, second.id, removed.id, None]
    assert [image["active"] for image in images] == [True, True, False, False]
    assert [image["position"] for image in images] == [1, 2, 3, None]
    assert [image["role"] for image in images] == ["main", "gallery", "gallery", None]
    assert (
        images[0]["photo_submission_id"] == PhotoSubmission.objects.get(idempotency_key="cover").id
    )
    assert images[1]["photo_submission_id"] is None
    assert (
        images[2]["photo_submission_id"]
        == PhotoSubmission.objects.get(idempotency_key="removed").id
    )
    assert images[3]["photo_submission_id"] == pending.id
    assert images[3]["media_id"] == pending_media.id
    assert images[3]["url"] == f"https://media.example.com/stores/{home.id}/media/pending.jpg"
    assert images[0]["thumbnail_url"].endswith("/renditions/cover-320w-v1.webp")


def test_does_not_show_another_products_or_another_stores_images(client, home, anime, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    grant_membership(user=user, store=anime, role_name="content_editor")
    product = make_product(home)
    other_product = make_product(home, name="Other", slug="other")
    foreign_product = make_product(anime, name="Foreign", slug="foreign")
    own = add_link(product, home, role=ProductMedia.Role.MAIN, content_hash="own", position=1)
    add_link(other_product, home, role=ProductMedia.Role.MAIN, content_hash="other", position=1)
    add_link(
        foreign_product, anime, role=ProductMedia.Role.MAIN, content_hash="foreign", position=1
    )
    pending_media = make_media(home, content_hash="pending")
    make_submission(home, user, product, pending_media, key="pending")
    other_pending = make_media(home, content_hash="other-pending")
    make_submission(home, user, other_product, other_pending, key="other-pending")

    response = get_images(client, user, product.id)

    assert response.status_code == 200
    assert [image["id"] for image in response.json()["images"]] == [own.id, None]
    assert response.json()["images"][1]["media_id"] == pending_media.id


def test_carousel_requires_catalog_manage(client, home, user):
    grant_membership(user=user, store=home, role_name="warehouse")
    product = make_product(home)

    response = get_images(client, user, product.id)

    assert_problem_details(response, status=403, code="permission_denied")


def test_carousel_goes_through_the_authorizer(client, home, user, override_authorizer):
    grant_membership(user=user, store=home, role_name="owner")
    product = make_product(home)

    class DenyingAuthorizer:
        def require(self, user_id, store, permission):
            raise PermissionDeniedError("You do not have permission to perform this action.")

    override_authorizer(DenyingAuthorizer())

    response = get_images(client, user, product.id)

    assert_problem_details(response, status=403, code="permission_denied")


def test_another_stores_product_is_not_found(client, home, anime, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    foreign_product = make_product(anime, name="Foreign", slug="foreign")
    add_link(foreign_product, anime, role=ProductMedia.Role.MAIN, content_hash="foreign")

    response = get_images(client, user, foreign_product.id)

    assert_problem_details(response, status=404, code="not_found")


def test_reorder_renumbers_positions_and_moves_the_cover(client, home, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    product = make_product(home)
    first = add_link(product, home, role=ProductMedia.Role.MAIN, content_hash="first", position=1)
    second = add_link(
        product, home, role=ProductMedia.Role.GALLERY, content_hash="second", position=2
    )
    third = add_link(
        product, home, role=ProductMedia.Role.GALLERY, content_hash="third", position=3
    )

    response = reorder(client, user, product.id, [third.id, first.id, second.id])

    assert response.status_code == 200
    body = response.json()
    assert [image["id"] for image in body["images"]] == [third.id, first.id, second.id]
    assert [image["position"] for image in body["images"]] == [1, 2, 3]
    assert [image["role"] for image in body["images"]] == ["main", "gallery", "gallery"]
    assert ProductMedia.objects.get(pk=third.id).role == ProductMedia.Role.MAIN
    assert (
        ProductMedia.objects.filter(
            product=product, role=ProductMedia.Role.MAIN, is_active=True
        ).count()
        == 1
    )
    assert ProductMedia.objects.filter(product=product).count() == 3


@pytest.mark.parametrize(
    "build_ids",
    [
        lambda first, second, inactive, other, foreign: [first.id],
        lambda first, second, inactive, other, foreign: [first.id, first.id, second.id],
        lambda first, second, inactive, other, foreign: [first.id, second.id, 999999],
        lambda first, second, inactive, other, foreign: [first.id, second.id, inactive.id],
        lambda first, second, inactive, other, foreign: [first.id, second.id, other.id],
        lambda first, second, inactive, other, foreign: [first.id, second.id, foreign.id],
    ],
    ids=["omits", "repeats", "adds", "inactive", "other-product", "other-store"],
)
def test_reorder_rejects_invalid_lists(client, home, anime, user, build_ids):
    grant_membership(user=user, store=home, role_name="content_editor")
    grant_membership(user=user, store=anime, role_name="content_editor")
    product = make_product(home)
    first = add_link(product, home, role=ProductMedia.Role.MAIN, content_hash="first", position=1)
    second = add_link(
        product, home, role=ProductMedia.Role.GALLERY, content_hash="second", position=2
    )
    inactive = add_link(
        product,
        home,
        role=ProductMedia.Role.GALLERY,
        content_hash="inactive",
        position=3,
        is_active=False,
    )
    other_product = make_product(home, name="Other", slug="other")
    other = add_link(
        other_product, home, role=ProductMedia.Role.MAIN, content_hash="other", position=1
    )
    foreign_product = make_product(anime, name="Foreign", slug="foreign")
    foreign = add_link(
        foreign_product, anime, role=ProductMedia.Role.MAIN, content_hash="foreign", position=1
    )

    response = reorder(client, user, product.id, build_ids(first, second, inactive, other, foreign))

    assert_problem_details(response, status=400, code="catalog_invalid_image_order")
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.position == 1
    assert first.role == ProductMedia.Role.MAIN
    assert second.position == 2


def test_reorder_requires_catalog_manage(client, home, user):
    grant_membership(user=user, store=home, role_name="warehouse")
    product = make_product(home)
    first = add_link(product, home, role=ProductMedia.Role.MAIN, content_hash="first", position=1)
    second = add_link(
        product, home, role=ProductMedia.Role.GALLERY, content_hash="second", position=2
    )

    response = reorder(client, user, product.id, [second.id, first.id])

    assert_problem_details(response, status=403, code="permission_denied")


def test_reorder_requires_catalog_manage_through_the_authorizer(
    client, home, user, override_authorizer
):
    grant_membership(user=user, store=home, role_name="owner")
    product = make_product(home)
    first = add_link(product, home, role=ProductMedia.Role.MAIN, content_hash="first", position=1)
    second = add_link(
        product, home, role=ProductMedia.Role.GALLERY, content_hash="second", position=2
    )

    class DenyingAuthorizer:
        def require(self, user_id, store, permission):
            raise PermissionDeniedError("You do not have permission to perform this action.")

    override_authorizer(DenyingAuthorizer())

    response = reorder(client, user, product.id, [second.id, first.id])

    assert_problem_details(response, status=403, code="permission_denied")
    first.refresh_from_db()
    assert first.role == ProductMedia.Role.MAIN


def test_reorder_a_product_of_another_store_is_not_found(client, home, anime, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    foreign_product = make_product(anime, name="Foreign", slug="foreign")
    link = add_link(foreign_product, anime, role=ProductMedia.Role.MAIN, content_hash="foreign")

    response = reorder(client, user, foreign_product.id, [link.id])

    assert_problem_details(response, status=404, code="catalog_store_mismatch")
