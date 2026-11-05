from decimal import Decimal

import pytest

from apps.catalog.models import Category, Design, Product, ProductVariant, Supplier
from apps.stores.models import Store
from tests.api.helpers import assert_problem_details

pytestmark = pytest.mark.django_db

CATEGORIES_URL = "/api/v1/catalog/categories/"
PRODUCTS_URL = "/api/v1/catalog/products/"
VARIANTS_URL = "/api/v1/catalog/variants/{sku}/"

SIZE_OPTION = [
    {
        "code": "size",
        "label": "Size",
        "values": [
            {
                "code": "IND",
                "label": "Individual / Personal / Viajera",
                "width_cm": 110,
                "height_cm": 160,
            },
            {
                "code": "MAT",
                "label": "Matrimonial",
                "width_cm": 210,
                "height_cm": 160,
            },
        ],
    }
]

ATTRIBUTE_SCHEMA = [
    {
        "code": "material",
        "label": "Material",
        "type": "text",
        "choices": [],
        "required": True,
    }
]


@pytest.fixture
def home():
    return Store.objects.create(slug="home", name="Home")


@pytest.fixture
def anime():
    return Store.objects.create(slug="anime", name="Anime")


def make_category(
    store,
    *,
    name="Frazada",
    sku_code="FRZ",
    option_schema=None,
    attribute_schema=None,
    is_active=True,
):
    return Category.objects.create(
        store=store,
        name=name,
        sku_code=sku_code,
        shape=Category.Shape.RECTANGLE,
        option_schema=SIZE_OPTION if option_schema is None else option_schema,
        attribute_schema=ATTRIBUTE_SCHEMA if attribute_schema is None else attribute_schema,
        is_active=is_active,
    )


def make_design(store, *, name="Térmica", number=None, supplier=None):
    supplier = supplier or Supplier.objects.create(store=store, name="Beka")
    design = Design.objects.create(
        store=store,
        name=name,
        supplier=supplier,
        supplier_design_name=f"{name} {Design.objects.count()}",
    )
    if number is not None:
        Design.objects.filter(pk=design.pk).update(number=number)
        design.refresh_from_db()
    return design


def make_product(
    store,
    *,
    category=None,
    design=None,
    name="",
    description="",
    attributes=None,
    is_active=True,
):
    category = category or Category.objects.filter(store=store).first() or make_category(store)
    design = design or make_design(store)
    return Product.objects.create(
        store=store,
        category=category,
        design=design,
        name=name,
        description=description,
        attributes={"material": "Flannel premier"} if attributes is None else attributes,
        is_active=is_active,
    )


def make_variant(
    product,
    *,
    option_values=None,
    price="499.00",
    compare_at_price=None,
    cost="200.00",
    is_active=True,
):
    return ProductVariant.objects.create(
        product=product,
        option_values={"size": "MAT"} if option_values is None else option_values,
        price=Decimal(price),
        compare_at_price=None if compare_at_price is None else Decimal(compare_at_price),
        cost=Decimal(cost),
        is_active=is_active,
    )


def test_categories_are_anonymous_and_store_scoped(client, home, anime):
    make_category(home, name="Frazada", sku_code="FRZ")
    make_category(anime, name="Anime Card", sku_code="CRD", option_schema=[])

    response = client.get(CATEGORIES_URL, HTTP_X_STORE="home")

    assert response.status_code == 200
    assert [category["name"] for category in response.json()] == ["Frazada"]

    response = client.get(CATEGORIES_URL, HTTP_X_STORE="anime")

    assert [category["name"] for category in response.json()] == ["Anime Card"]


def test_categories_include_their_option_definitions(client, home):
    make_category(home)

    response = client.get(CATEGORIES_URL, HTTP_X_STORE="home")

    assert response.status_code == 200
    assert response.json() == [
        {
            "name": "Frazada",
            "slug": "frazada",
            "sku_code": "FRZ",
            "shape": "rectangle",
            "options": [
                {
                    "code": "size",
                    "label": "Size",
                    "values": [
                        {
                            "code": "IND",
                            "label": "Individual / Personal / Viajera",
                            "width_cm": 110.0,
                            "height_cm": 160.0,
                        },
                        {
                            "code": "MAT",
                            "label": "Matrimonial",
                            "width_cm": 210.0,
                            "height_cm": 160.0,
                        },
                    ],
                }
            ],
        }
    ]


