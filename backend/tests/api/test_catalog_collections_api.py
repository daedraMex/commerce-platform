from decimal import Decimal

import pytest

from apps.catalog.models import (
    Category,
    Collection,
    CollectionProduct,
    Design,
    Product,
    ProductVariant,
    Supplier,
)
from apps.stores.models import Store
from tests.api.helpers import assert_problem_details

pytestmark = pytest.mark.django_db

COLLECTIONS_URL = "/api/v1/catalog/collections/"
PRODUCTS_URL = "/api/v1/catalog/products/"

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


def make_category(store, *, name="Frazada", slug="frazada", sku_code="FRZ"):
    return Category.objects.create(
        store=store,
        name=name,
        slug=slug,
        sku_code=sku_code,
        shape=Category.Shape.RECTANGLE,
        option_schema=SIZE_OPTION,
    )


def make_product(store, *, name="Frazada Térmica", category=None):
    category = category or Category.objects.filter(store=store).first() or make_category(store)
    design = Design.objects.create(
        store=store,
        name=name,
        supplier=Supplier.objects.create(store=store, name=f"Supplier {name}"),
        supplier_design_name=name,
    )
    product = Product.objects.create(store=store, category=category, design=design, name=name)
    ProductVariant.objects.create(
        product=product,
        option_values={"size": "MAT"},
        price=Decimal("499.00"),
        cost=Decimal("200.00"),
    )
    return product


def detail_url(product):
    return f"{PRODUCTS_URL}{product.slug}/"


def test_collections_are_anonymous_and_store_scoped(client, home, anime):
    Collection.objects.create(store=home, name="Halloween 2026")
    Collection.objects.create(store=anime, name="Artistas Asiáticos 2025")

    home_response = client.get(COLLECTIONS_URL, HTTP_X_STORE="home")
    anime_response = client.get(COLLECTIONS_URL, HTTP_X_STORE="anime")

    assert home_response.status_code == 200
    assert [collection["name"] for collection in home_response.json()] == ["Halloween 2026"]
    assert [collection["name"] for collection in anime_response.json()] == [
        "Artistas Asiáticos 2025"
    ]


def test_collections_show_their_public_fields(client, home):
    Collection.objects.create(
        store=home,
        name="Halloween 2026",
        description="Seasonal blankets.",
    )

    response = client.get(COLLECTIONS_URL, HTTP_X_STORE="home")

    assert response.json() == [
        {
            "name": "Halloween 2026",
            "slug": "halloween-2026",
            "description": "Seasonal blankets.",
        }
    ]


def test_inactive_collections_are_not_listed(client, home):
    Collection.objects.create(store=home, name="Halloween 2026")
    Collection.objects.create(store=home, name="Hidden", is_active=False)

    response = client.get(COLLECTIONS_URL, HTTP_X_STORE="home")

    assert [collection["name"] for collection in response.json()] == ["Halloween 2026"]


def test_collections_report_the_store_header_errors(client):
    assert_problem_details(
        client.get(COLLECTIONS_URL),
        status=400,
        code="store_header_missing",
    )
    assert_problem_details(
        client.get(COLLECTIONS_URL, HTTP_X_STORE="Not A Slug"),
        status=400,
        code="store_header_invalid",
    )
    assert_problem_details(
        client.get(COLLECTIONS_URL, HTTP_X_STORE="missing"),
        status=400,
        code="store_not_found",
    )


def test_collections_never_expose_their_supplier(client, home):
    supplier = Supplier.objects.create(store=home, name="Beka Textiles")
    Collection.objects.create(store=home, name="Halloween 2026", supplier=supplier)

    body = client.get(COLLECTIONS_URL, HTTP_X_STORE="home").content.decode()

    assert "Beka Textiles" not in body
    assert "supplier" not in body


def test_product_list_filters_by_collection_in_its_curated_order(client, home):
    first = make_product(home, name="First")
    second = make_product(home, name="Second")
    third = make_product(home, name="Third")
    collection = Collection.objects.create(store=home, name="Halloween 2026")
    for product, position in ((second, 1), (third, 2), (first, 3)):
        CollectionProduct.objects.create(collection=collection, product=product, position=position)

    response = client.get(PRODUCTS_URL, {"collection": "halloween-2026"}, HTTP_X_STORE="home")

    assert [item["name"] for item in response.json()["results"]] == [
        "Second",
        "Third",
        "First",
    ]


