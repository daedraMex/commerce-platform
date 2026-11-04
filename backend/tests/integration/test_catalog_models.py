import threading

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError

from apps.catalog.models import Category, Design, Supplier
from apps.stores.models import Store

pytestmark = pytest.mark.django_db


def make_store(slug, name=None):
    return Store.objects.create(slug=slug, name=name or slug.title())


def make_supplier(store, name="Beka"):
    return Supplier.objects.create(store=store, name=name)


def make_design(store, supplier, supplier_design_name):
    return Design.objects.create(
        store=store,
        supplier=supplier,
        name="Jack Todos",
        supplier_design_name=supplier_design_name,
    )


def make_category(store, *, name="Frazada", slug="frazada", sku_code="FRZ", option_schema=None):
    return Category.objects.create(
        store=store,
        name=name,
        slug=slug,
        sku_code=sku_code,
        shape=Category.Shape.RECTANGLE,
        option_schema=option_schema or [],
    )


def size_schema(*codes):
    return [
        {
            "code": "size",
            "label": "Size",
            "values": [
                {"code": code, "label": code, "width_cm": 80, "height_cm": 80} for code in codes
            ],
        }
    ]


def test_design_numbers_start_at_one_and_increase_per_store():
    home = make_store("home", "Home")
    anime = make_store("anime", "Anime")
    home_supplier = make_supplier(home)
    anime_supplier = make_supplier(anime, "Kawaii")

    home_numbers = [
        make_design(home, home_supplier, "JACK TODOS").number,
        make_design(home, home_supplier, "STRAYKIDS AZULCLARO").number,
    ]
    anime_number = make_design(anime, anime_supplier, "NEKO").number

    assert home_numbers == [1, 2]
    assert anime_number == 1


def test_a_deactivated_design_number_is_never_reused():
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    first = make_design(home, supplier, "JACK TODOS")
    second = make_design(home, supplier, "STRAYKIDS AZULCLARO")

    second.is_active = False
    second.save()

    assert make_design(home, supplier, "NEKO").number == first.number + 2


def test_a_design_number_is_shown_with_five_digits():
    home = make_store("home", "Home")
    supplier = make_supplier(home)

    design = make_design(home, supplier, "JACK TODOS")

    assert design.formatted_number == "00001"


def test_a_design_number_cannot_be_edited():
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    design = make_design(home, supplier, "JACK TODOS")

    design.number = 99

    with pytest.raises(ValidationError):
        design.save()

    design.refresh_from_db()
    assert design.number == 1


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_concurrent_design_creation_never_produces_a_duplicate_number():
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    start = threading.Barrier(6)
    errors = []

    def create_design(index):
        try:
            start.wait(timeout=10)
            Design.objects.create(
                store=home,
                supplier=supplier,
                name="Jack Todos",
                supplier_design_name=f"DESIGN {index}",
            )
        except Exception as error:  # pragma: no cover - reported through the assertion
            errors.append(error)
        finally:
            connection.close()

    threads = [threading.Thread(target=create_design, args=(index,)) for index in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert errors == []
    assert sorted(Design.objects.values_list("number", flat=True)) == [1, 2, 3, 4, 5, 6]


def test_the_supplier_design_name_is_unique_per_supplier():
    home = make_store("home", "Home")
    beka = make_supplier(home, "Beka")
    other = make_supplier(home, "Other")
    make_design(home, beka, "JACK TODOS")

    with pytest.raises(IntegrityError), transaction.atomic():
        make_design(home, beka, "JACK TODOS")

    assert make_design(home, other, "JACK TODOS").pk is not None


def test_a_category_slug_is_unique_per_store():
    home = make_store("home", "Home")
    anime = make_store("anime", "Anime")
    make_category(home)

    with pytest.raises(IntegrityError), transaction.atomic():
        make_category(home, name="Frazada other", sku_code="ALM")

    assert make_category(anime).pk is not None


def test_a_category_rejects_a_malformed_schema_when_saved():
    home = make_store("home", "Home")

    with pytest.raises(ValidationError):
        Category.objects.create(
            store=home,
            name="Frazada",
            sku_code="FRZ",
            shape=Category.Shape.RECTANGLE,
            attribute_schema=[{"code": "material"}],
        )

    assert not Category.objects.exists()


def test_a_category_rejects_overlapping_sku_suffixes_when_saved():
    home = make_store("home", "Home")
    make_category(
        home,
        name="Almohada dona",
        slug="almohada-dona",
        sku_code="ALM",
        option_schema=size_schema("DON-80"),
    )

    with pytest.raises(ValidationError):
        make_category(
            home,
            name="Almohada dona again",
            slug="almohada-dona-again",
            sku_code="alm",
            option_schema=size_schema("DON-80"),
        )


def test_a_category_stores_its_sku_code_uppercase():
    home = make_store("home", "Home")

    category = make_category(home, sku_code="frz")

    assert category.sku_code == "FRZ"


def test_a_category_generates_its_slug_from_the_name():
    home = make_store("home", "Home")

    category = Category.objects.create(
        store=home,
        name="Frazada Térmica",
        sku_code="FRZ",
        shape=Category.Shape.RECTANGLE,
    )

    assert category.slug == "frazada-termica"


def test_a_design_supplier_must_belong_to_the_design_store():
    home = make_store("home", "Home")
    anime = make_store("anime", "Anime")
    home_supplier = make_supplier(home)

    with pytest.raises(ValidationError):
        make_design(anime, home_supplier, "JACK TODOS")

    assert not Design.objects.exists()


def test_a_supplier_with_designs_cannot_be_deleted():
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    make_design(home, supplier, "JACK TODOS")

    with pytest.raises(ProtectedError):
        supplier.delete()