def test_inactive_categories_are_not_listed(client, home):
    make_category(home, name="Frazada", sku_code="FRZ")
    make_category(home, name="Hidden", sku_code="HID", option_schema=[], is_active=False)

    response = client.get(CATEGORIES_URL, HTTP_X_STORE="home")

    assert [category["name"] for category in response.json()] == ["Frazada"]


def test_categories_report_the_store_header_errors(client):
    assert_problem_details(
        client.get(CATEGORIES_URL),
        status=400,
        code="store_header_missing",
    )
    assert_problem_details(
        client.get(CATEGORIES_URL, HTTP_X_STORE="Not A Slug"),
        status=400,
        code="store_header_invalid",
    )
    assert_problem_details(
        client.get(CATEGORIES_URL, HTTP_X_STORE="missing"),
        status=400,
        code="store_not_found",
    )


def test_product_list_is_anonymous_and_store_scoped(client, home, anime):
    home_product = make_product(home)
    make_variant(home_product)
    anime_product = make_product(anime)
    make_variant(anime_product)

    response = client.get(PRODUCTS_URL, HTTP_X_STORE="home")

    assert response.status_code == 200
    assert [item["slug"] for item in response.json()["results"]] == [home_product.slug]

    response = client.get(PRODUCTS_URL, HTTP_X_STORE="anime")

    assert [item["slug"] for item in response.json()["results"]] == [anime_product.slug]


def test_product_list_shows_the_public_fields_with_labels(client, home):
    category = make_category(home)
    design = make_design(home, name="Térmica", number=12)
    product = make_product(home, category=category, design=design)
    make_variant(product, price="499.00", compare_at_price="699.00")

    response = client.get(PRODUCTS_URL, HTTP_X_STORE="home")

    assert response.json()["results"] == [
        {
            "name": "Frazada Térmica",
            "slug": "frazada-termica",
            "category": {"name": "Frazada", "slug": "frazada"},
            "attributes": [
                {
                    "code": "material",
                    "label": "Material",
                    "type": "text",
                    "value": "Flannel premier",
                }
            ],
            "variants": [
                {
                    "sku": "FRZ-00012-MAT",
                    "options": [
                        {
                            "code": "size",
                            "label": "Size",
                            "value": {
                                "code": "MAT",
                                "label": "Matrimonial",
                                "width_cm": 210.0,
                                "height_cm": 160.0,
                            },
                        }
                    ],
                    "price": "499.00",
                    "compare_at_price": "699.00",
                }
            ],
        }
    ]


def test_product_list_hides_inactive_products_categories_and_variants(client, home):
    visible = make_product(home, name="Visible product")
    make_variant(visible)

    inactive_product = make_product(home, name="Inactive product", is_active=False)
    make_variant(inactive_product)

    inactive_category = make_category(
        home, name="Retired", sku_code="RET", option_schema=[], attribute_schema=[]
    )
    inactive_category.is_active = False
    inactive_category.save()
    product_in_inactive_category = make_product(
        home, category=inactive_category, name="Retired product", attributes={}
    )
    make_variant(product_in_inactive_category, option_values={})

    no_active_variants = make_product(home, name="Sold out product")
    make_variant(no_active_variants, is_active=False)

    response = client.get(PRODUCTS_URL, HTTP_X_STORE="home")

    assert [item["name"] for item in response.json()["results"]] == ["Visible product"]


def test_product_list_leaves_out_inactive_variants_of_a_visible_product(client, home):
    product = make_product(home)
    make_variant(product, option_values={"size": "MAT"})
    make_variant(product, option_values={"size": "IND"}, is_active=False)

    response = client.get(PRODUCTS_URL, HTTP_X_STORE="home")

    variants = response.json()["results"][0]["variants"]
    assert [variant["sku"] for variant in variants] == ["FRZ-00001-MAT"]