def test_product_list_ignores_collections_of_another_store(client, home, anime):
    home_product = make_product(home, name="Home product")
    anime_product = make_product(anime, name="Anime product")
    home_collection = Collection.objects.create(store=home, name="Halloween 2026")
    anime_collection = Collection.objects.create(store=anime, name="Halloween 2026")
    CollectionProduct.objects.create(collection=home_collection, product=home_product, position=1)
    CollectionProduct.objects.create(collection=anime_collection, product=anime_product, position=1)

    response = client.get(PRODUCTS_URL, {"collection": "halloween-2026"}, HTTP_X_STORE="home")

    assert response.status_code == 200
    assert [item["slug"] for item in response.json()["results"]] == [home_product.slug]

    response = client.get(PRODUCTS_URL, {"collection": "halloween-2026"}, HTTP_X_STORE="anime")

    assert [item["slug"] for item in response.json()["results"]] == [anime_product.slug]


def test_filtering_by_an_inactive_collection_returns_no_products(client, home):
    product = make_product(home)
    collection = Collection.objects.create(store=home, name="Halloween 2026", is_active=False)
    CollectionProduct.objects.create(collection=collection, product=product, position=1)

    response = client.get(PRODUCTS_URL, {"collection": "halloween-2026"}, HTTP_X_STORE="home")

    assert response.status_code == 200
    assert response.json()["results"] == []


def test_an_inactive_collections_products_stay_visible_elsewhere(client, home):
    product = make_product(home)
    collection = Collection.objects.create(store=home, name="Halloween 2026", is_active=False)
    CollectionProduct.objects.create(collection=collection, product=product, position=1)

    unfiltered = client.get(PRODUCTS_URL, HTTP_X_STORE="home")
    detail = client.get(detail_url(product), HTTP_X_STORE="home")

    assert [item["slug"] for item in unfiltered.json()["results"]] == [product.slug]
    assert detail.status_code == 200
    assert detail.json()["collections"] == []


def test_product_detail_lists_only_active_collections(client, home):
    product = make_product(home)
    active = Collection.objects.create(
        store=home, name="Halloween 2026", description="Seasonal blankets."
    )
    inactive = Collection.objects.create(store=home, name="Retired 2025", is_active=False)
    CollectionProduct.objects.create(collection=active, product=product, position=2)
    CollectionProduct.objects.create(collection=inactive, product=product, position=1)

    response = client.get(detail_url(product), HTTP_X_STORE="home")

    assert response.json()["collections"] == [
        {
            "name": "Halloween 2026",
            "slug": "halloween-2026",
            "description": "Seasonal blankets.",
        }
    ]


def test_product_detail_never_exposes_a_collection_supplier(client, home):
    supplier = Supplier.objects.create(store=home, name="Beka Textiles")
    product = make_product(home)
    collection = Collection.objects.create(store=home, name="Halloween 2026", supplier=supplier)
    CollectionProduct.objects.create(collection=collection, product=product, position=1)

    body = client.get(detail_url(product), HTTP_X_STORE="home").content.decode()

    assert "Beka Textiles" not in body
    assert "supplier" not in body


def test_product_list_query_count_does_not_grow_with_collections(
    client, home, django_assert_max_num_queries
):
    collection = Collection.objects.create(store=home, name="Halloween 2026")
    products = [make_product(home, name=f"Product {index}") for index in range(5)]
    for position, product in enumerate(products, start=1):
        CollectionProduct.objects.create(collection=collection, product=product, position=position)

    with django_assert_max_num_queries(4):
        response = client.get(
            PRODUCTS_URL,
            {"collection": "halloween-2026", "page_size": 5},
            HTTP_X_STORE="home",
        )

    assert response.json()["count"] == 5

    more = [make_product(home, name=f"More {index}") for index in range(45)]
    for position, product in enumerate(more, start=len(products) + 1):
        CollectionProduct.objects.create(collection=collection, product=product, position=position)

    with django_assert_max_num_queries(4):
        response = client.get(
            PRODUCTS_URL,
            {"collection": "halloween-2026", "page_size": 50},
            HTTP_X_STORE="home",
        )

    assert response.json()["count"] == 50


def test_product_detail_query_count_does_not_grow_with_collections(
    client, home, django_assert_max_num_queries
):
    product = make_product(home)
    for index in range(50):
        collection = Collection.objects.create(store=home, name=f"Collection {index}")
        CollectionProduct.objects.create(collection=collection, product=product, position=index)

    with django_assert_max_num_queries(4):
        response = client.get(detail_url(product), HTTP_X_STORE="home")

    assert len(response.json()["collections"]) == 50


def test_product_detail_ignores_a_collection_that_moved_to_another_store(client, home, anime):
    product = make_product(home)
    collection = Collection.objects.create(store=home, name="Halloween 2026")
    CollectionProduct.objects.create(collection=collection, product=product, position=1)
    Collection.objects.filter(pk=collection.pk).update(store=anime)

    response = client.get(detail_url(product), HTTP_X_STORE="home")

    assert response.status_code == 200
    assert response.json()["collections"] == []
