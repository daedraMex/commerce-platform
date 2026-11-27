from decimal import Decimal
from urllib.parse import quote

import pytest

from apps.catalog.models import Category, Product, ProductVariant
from apps.stores.models import Store

pytestmark = pytest.mark.django_db

SHARED_NUMBER = "5215512345678"


@pytest.fixture(autouse=True)
def shared_whatsapp_number(settings):
    settings.LABEL_WHATSAPP_NUMBER = SHARED_NUMBER


def make_store(slug="home", name="Home", **kwargs):
    return Store.objects.create(slug=slug, name=name, **kwargs)


def make_variant(store, *, sku="FRZ-00001-MAT", variant_active=True, product_active=True):
    category = Category.objects.create(
        store=store,
        name="Frazada",
        sku_code="FRZ",
        shape=Category.Shape.RECTANGLE,
        option_schema=[],
        attribute_schema=[],
    )
    product = Product.objects.create(
        store=store,
        category=category,
        name="Frazada Térmica",
        is_active=product_active,
    )
    return ProductVariant.objects.create(
        product=product,
        sku=sku,
        option_values={},
        price=Decimal("499.00"),
        cost=Decimal("200.00"),
        is_active=variant_active,
    )


def whatsapp_url(number, text):
    return f"https://wa.me/{number}?text={quote(text, safe='')}"


def test_a_known_label_redirects_to_whatsapp_with_the_encoded_text(client):
    store = make_store()
    variant = make_variant(store)

    response = client.get(f"/{store.slug}/{variant.sku}")

    assert response.status_code == 302
    assert response.url == whatsapp_url(
        SHARED_NUMBER,
        "Hola Home, me interesa FRZ-00001-MAT",
    )
    assert "%2C" in response.url


def test_the_sku_is_url_encoded_in_the_whatsapp_text(client):
    store = make_store()
    variant = make_variant(store, sku="FRZ 01")

    response = client.get(f"/{store.slug}/{quote(variant.sku, safe='')}")

    assert response.status_code == 302
    assert "FRZ%2001" in response.url
    assert "FRZ 01" not in response.url


def test_a_store_whatsapp_number_overrides_the_shared_number(client):
    store = make_store(whatsapp_number="+52 1 55 9876 5432")
    variant = make_variant(store)

    response = client.get(f"/{store.slug}/{variant.sku}")

    assert response.status_code == 302
    assert response.url == whatsapp_url(
        "5215598765432",
        "Hola Home, me interesa FRZ-00001-MAT",
    )


def test_an_unknown_store_gets_a_noindex_404_without_store_data(client):
    make_store(slug="home", name="Home")

    response = client.get("/desconocida/FRZ-00001-MAT")

    assert response.status_code == 404
    assert response["X-Robots-Tag"] == "noindex"
    body = response.content.decode()
    assert "noindex" in body
    assert "Producto no disponible" in body
    assert "Home" not in body
    assert "wa.me" not in body


def test_an_inactive_store_is_treated_as_unknown(client):
    store = make_store(slug="home", name="Tienda Oculta", is_active=False)
    variant = make_variant(store)

    response = client.get(f"/{store.slug}/{variant.sku}")

    assert response.status_code == 404
    assert response["X-Robots-Tag"] == "noindex"
    assert "Tienda Oculta" not in response.content.decode()


def test_an_unknown_sku_lists_the_known_store_and_its_contact_link(client):
    make_store(slug="home", name="Home")

    response = client.get("/home/NO-EXISTE")

    assert response.status_code == 404
    assert response["X-Robots-Tag"] == "noindex"
    body = response.content.decode()
    assert "Producto no disponible" in body
    assert "Home" in body
    assert whatsapp_url(SHARED_NUMBER, "Hola Home") in body
    assert "NO-EXISTE" not in body


def test_a_known_store_does_not_answer_another_stores_sku(client):
    make_store(slug="home", name="Home")
    anime = make_store(slug="anime", name="Anime")
    make_variant(anime, sku="ANM-00001")

    response = client.get("/home/ANM-00001")

    assert response.status_code == 404
    assert "Anime" not in response.content.decode()


@pytest.mark.parametrize(
    "variant_options",
    [
        {"variant_active": False},
        {"product_active": False},
    ],
)
def test_an_inactive_sku_gets_the_friendly_404(client, variant_options):
    store = make_store()
    make_variant(store, **variant_options)

    response = client.get(f"/{store.slug}/FRZ-00001-MAT")

    assert response.status_code == 404
    assert response["X-Robots-Tag"] == "noindex"
    assert "Producto no disponible" in response.content.decode()


def test_an_inactive_category_gets_the_friendly_404(client):
    store = make_store()
    variant = make_variant(store)
    variant.product.category.is_active = False
    variant.product.category.save()

    response = client.get(f"/{store.slug}/{variant.sku}")

    assert response.status_code == 404
    assert response["X-Robots-Tag"] == "noindex"


def test_a_label_without_any_configured_number_gets_the_friendly_404(client, settings):
    settings.LABEL_WHATSAPP_NUMBER = ""
    store = make_store()
    make_variant(store)

    response = client.get("/home/FRZ-00001-MAT")

    assert response.status_code == 404
    assert response["X-Robots-Tag"] == "noindex"
