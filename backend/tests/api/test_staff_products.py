import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.services import grant_membership
from apps.catalog.models import Category, Design, Media, Product, ProductMedia, Supplier
from apps.shared.domain.exceptions import PermissionDeniedError
from apps.stores.models import Store
from tests.api.helpers import assert_problem_details

pytestmark = pytest.mark.django_db

STAFF_PRODUCTS_URL = "/api/v1/staff/products/"
STAFF_PRODUCT_DETAIL_URL = "/api/v1/staff/products/{id}/"

SIZE_OPTION = [
    {
        "code": "size",
        "label": "Size",
        "values": [
            {
                "code": "MAT",
                "label": "Matrimonial",
                "width_cm": 210,
                "height_cm": 160,
            }
        ],
    }
]


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


def get_products(client, user, slug="home", **params):
    return client.get(
        STAFF_PRODUCTS_URL,
        params,
        HTTP_AUTHORIZATION=bearer(user),
        HTTP_X_STORE=slug,
    )


def get_product(client, user, product_id, slug="home"):
    return client.get(
        STAFF_PRODUCT_DETAIL_URL.format(id=product_id),
        HTTP_AUTHORIZATION=bearer(user),
        HTTP_X_STORE=slug,
    )


def make_category(store, *, name="Frazada", slug=None, sku_code="FRZ"):
    return Category.objects.create(
        store=store,
        name=name,
        slug=slug or f"{name.lower()}-{Category.objects.count()}",
        sku_code=sku_code,
        shape=Category.Shape.RECTANGLE,
        option_schema=SIZE_OPTION,
    )


def make_product(store, *, category=None, name="Frazada Térmica", slug=None, is_active=True):
    if category is None:
        category = Category.objects.filter(store=store).first() or make_category(store)
    supplier = Supplier.objects.filter(store=store).first() or Supplier.objects.create(
        store=store, name="Beka"
    )
    design = Design.objects.create(
        store=store,
        supplier=supplier,
        name="Térmica",
        supplier_design_name=f"TERMICA {Design.objects.count()}",
    )
    return Product.objects.create(
        store=store,
        category=category,
        design=design,
        name=name,
        slug=slug or f"product-{Product.objects.count()}",
        attributes={},
        is_active=is_active,
    )


def make_media(store, *, key, content_hash, alt_text="A blanket", width=800, height=600):
    return Media.objects.create(
        store=store,
        storage_key=key,
        content_hash=content_hash,
        mime_type="image/jpeg",
        alt_text=alt_text,
        width=width,
        height=height,
    )


def add_image(product, store, *, role, key, content_hash, is_active=True):
    media = make_media(store, key=key, content_hash=content_hash)
    return ProductMedia.objects.create(
        product=product,
        media=media,
        role=role,
        is_active=is_active,
    )


