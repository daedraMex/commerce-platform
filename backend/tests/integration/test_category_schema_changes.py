from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.catalog.models import Category, Product, ProductVariant
from apps.stores.models import Store

pytestmark = pytest.mark.django_db


def make_store(slug, name=None):
    return Store.objects.create(slug=slug, name=name or slug.title())


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


def attribute_schema(*, required=False, choices=None):
    return [
        {
            "code": "finish",
            "label": "Finish",
            "type": "choice" if choices is not None else "text",
            "choices": choices or [],
            "required": required,
        }
    ]


def make_category(
    store,
    *,
    name="Frazada",
    slug="frazada",
    sku_code="FRZ",
    option_schema=None,
    attribute_schema=None,
):
    return Category.objects.create(
        store=store,
        name=name,
        slug=slug,
        sku_code=sku_code,
        shape=Category.Shape.RECTANGLE,
        option_schema=option_schema or [],
        attribute_schema=attribute_schema or [],
    )


def make_product(store, category, *, attributes=None, is_active=True):
    return Product.objects.create(
        store=store,
        category=category,
        attributes=attributes or {},
        is_active=is_active,
    )


def make_variant(product, option_values, *, sku="FRZ-00001-IND", is_active=True):
    return ProductVariant.objects.create(
        product=product,
        option_values=option_values,
        sku=sku,
        price=Decimal("199.00"),
        cost=Decimal("80.00"),
        is_active=is_active,
    )


def test_adding_an_option_value_and_relabelling_an_attribute_is_saved():
    home = make_store("home", "Home")
    category = make_category(
        home,
        option_schema=size_schema("IND", "MAX"),
        attribute_schema=attribute_schema(),
    )
    product = make_product(home, category, attributes={"finish": "Matte"})
    make_variant(product, {"size": "IND"})

    category.option_schema = size_schema("IND", "MAX", "MAT")
    category.attribute_schema = [{**attribute_schema()[0], "label": "Coating"}]
    category.save()

    category.refresh_from_db()
    assert [value["code"] for value in category.option_schema[0]["values"]] == ["IND", "MAX", "MAT"]
    assert category.attribute_schema[0]["label"] == "Coating"


def test_a_schema_change_ignores_another_stores_variants():
    home = make_store("home", "Home")
    anime = make_store("anime", "Anime")
    home_category = make_category(home, option_schema=size_schema("IND", "MAX"))
    anime_category = make_category(anime, option_schema=size_schema("IND", "MAX"))
    make_variant(make_product(anime, anime_category), {"size": "IND"})

    home_category.option_schema = size_schema("MAX")
    home_category.save()

    home_category.refresh_from_db()
    assert [value["code"] for value in home_category.option_schema[0]["values"]] == ["MAX"]


def test_saving_a_new_required_attribute_with_an_active_product_is_rejected():
    home = make_store("home", "Home")
    category = make_category(home)
    product = make_product(home, category, attributes={})
    product.name = "Frazada Jack Todos"
    product.save()

    category.attribute_schema = attribute_schema(required=True)

    with pytest.raises(ValidationError) as error:
        category.save()

    assert "Frazada Jack Todos" in str(error.value)
    assert "finish" in str(error.value)
    category.refresh_from_db()
    assert category.attribute_schema == []


def test_saving_a_removed_choice_in_use_is_rejected():
    home = make_store("home", "Home")
    old_schema = attribute_schema(choices=["Matte", "Gloss"])
    category = make_category(home, attribute_schema=old_schema)
    make_product(home, category, attributes={"finish": "Matte"})

    category.attribute_schema = attribute_schema(choices=["Gloss"])

    with pytest.raises(ValidationError) as error:
        category.save()

    assert "finish" in str(error.value)
    category.refresh_from_db()
    assert category.attribute_schema == old_schema


def test_saving_a_changed_attribute_type_in_use_is_rejected():
    home = make_store("home", "Home")
    old_schema = attribute_schema()
    category = make_category(home, attribute_schema=old_schema)
    make_product(home, category, attributes={"finish": "Matte"})

    category.attribute_schema = [{**old_schema[0], "type": "number"}]

    with pytest.raises(ValidationError) as error:
        category.save()

    assert "finish" in str(error.value)
    category.refresh_from_db()
    assert category.attribute_schema == old_schema


def test_saving_a_removed_option_value_used_by_an_inactive_variant_is_rejected():
    home = make_store("home", "Home")
    category = make_category(home, option_schema=size_schema("IND", "MAX"))
    product = make_product(home, category, is_active=False)
    variant = make_variant(product, {"size": "IND"}, is_active=False)

    category.option_schema = size_schema("MAX")

    with pytest.raises(ValidationError) as error:
        category.save()

    assert variant.sku in str(error.value)
    assert "IND" in str(error.value)
    category.refresh_from_db()
    assert [value["code"] for value in category.option_schema[0]["values"]] == ["IND", "MAX"]


def test_saving_a_removed_option_used_by_a_variant_is_rejected():
    home = make_store("home", "Home")
    category = make_category(home, option_schema=size_schema("IND"))
    product = make_product(home, category)
    variant = make_variant(product, {"size": "IND"})

    category.option_schema = []

    with pytest.raises(ValidationError) as error:
        category.save()

    assert variant.sku in str(error.value)
    assert "size" in str(error.value)
    category.refresh_from_db()
    assert category.option_schema != []


def test_a_new_required_attribute_is_allowed_when_no_active_product_exists():
    home = make_store("home", "Home")
    category = make_category(home)
    make_product(home, category, is_active=False)

    category.attribute_schema = attribute_schema(required=True)
    category.save()

    category.refresh_from_db()
    assert category.attribute_schema[0]["required"] is True


def test_changing_the_sku_code_is_rejected_when_a_variant_exists():
    home = make_store("home", "Home")
    category = make_category(home, option_schema=size_schema("IND"))
    product = make_product(home, category)
    variant = make_variant(product, {"size": "IND"})

    category.sku_code = "FRZD"

    with pytest.raises(ValidationError) as error:
        category.save()

    assert variant.sku in str(error.value)
    category.refresh_from_db()
    assert category.sku_code == "FRZ"


def test_changing_the_sku_code_is_allowed_without_variants():
    home = make_store("home", "Home")
    category = make_category(home)

    category.sku_code = "FRZD"
    category.save()

    category.refresh_from_db()
    assert category.sku_code == "FRZD"