def test_product_list_filters_by_category_slug(client, home):
    frazada = make_category(home, name="Frazada", sku_code="FRZ")
    almohada = make_category(
        home, name="Almohada", sku_code="ALM", option_schema=[], attribute_schema=[]
    )
    frazada_product = make_product(home, category=frazada, name="Frazada product")
    make_variant(frazada_product)
    almohada_product = make_product(home, category=almohada, name="Almohada product", attributes={})
    make_variant(almohada_product, option_values={})

    response = client.get(PRODUCTS_URL, {"category": "almohada"}, HTTP_X_STORE="home")

    assert [item["slug"] for item in response.json()["results"]] == [almohada_product.slug]


def test_product_list_searches_names_ignoring_case_and_accents(client, home):
    category = make_category(home, name="Frazada", sku_code="FRZ")
    product = make_product(home, category=category, design=make_design(home, name="Térmica"))
    make_variant(product)
    other = make_product(home, name="Frazada Invierno")
    make_variant(other)

    response = client.get(PRODUCTS_URL, {"search": "frazada termica"}, HTTP_X_STORE="home")

    assert [item["slug"] for item in response.json()["results"]] == [product.slug]

    response = client.get(PRODUCTS_URL, {"search": "FRAZADA TÉRMICA"}, HTTP_X_STORE="home")

    assert [item["slug"] for item in response.json()["results"]] == [product.slug]


def test_product_list_is_ordered_newest_first(client, home):
    first = make_product(home, name="First")
    make_variant(first)
    second = make_product(home, name="Second")
    make_variant(second)
    third = make_product(home, name="Third")
    make_variant(third)

    Product.objects.filter(pk=first.pk).update(created_at="2026-01-01T00:00:00Z")
    Product.objects.filter(pk=second.pk).update(created_at="2026-02-01T00:00:00Z")
    Product.objects.filter(pk=third.pk).update(created_at="2026-03-01T00:00:00Z")

    response = client.get(PRODUCTS_URL, HTTP_X_STORE="home")

    assert [item["name"] for item in response.json()["results"]] == [
        "Third",
        "Second",
        "First",
    ]


def test_product_list_is_paginated_newest_first(client, home):
    for index in range(3):
        product = make_product(home, name=f"Product {index}")
        make_variant(product)
        Product.objects.filter(pk=product.pk).update(created_at=f"2026-0{index + 1}-01T00:00:00Z")

    response = client.get(PRODUCTS_URL, {"page_size": 2}, HTTP_X_STORE="home")

    body = response.json()
    assert body["count"] == 3
    assert body["next"] is not None
    assert [item["name"] for item in body["results"]] == ["Product 2", "Product 1"]


def test_product_list_reports_the_store_header_errors(client):
    assert_problem_details(
        client.get(PRODUCTS_URL),
        status=400,
        code="store_header_missing",
    )
    assert_problem_details(
        client.get(PRODUCTS_URL, HTTP_X_STORE="Not A Slug"),
        status=400,
        code="store_header_invalid",
    )
    assert_problem_details(
        client.get(PRODUCTS_URL, HTTP_X_STORE="missing"),
        status=400,
        code="store_not_found",
    )


def detail_url(product):
    return f"{PRODUCTS_URL}{product.slug}/"


def test_product_detail_is_anonymous_and_store_scoped(client, home, anime):
    category = make_category(home)
    product = make_product(home, category=category, description="Soft and warm.")
    make_variant(product)
    anime_product = make_product(anime, name="Anime blanket")
    make_variant(anime_product)

    response = client.get(detail_url(product), HTTP_X_STORE="home")

    assert response.status_code == 200
    assert response.json()["slug"] == product.slug
    assert response.json()["description"] == "Soft and warm."

    assert_problem_details(
        client.get(detail_url(product), HTTP_X_STORE="anime"),
        status=404,
        code="not_found",
    )