def test_staff_products_are_store_scoped_and_list_only_active_products(client, home, anime, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    home_product = make_product(home, name="Home product", slug="home-product")
    make_product(home, name="Retired product", slug="retired-product", is_active=False)
    make_product(anime, name="Anime product", slug="anime-product")

    response = get_products(client, user, "home")

    assert response.status_code == 200
    assert [item["slug"] for item in response.json()["results"]] == [home_product.slug]


def test_staff_products_require_catalog_manage(client, home, user):
    grant_membership(user=user, store=home, role_name="warehouse")
    make_product(home)

    response = get_products(client, user, "home")

    assert_problem_details(response, status=403, code="permission_denied")


def test_staff_products_reject_a_user_without_a_membership(client, home, user):
    make_product(home)

    response = get_products(client, user, "home")

    assert_problem_details(response, status=403, code="permission_denied")


def test_staff_products_require_authentication(client, home, user):
    make_product(home)

    response = client.get(STAFF_PRODUCTS_URL, HTTP_X_STORE="home")

    assert_problem_details(response, status=401, code="not_authenticated")


def test_staff_products_go_through_the_authorizer(client, home, user, override_authorizer):
    grant_membership(user=user, store=home, role_name="owner")
    make_product(home)

    class DenyingAuthorizer:
        def require(self, user_id, store, permission):
            raise PermissionDeniedError("You do not have permission to perform this action.")

    override_authorizer(DenyingAuthorizer())

    response = get_products(client, user, "home")

    assert_problem_details(response, status=403, code="permission_denied")


def test_staff_products_search_names_ignoring_case_and_accents(client, home, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    make_product(home, name="Frazada Térmica", slug="frazada-termica")
    make_product(home, name="Frazada Invierno", slug="frazada-invierno")
    make_product(home, name="Almohada", slug="almohada")

    response = get_products(client, user, "home", search="frazada termica")

    assert [item["slug"] for item in response.json()["results"]] == ["frazada-termica"]

    response = get_products(client, user, "home", search="FRAZADA TÉRMICA")

    assert [item["slug"] for item in response.json()["results"]] == ["frazada-termica"]


def test_staff_products_filter_by_category_slug(client, home, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    frazada = make_category(home, name="Frazada", slug="frazada")
    almohada = make_category(home, name="Almohada", slug="almohada", sku_code="ALM")
    make_product(home, category=frazada, name="Frazada product", slug="frazada-product")
    make_product(home, category=almohada, name="Almohada product", slug="almohada-product")

    response = get_products(client, user, "home", category="almohada")

    assert [item["slug"] for item in response.json()["results"]] == ["almohada-product"]


def test_needs_main_image_considers_only_active_main_images(client, home, user, media_base_url):
    grant_membership(user=user, store=home, role_name="content_editor")
    make_product(home, name="No image", slug="no-image")
    retired_main = make_product(home, name="Retired main", slug="retired-main")
    gallery_only = make_product(home, name="Gallery only", slug="gallery-only")
    with_main = make_product(home, name="With main", slug="with-main")

    add_image(
        retired_main,
        home,
        role=ProductMedia.Role.MAIN,
        key="stores/1/media/retired-main.jpg",
        content_hash="retired-main",
        is_active=False,
    )
    add_image(
        gallery_only,
        home,
        role=ProductMedia.Role.GALLERY,
        key="stores/1/media/gallery-only.jpg",
        content_hash="gallery-only",
    )
    add_image(
        with_main,
        home,
        role=ProductMedia.Role.MAIN,
        key="stores/1/media/with-main.jpg",
        content_hash="with-main",
    )

    response = get_products(client, user, "home", needs_main_image="true")

    assert [item["slug"] for item in response.json()["results"]] == [
        "gallery-only",
        "no-image",
        "retired-main",
    ]
    assert all(item["needs_main_image"] is True for item in response.json()["results"])

    response = get_products(client, user, "home", needs_main_image="false")

    assert [item["slug"] for item in response.json()["results"]] == ["with-main"]


def test_staff_products_return_the_active_main_image_and_its_renditions(
    client, home, user, media_base_url
):
    grant_membership(user=user, store=home, role_name="content_editor")
    product = make_product(home, name="Frazada Térmica", slug="frazada-termica")
    add_image(
        product,
        home,
        role=ProductMedia.Role.MAIN,
        key="stores/1/media/main.jpg",
        content_hash="main",
    )
    add_image(
        product,
        home,
        role=ProductMedia.Role.GALLERY,
        key="stores/1/media/gallery.jpg",
        content_hash="gallery",
    )

    response = get_products(client, user, "home")

    assert response.json()["results"] == [
        {
            "id": product.id,
            "name": "Frazada Térmica",
            "slug": "frazada-termica",
            "category": {"name": product.category.name, "slug": product.category.slug},
            "needs_main_image": False,
            "main_image": {
                "url": "https://media.example.com/stores/1/media/main.jpg",
                "thumbnail_url": (
                    "https://media.example.com/stores/1/media/renditions/main-320w-v1.webp"
                ),
                "medium_url": (
                    "https://media.example.com/stores/1/media/renditions/main-800w-v1.webp"
                ),
                "role": "main",
                "position": 1,
                "alt_text": "A blanket",
                "width": 800,
                "height": 600,
                "variant": None,
            },
        }
    ]


def test_staff_products_ignore_a_retired_main_image(client, home, user, media_base_url):
    grant_membership(user=user, store=home, role_name="content_editor")
    product = make_product(home, name="Frazada Térmica", slug="frazada-termica")
    add_image(
        product,
        home,
        role=ProductMedia.Role.MAIN,
        key="stores/1/media/retired-main.jpg",
        content_hash="retired-main",
        is_active=False,
    )

    response = get_products(client, user, "home")

    item = response.json()["results"][0]
    assert item["needs_main_image"] is True
    assert item["main_image"] is None
    assert "retired-main" not in response.content.decode()


def test_staff_product_main_images_never_come_from_another_store(client, home, anime, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    product = make_product(home, name="Home product", slug="home-product")
    other_media = make_media(anime, key="stores/2/media/anime.jpg", content_hash="anime")

    # The model refuses cross-store links; a stored row must never leak either.
    with pytest.raises(ValidationError):
        ProductMedia.objects.create(product=product, media=other_media)

    response = get_products(client, user, "home")

    assert "stores/2/media/anime.jpg" not in response.content.decode()


def test_staff_products_are_paginated(client, home, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    for index in range(3):
        make_product(home, name=f"Product {index}", slug=f"product-{index}")

    response = get_products(client, user, "home", page_size=2)

    body = response.json()
    assert body["count"] == 3
    assert body["next"] is not None
    assert [item["slug"] for item in body["results"]] == ["product-0", "product-1"]


def test_staff_product_detail_returns_the_same_shape_as_a_list_item(
    client, home, user, media_base_url
):
    grant_membership(user=user, store=home, role_name="content_editor")
    product = make_product(home, name="Frazada Térmica", slug="frazada-termica")
    add_image(
        product,
        home,
        role=ProductMedia.Role.MAIN,
        key="stores/1/media/main.jpg",
        content_hash="main",
    )

    detail = get_product(client, user, product.id)
    listing = get_products(client, user, "home")

    assert detail.status_code == 200
    assert detail.json() == listing.json()["results"][0]
    assert detail.json() == {
        "id": product.id,
        "name": "Frazada Térmica",
        "slug": "frazada-termica",
        "category": {"name": product.category.name, "slug": product.category.slug},
        "needs_main_image": False,
        "main_image": {
            "url": "https://media.example.com/stores/1/media/main.jpg",
            "thumbnail_url": (
                "https://media.example.com/stores/1/media/renditions/main-320w-v1.webp"
            ),
            "medium_url": ("https://media.example.com/stores/1/media/renditions/main-800w-v1.webp"),
            "role": "main",
            "position": 1,
            "alt_text": "A blanket",
            "width": 800,
            "height": 600,
            "variant": None,
        },
    }


def test_staff_product_detail_returns_404_for_another_stores_product_without_leaking(
    client, home, anime, user
):
    grant_membership(user=user, store=home, role_name="content_editor")
    other = make_product(anime, name="Secret Anime Product", slug="secret-anime-product")

    response = get_product(client, user, other.id, "home")

    assert_problem_details(response, status=404, code="not_found")
    assert "Secret Anime Product" not in response.content.decode()
    assert "secret-anime-product" not in response.content.decode()


def test_staff_product_detail_returns_404_for_an_inactive_product(client, home, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    product = make_product(home, name="Retired Product", slug="retired-product", is_active=False)

    response = get_product(client, user, product.id)

    assert_problem_details(response, status=404, code="not_found")
    assert "Retired Product" not in response.content.decode()


def test_staff_product_detail_returns_404_for_an_unknown_id(client, home, user):
    grant_membership(user=user, store=home, role_name="content_editor")

    response = get_product(client, user, 999999)

    assert_problem_details(response, status=404, code="not_found")


def test_staff_product_detail_requires_the_store_header(client, home, user):
    grant_membership(user=user, store=home, role_name="content_editor")
    product = make_product(home)

    response = client.get(
        STAFF_PRODUCT_DETAIL_URL.format(id=product.id),
        HTTP_AUTHORIZATION=bearer(user),
    )

    assert_problem_details(response, status=400, code="store_header_missing")


def test_staff_product_detail_requires_catalog_manage(client, home, user):
    grant_membership(user=user, store=home, role_name="warehouse")
    product = make_product(home)

    response = get_product(client, user, product.id)

    assert_problem_details(response, status=403, code="permission_denied")
