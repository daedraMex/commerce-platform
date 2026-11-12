from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command

from apps.catalog.management.commands import seed_demo
from apps.catalog.models import (
    Category,
    Collection,
    Design,
    Media,
    Product,
    ProductVariant,
    Supplier,
)
from apps.stores.models import Store

pytestmark = pytest.mark.django_db


def make_store(slug="home", name=None, *, is_active=True):
    return Store.objects.create(slug=slug, name=name or slug.title(), is_active=is_active)


def make_superuser(email="operator@example.com", *, is_active=True, is_superuser=True):
    return get_user_model().objects.create_user(
        email=email,
        password="s3cret-pass",
        is_active=is_active,
        is_superuser=is_superuser,
        is_staff=is_superuser,
    )


def run_seed(*, store="home", operator="operator@example.com"):
    stdout = StringIO()
    call_command("seed_demo", store=store, operator=operator, stdout=stdout)
    return stdout.getvalue()


def catalog_counts(store):
    return {
        "categories": Category.objects.filter(store=store).count(),
        "products": Product.objects.filter(store=store).count(),
        "variants": ProductVariant.objects.filter(store=store).count(),
        "designs": Design.objects.filter(store=store).count(),
        "suppliers": Supplier.objects.filter(store=store).count(),
        "collections": Collection.objects.filter(store=store).count(),
        "media": Media.objects.filter(store=store).count(),
    }


def test_seed_demo_loads_a_demo_catalog_into_an_existing_store(settings):
    settings.DEBUG = True
    home = make_store("home", "Home")
    make_superuser()

    output = run_seed()

    assert Store.objects.count() == 1
    assert Category.objects.filter(store=home).count() >= 2
    products = Product.objects.filter(store=home)
    assert products.count() >= 5
    assert all(product.variants.exists() for product in products)
    variants = ProductVariant.objects.filter(store=home)
    assert variants.exists()
    assert all(variant.price > 0 for variant in variants)
    assert Collection.objects.filter(store=home).exists()
    assert not Media.objects.filter(store=home).exists()
    assert "Rows created" in output


def test_seed_demo_works_without_photos_or_private_media(settings, tmp_path):
    settings.DEBUG = True
    settings.STORAGES = {
        **settings.STORAGES,
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": tmp_path},
        },
    }
    make_store("home", "Home")
    make_superuser()

    run_seed()

    assert Product.objects.filter(store__slug="home").count() >= 5
    assert not Media.objects.exists()
    assert list(tmp_path.rglob("*")) == []


def test_seed_demo_is_idempotent(settings):
    settings.DEBUG = True
    home = make_store("home", "Home")
    make_superuser()

    run_seed()
    first = catalog_counts(home)

    output = run_seed()
    second = catalog_counts(home)

    assert second == first
    assert first["categories"] >= 2
    assert first["products"] >= 5
    assert first["variants"] > 0
    assert "Rows unchanged" in output


def test_seed_demo_rejects_an_invalid_demo_category_and_creates_nothing(settings, monkeypatch):
    settings.DEBUG = True
    home = make_store("home", "Home")
    make_superuser()

    invalid_definition = {
        "name": "Broken",
        "slug": "demo-broken",
        "sku_code": "DMB",
        "option_schema": [
            {
                "code": "size",
                "label": "Size",
                "values": [{"code": "SM", "label": "Small"}],
            }
        ],
    }
    monkeypatch.setattr(seed_demo, "DEMO_CATEGORIES", (invalid_definition,))

    with pytest.raises(CommandError, match="demo category"):
        run_seed()

    assert not Category.objects.filter(store=home).exists()
    assert not Product.objects.exists()


def test_seeding_one_store_creates_nothing_in_another(settings):
    settings.DEBUG = True
    home = make_store("home", "Home")
    anime = make_store("anime", "Anime")
    make_superuser()

    run_seed(store="home")

    assert catalog_counts(home)["products"] >= 5
    assert catalog_counts(anime) == {
        "categories": 0,
        "products": 0,
        "variants": 0,
        "designs": 0,
        "suppliers": 0,
        "collections": 0,
        "media": 0,
    }


def test_seed_demo_refuses_to_run_when_debug_is_off(settings):
    settings.DEBUG = False
    make_store("home", "Home")
    make_superuser()

    with pytest.raises(CommandError, match="DEBUG"):
        run_seed()

    assert not Category.objects.exists()
    assert not Product.objects.exists()
    assert not ProductVariant.objects.exists()


def test_seed_demo_rejects_an_unknown_store(settings):
    settings.DEBUG = True
    make_superuser()

    with pytest.raises(CommandError, match="No store"):
        run_seed(store="missing")

    assert not Category.objects.exists()
    assert not Product.objects.exists()


@pytest.mark.parametrize(
    ("email", "is_active", "is_superuser"),
    [
        ("nobody@example.com", True, True),
        ("operator@example.com", False, True),
        ("operator@example.com", True, False),
    ],
)
def test_seed_demo_rejects_an_invalid_operator(settings, email, is_active, is_superuser):
    settings.DEBUG = True
    make_store("home", "Home")
    if email == "operator@example.com":
        make_superuser(is_active=is_active, is_superuser=is_superuser)

    with pytest.raises(CommandError, match="superuser|user with email"):
        run_seed(operator=email)

    assert not Category.objects.exists()
    assert not Product.objects.exists()
