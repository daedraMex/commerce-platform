import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.catalog.models import Category, Collection, CollectionProduct, Product, Supplier
from apps.stores.models import Store

pytestmark = pytest.mark.django_db


def make_store(slug):
    return Store.objects.create(slug=slug, name=slug.title())


def make_category(store, *, name="Frazada", slug="frazada", sku_code="FRZ"):
    return Category.objects.create(
        store=store,
        name=name,
        slug=slug,
        sku_code=sku_code,
        shape=Category.Shape.RECTANGLE,
    )


def make_product(store, *, name="Frazada Térmica"):
    category = Category.objects.filter(store=store).first() or make_category(store)
    return Product.objects.create(store=store, category=category, name=name)


def test_a_collection_generates_its_slug_from_the_name():
    home = make_store("home")

    collection = Collection.objects.create(store=home, name="Halloween Térmico 2026")

    assert collection.slug == "halloween-termico-2026"


def test_a_collection_normalizes_a_manually_entered_slug():
    home = make_store("home")

    collection = Collection.objects.create(
        store=home, name="Halloween 2026", slug="Halloween Térmico"
    )

    assert collection.slug == "halloween-termico"


def test_a_collection_slug_is_unique_per_store():
    home = make_store("home")
    anime = make_store("anime")
    Collection.objects.create(store=home, name="Halloween 2026", slug="halloween-2026")

    with pytest.raises(IntegrityError), transaction.atomic():
        Collection.objects.create(store=home, name="Other", slug="halloween-2026")

    assert Collection.objects.create(store=anime, name="Halloween", slug="halloween-2026").pk


def test_a_collection_supplier_must_belong_to_the_collection_store():
    home = make_store("home")
    anime = make_store("anime")
    anime_supplier = Supplier.objects.create(store=anime, name="Kawaii")

    with pytest.raises(ValidationError):
        Collection.objects.create(store=home, name="Halloween 2026", supplier=anime_supplier)

    assert not Collection.objects.exists()


def test_a_collection_supplier_is_optional():
    home = make_store("home")

    assert Collection.objects.create(store=home, name="Halloween 2026").supplier is None


def test_a_collection_store_cannot_change_once_it_has_products():
    home = make_store("home")
    anime = make_store("anime")
    product = make_product(home)
    collection = Collection.objects.create(store=home, name="Halloween 2026")
    CollectionProduct.objects.create(collection=collection, product=product, position=1)

    collection.store = anime

    with pytest.raises(ValidationError):
        collection.save()

    collection.refresh_from_db()
    assert collection.store_id == home.pk


def test_a_product_of_another_store_cannot_join_a_collection():
    home = make_store("home")
    anime = make_store("anime")
    collection = Collection.objects.create(store=home, name="Halloween 2026")
    anime_product = make_product(anime)

    with pytest.raises(ValidationError):
        CollectionProduct.objects.create(collection=collection, product=anime_product, position=1)

    assert not CollectionProduct.objects.exists()


def test_a_product_can_join_several_collections_or_none():
    home = make_store("home")
    product = make_product(home)
    halloween = Collection.objects.create(store=home, name="Halloween 2026")
    artists = Collection.objects.create(store=home, name="Artistas Asiáticos 2025")

    CollectionProduct.objects.create(collection=halloween, product=product, position=2)
    CollectionProduct.objects.create(collection=artists, product=product, position=1)

    assert product.collection_memberships.count() == 2


def test_a_product_joins_a_collection_only_once():
    home = make_store("home")
    product = make_product(home)
    collection = Collection.objects.create(store=home, name="Halloween 2026")
    CollectionProduct.objects.create(collection=collection, product=product, position=1)

    with pytest.raises(IntegrityError), transaction.atomic():
        CollectionProduct.objects.create(collection=collection, product=product, position=2)


def test_positions_order_the_products_of_a_collection():
    home = make_store("home")
    first = make_product(home, name="First")
    second = make_product(home, name="Second")
    third = make_product(home, name="Third")
    collection = Collection.objects.create(store=home, name="Halloween 2026")

    for product, position in ((second, 1), (third, 2), (first, 3)):
        CollectionProduct.objects.create(collection=collection, product=product, position=position)

    ordered = collection.memberships.values_list("product__name", flat=True)

    assert list(ordered) == ["Second", "Third", "First"]
