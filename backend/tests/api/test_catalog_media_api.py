from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.catalog.models import (
    Category,
    Design,
    Media,
    Product,
    ProductMedia,
    ProductVariant,
    Supplier,
)
from apps.stores.models import Store

pytestmark = pytest.mark.django_db

PRODUCTS_URL = "/api/v1/catalog/products/"
VARIANTS_URL = "/api/v1/catalog/variants/{sku}/"

SIZE_OPTION = [
    {
        "code": "size",
        "label": "Size",
        "values": [{"code": "MAT", "label": "Matrimonial", "width_cm": 210, "height_cm": 160}],
    }
]


@pytest.fixture
def media_base_url(settings):
    settings.MEDIA_BASE_URL = "https://media.example.com"
    return settings.MEDIA_BASE_URL


def make_store(slug):
    return Store.objects.create(slug=slug, name=slug.title())


def make_category(store):
    return Category.objects.create(
        store=store,
        name="Frazada",
        slug=f"frazada-{Category.objects.count()}",
        sku_code="FRZ",
        shape=Category.Shape.RECTANGLE,
        option_schema=SIZE_OPTION,
    )


def make_product(store, *, category=None, design=None, name="Frazada Térmica", slug=None):
    if category is None:
        category = Category.objects.filter(store=store).first() or make_category(store)
    if design is None:
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
    )


def make_variant(product):
    return ProductVariant.objects.create(
        product=product,
        option_values={"size": "MAT"},
        price=Decimal("499.00"),
        cost=Decimal("200.00"),
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


def detail_url(product):
    return f"{PRODUCTS_URL}{product.slug}/"


def test_product_detail_returns_its_images(client, media_base_url):
    home = make_store("home")
    category = make_category(home)
    product = make_product(home, category=category)
    variant = make_variant(product)
    main = make_media(
        home,
        key="stores/1/media/main.jpg",
        content_hash="main",
        alt_text="The main photo",
    )
    gallery = make_media(home, key="stores/1/media/gallery.jpg", content_hash="gallery")
    ProductMedia.objects.create(product=product, media=main, role=ProductMedia.Role.MAIN)
    ProductMedia.objects.create(
        product=product,
        variant=variant,
        media=gallery,
        role=ProductMedia.Role.GALLERY,
        position=2,
    )

    response = client.get(detail_url(product), HTTP_X_STORE="home")

    assert response.status_code == 200
    assert response.json()["images"] == [
        {
            "url": "https://media.example.com/stores/1/media/main.jpg",
            "role": "main",
            "position": 1,
            "alt_text": "The main photo",
            "width": 800,
            "height": 600,
            "variant": None,
        },
        {
            "url": "https://media.example.com/stores/1/media/gallery.jpg",
            "role": "gallery",
            "position": 2,
            "alt_text": "A blanket",
            "width": 800,
            "height": 600,
            "variant": variant.sku,
        },
    ]


def test_product_detail_is_empty_images_when_there_are_none(client, media_base_url):
    home = make_store("home")
    product = make_product(home)
    make_variant(product)

    response = client.get(detail_url(product), HTTP_X_STORE="home")

    assert response.json()["images"] == []


def test_product_detail_never_returns_images_of_another_store(client, media_base_url):
    home = make_store("home")
    anime = make_store("anime")
    product = make_product(home)
    make_variant(product)
    other_media = make_media(anime, key="stores/2/media/other.jpg", content_hash="other")
    with pytest.raises(ValidationError):
        ProductMedia.objects.create(product=product, media=other_media)

    response = client.get(detail_url(product), HTTP_X_STORE="home")

    assert response.json()["images"] == []


def test_the_variant_lookup_returns_the_products_main_image(client, media_base_url):
    home = make_store("home")
    product = make_product(home)
    variant = make_variant(product)
    main = make_media(home, key="stores/1/media/main.jpg", content_hash="main")
    ProductMedia.objects.create(product=product, media=main, role=ProductMedia.Role.MAIN)

    response = client.get(
        VARIANTS_URL.format(sku=variant.sku),
        HTTP_X_STORE="home",
    )

    assert response.status_code == 200
    assert response.json()["product"]["main_image"] == {
        "url": "https://media.example.com/stores/1/media/main.jpg",
        "role": "main",
        "position": 1,
        "alt_text": "A blanket",
        "width": 800,
        "height": 600,
        "variant": None,
    }


def test_the_variant_lookup_returns_a_null_main_image_without_one(client, media_base_url):
    home = make_store("home")
    product = make_product(home)
    variant = make_variant(product)

    response = client.get(VARIANTS_URL.format(sku=variant.sku), HTTP_X_STORE="home")

    assert response.status_code == 200
    assert response.json()["product"]["main_image"] is None


def test_product_detail_query_count_does_not_grow_with_images(
    client, django_assert_max_num_queries
):
    home = make_store("home")
    category = make_category(home)
    product = make_product(home, category=category)
    make_variant(product)
    for index in range(5):
        media = make_media(
            home,
            key=f"stores/1/media/{index}.jpg",
            content_hash=str(index),
        )
        ProductMedia.objects.create(product=product, media=media, role=ProductMedia.Role.GALLERY)

    with django_assert_max_num_queries(5):
        response = client.get(detail_url(product), HTTP_X_STORE="home")

    assert len(response.json()["images"]) == 5


def test_product_list_query_count_does_not_grow_with_images(client, django_assert_max_num_queries):
    home = make_store("home")
    category = make_category(home)
    for index in range(5):
        product = make_product(home, category=category, name=f"Product {index}")
        make_variant(product)
        media = make_media(
            home,
            key=f"stores/1/media/{index}.jpg",
            content_hash=str(index),
        )
        ProductMedia.objects.create(product=product, media=media, role=ProductMedia.Role.MAIN)

    with django_assert_max_num_queries(4):
        response = client.get(PRODUCTS_URL, {"page_size": 5}, HTTP_X_STORE="home")

    assert response.json()["count"] == 5