def test_product_detail_shows_attributes_with_labels_and_active_variants(client, home):
    category = make_category(home)
    design = make_design(home, name="Térmica", number=12)
    product = make_product(home, category=category, design=design, description="Warm.")
    make_variant(product, option_values={"size": "MAT"})
    make_variant(product, option_values={"size": "IND"}, is_active=False)

    response = client.get(detail_url(product), HTTP_X_STORE="home")

    assert response.json() == {
        "name": "Frazada Térmica",
        "slug": "frazada-termica",
        "description": "Warm.",
        "category": {"name": "Frazada", "slug": "frazada"},
        "collections": [],
        "attributes": [
            {
                "code": "material",
                "label": "Material",
                "type": "text",
                "value": "Flannel premier",
            }
        ],
        "variants": [
            {
                "sku": "FRZ-00012-MAT",
                "options": [
                    {
                        "code": "size",
                        "label": "Size",
                        "value": {
                            "code": "MAT",
                            "label": "Matrimonial",
                            "width_cm": 210.0,
                            "height_cm": 160.0,
                        },
                    }
                ],
                "price": "499.00",
                "compare_at_price": None,
            }
        ],
    }


@pytest.mark.parametrize("case", ["inactive_product", "inactive_category", "no_active_variant"])
def test_product_detail_is_404_when_not_visible(client, home, case):
    category = make_category(home)
    product = make_product(home, category=category)
    variant = make_variant(product)

    if case == "inactive_product":
        product.is_active = False
        product.save()
    elif case == "inactive_category":
        category.is_active = False
        category.save()
    else:
        variant.is_active = False
        variant.save()

    assert_problem_details(
        client.get(detail_url(product), HTTP_X_STORE="home"),
        status=404,
        code="not_found",
    )


def test_product_detail_is_404_for_an_unknown_slug(client, home):
    assert_problem_details(
        client.get(f"{PRODUCTS_URL}missing/", HTTP_X_STORE="home"),
        status=404,
        code="not_found",
    )


def test_product_detail_reports_the_store_header_errors(client, home):
    product = make_product(home)
    make_variant(product)

    assert_problem_details(
        client.get(detail_url(product)),
        status=400,
        code="store_header_missing",
    )
    assert_problem_details(
        client.get(detail_url(product), HTTP_X_STORE="Not A Slug"),
        status=400,
        code="store_header_invalid",
    )
    assert_problem_details(
        client.get(detail_url(product), HTTP_X_STORE="missing"),
        status=400,
        code="store_not_found",
    )


def variant_url(sku):
    return VARIANTS_URL.format(sku=sku)


def test_variant_lookup_returns_the_variant_and_its_product_summary(client, home):
    category = make_category(home)
    design = make_design(home, name="Térmica", number=12)
    product = make_product(home, category=category, design=design)
    make_variant(product, price="499.00", compare_at_price="699.00")

    response = client.get(variant_url("FRZ-00012-MAT"), HTTP_X_STORE="home")

    assert response.status_code == 200
    assert response.json() == {
        "sku": "FRZ-00012-MAT",
        "options": [
            {
                "code": "size",
                "label": "Size",
                "value": {
                    "code": "MAT",
                    "label": "Matrimonial",
                    "width_cm": 210.0,
                    "height_cm": 160.0,
                },
            }
        ],
        "price": "499.00",
        "compare_at_price": "699.00",
        "product": {"name": "Frazada Térmica", "slug": "frazada-termica"},
    }


def test_variant_lookup_ignores_case(client, home):
    product = make_product(home)
    make_variant(product)

    response = client.get(variant_url("frz-00001-mat"), HTTP_X_STORE="home")

    assert response.status_code == 200
    assert response.json()["sku"] == "FRZ-00001-MAT"


def test_variant_lookup_is_store_scoped(client, home, anime):
    home_product = make_product(home)
    make_variant(home_product)
    anime_product = make_product(anime, name="Anime blanket", design=make_design(anime, number=2))
    anime_variant = make_variant(anime_product)

    assert_problem_details(
        client.get(variant_url(anime_variant.sku), HTTP_X_STORE="home"),
        status=404,
        code="not_found",
    )
    assert_problem_details(
        client.get(variant_url("FRZ-00001-MAT"), HTTP_X_STORE="anime"),
        status=404,
        code="not_found",
    )


@pytest.mark.parametrize("case", ["inactive_variant", "inactive_product", "inactive_category"])
def test_variant_lookup_is_404_when_not_visible(client, home, case):
    category = make_category(home)
    product = make_product(home, category=category)
    variant = make_variant(product)

    if case == "inactive_variant":
        variant.is_active = False
        variant.save()
    elif case == "inactive_product":
        product.is_active = False
        product.save()
    else:
        category.is_active = False
        category.save()

    assert_problem_details(
        client.get(variant_url(variant.sku), HTTP_X_STORE="home"),
        status=404,
        code="not_found",
    )


def test_variant_lookup_is_404_for_an_unknown_sku(client, home):
    assert_problem_details(
        client.get(variant_url("NOPE-00001-X"), HTTP_X_STORE="home"),
        status=404,
        code="not_found",
    )


def test_variant_lookup_reports_the_store_header_errors(client, home):
    product = make_product(home)
    variant = make_variant(product)

    assert_problem_details(
        client.get(variant_url(variant.sku)),
        status=400,
        code="store_header_missing",
    )
    assert_problem_details(
        client.get(variant_url(variant.sku), HTTP_X_STORE="Not A Slug"),
        status=400,
        code="store_header_invalid",
    )
    assert_problem_details(
        client.get(variant_url(variant.sku), HTTP_X_STORE="missing"),
        status=400,
        code="store_not_found",
    )


def test_no_public_payload_exposes_cost_or_supplier_data(client, home):
    supplier = Supplier.objects.create(store=home, name="Beka Textiles")
    design = make_design(
        home,
        name="Térmica",
        number=12,
        supplier=supplier,
    )
    design.supplier_design_name = "STRAYKIDS AZULCLARO"
    design.save()
    category = make_category(home)
    product = make_product(home, category=category, design=design)
    variant = make_variant(product, cost="200.00")

    bodies = [
        client.get(CATEGORIES_URL, HTTP_X_STORE="home").content.decode(),
        client.get(PRODUCTS_URL, HTTP_X_STORE="home").content.decode(),
        client.get(detail_url(product), HTTP_X_STORE="home").content.decode(),
        client.get(variant_url(variant.sku), HTTP_X_STORE="home").content.decode(),
    ]

    for body in bodies:
        for secret in ("Beka Textiles", "STRAYKIDS AZULCLARO", "supplier", "cost", "200.00"):
            assert secret not in body


def _make_products(home, count):
    category = Category.objects.filter(store=home).first() or make_category(home)
    start = Product.objects.filter(store=home).count()
    for index in range(start, start + count):
        product = make_product(
            home,
            category=category,
            design=make_design(home, name=f"Design {index}"),
            name=f"Product {index}",
        )
        make_variant(product)


def test_product_list_query_count_does_not_grow_with_the_catalogue(
    client, home, django_assert_max_num_queries
):
    _make_products(home, 5)

    with django_assert_max_num_queries(4):
        response = client.get(PRODUCTS_URL, {"page_size": 5}, HTTP_X_STORE="home")

    assert response.json()["count"] == 5

    _make_products(home, 45)

    with django_assert_max_num_queries(4):
        response = client.get(PRODUCTS_URL, {"page_size": 50}, HTTP_X_STORE="home")

    assert response.json()["count"] == 50


def test_product_detail_query_count_does_not_grow_with_variants(
    client, home, django_assert_max_num_queries
):
    category = make_category(home)
    product = make_product(home, category=category)
    make_variant(product, option_values={"size": "MAT"})
    make_variant(product, option_values={"size": "IND"})

    with django_assert_max_num_queries(4):
        response = client.get(detail_url(product), HTTP_X_STORE="home")

    assert len(response.json()["variants"]) == 2
