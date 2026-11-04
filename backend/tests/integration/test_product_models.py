from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.catalog.models import Category, Design, Product, ProductVariant, Supplier
from apps.stores.models import Store

pytestmark = pytest.mark.django_db


def make_store(slug, name=None):
    return Store.objects.create(slug=slug, name=name or slug.title())


def make_supplier(store, name="Beka"):
    return Supplier.objects.create(store=store, name=name)


def make_design(store, supplier, supplier_design_name="JACK TODOS", *, number=None):
    design = Design.objects.create(
        store=store,
        supplier=supplier,
        name="Jack Todos",
        supplier_design_name=supplier_design_name,
    )
    if number is not None:
        Design.objects.filter(pk=design.pk).update(number=number)
        design.refresh_from_db()
    return design


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


def make_product(store, category, design=None, **kwargs):
    return Product.objects.create(store=store, category=category, design=design, **kwargs)


def make_variant(product, *, option_values=None, sku=None, **kwargs):
    return ProductVariant.objects.create(
        product=product,
        option_values=option_values if option_values is not None else {"size": "MAT"},
        sku=sku,
        price=kwargs.pop("price", Decimal("199.00")),
        compare_at_price=kwargs.pop("compare_at_price", None),
        cost=kwargs.pop("cost", Decimal("80.00")),
        **kwargs,
    )


def test_a_product_defaults_its_name_and_slug_from_the_category_and_design():
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    design = make_design(home, supplier)
    category = make_category(home)

    product = make_product(home, category, design)

    assert product.name == "Frazada Jack Todos"
    assert product.slug == "frazada-jack-todos"
    assert product.created_at is not None
    assert product.updated_at is not None


def test_a_product_slug_is_unique_per_store():
    home = make_store("home", "Home")
    anime = make_store("anime", "Anime")
    supplier = make_supplier(home)
    design = make_design(home, supplier)
    category = make_category(home)
    make_product(home, category, design)

    with pytest.raises(IntegrityError), transaction.atomic():
        make_product(home, category, design, slug="frazada-jack-todos")

    anime_supplier = make_supplier(anime, "Kawaii")
    anime_design = make_design(anime, anime_supplier)
    assert make_product(anime, make_category(anime), anime_design).pk is not None


def test_a_product_rejects_a_category_from_another_store():
    home = make_store("home", "Home")
    anime = make_store("anime", "Anime")

    with pytest.raises(ValidationError):
        make_product(home, make_category(anime, name="Frazada anime", slug="frazada-anime"))

    assert not Product.objects.exists()


def test_a_product_rejects_a_design_from_another_store():
    home = make_store("home", "Home")
    anime = make_store("anime", "Anime")
    anime_supplier = make_supplier(anime, "Kawaii")
    anime_design = make_design(anime, anime_supplier)

    with pytest.raises(ValidationError):
        make_product(home, make_category(home), anime_design)

    assert not Product.objects.exists()


def test_product_attributes_are_validated_against_the_category_schema():
    home = make_store("home", "Home")
    category = make_category(
        home,
        attribute_schema=[
            {
                "code": "material",
                "label": "Material",
                "type": "text",
                "choices": [],
                "required": True,
            }
        ],
    )

    product = make_product(home, category, attributes={"material": "Flannel premier"})

    assert product.attributes == {"material": "Flannel premier"}


@pytest.mark.parametrize(
    "attributes",
    [{"weight": 2}, {"material": 12}],
)
def test_a_product_with_invalid_attributes_is_rejected(attributes):
    home = make_store("home", "Home")
    category = make_category(
        home,
        attribute_schema=[
            {
                "code": "material",
                "label": "Material",
                "type": "text",
                "choices": [],
                "required": True,
            }
        ],
    )

    with pytest.raises(ValidationError):
        make_product(home, category, attributes=attributes)

    assert not Product.objects.exists()


def test_a_product_without_variants_can_change_its_category_and_design():
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    first_category = make_category(home)
    second_category = make_category(home, name="Almohada", slug="almohada", sku_code="ALM")
    first_design = make_design(home, supplier, "FIRST")
    second_design = make_design(home, supplier, "SECOND")
    product = make_product(home, first_category, first_design)

    product.category = second_category
    product.design = second_design
    product.save()

    product.refresh_from_db()
    assert product.category == second_category
    assert product.design == second_design


@pytest.mark.parametrize("change", ["category", "design"])
def test_a_product_cannot_change_category_or_design_once_it_has_variants(change):
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    category = make_category(home)
    design = make_design(home, supplier, number=12)
    product = make_product(home, category, design)
    make_variant(product, option_values={})

    if change == "category":
        product.category = make_category(home, name="Almohada", slug="almohada", sku_code="ALM")
    else:
        product.design = make_design(home, supplier, "OTHER", number=13)

    with pytest.raises(ValidationError):
        product.save()


def test_a_variant_generates_its_sku_from_the_category_design_and_option_values():
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    design = make_design(home, supplier, number=12)
    category = make_category(home, option_schema=size_schema("IND", "MAX", "MAT"))
    product = make_product(home, category, design)

    variant = make_variant(product, option_values={"size": "MAT"})

    assert variant.sku == "FRZ-00012-MAT"
    assert variant.store_id == home.pk


def test_a_variant_keeps_a_multi_part_option_value_code():
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    design = make_design(home, supplier, number=12)
    category = make_category(
        home,
        name="Almohada de figura",
        slug="almohada-de-figura",
        sku_code="ALM",
        option_schema=size_schema("DON-80"),
    )
    product = make_product(home, category, design)

    variant = make_variant(product, option_values={"size": "DON-80"})

    assert variant.sku == "ALM-00012-DON-80"


def test_a_hand_typed_sku_is_rejected_for_a_product_with_a_design():
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    design = make_design(home, supplier)
    category = make_category(home)
    product = make_product(home, category, design)

    with pytest.raises(ValidationError) as error:
        make_variant(product, option_values={}, sku="hand-typed")

    assert "without a design" in str(error.value)
    assert not ProductVariant.objects.exists()


def test_a_product_without_a_design_accepts_a_hand_typed_sku():
    home = make_store("home", "Home")
    category = make_category(home)
    product = make_product(home, category)

    variant = make_variant(product, option_values={}, sku="frz-custom")

    assert variant.sku == "FRZ-CUSTOM"


def test_a_product_without_a_design_requires_a_hand_typed_sku():
    home = make_store("home", "Home")
    category = make_category(home)
    product = make_product(home, category)

    with pytest.raises(ValidationError):
        make_variant(product, option_values={}, sku="")


def test_a_variants_store_must_equal_its_products_store():
    home = make_store("home", "Home")
    anime = make_store("anime", "Anime")
    supplier = make_supplier(home)
    design = make_design(home, supplier)
    category = make_category(home)
    product = make_product(home, category, design)

    with pytest.raises(ValidationError):
        ProductVariant.objects.create(
            product=product,
            store=anime,
            option_values={},
            price=Decimal("199.00"),
            cost=Decimal("80.00"),
        )


def test_a_sku_is_unique_per_store_ignoring_case():
    home = make_store("home", "Home")
    category = make_category(home)
    first = make_product(home, category, slug="first")
    second = make_product(home, category, slug="second")
    make_variant(first, option_values={}, sku="FRZ-CUSTOM")

    with pytest.raises(IntegrityError), transaction.atomic():
        make_variant(second, option_values={}, sku="frz-custom")


def test_the_same_sku_is_allowed_in_two_stores():
    home = make_store("home", "Home")
    anime = make_store("anime", "Anime")
    home_supplier = make_supplier(home)
    anime_supplier = make_supplier(anime, "Kawaii")
    home_design = make_design(home, home_supplier, number=12)
    anime_design = make_design(anime, anime_supplier, number=12)
    home_product = make_product(
        home, make_category(home, option_schema=size_schema("MAT")), home_design
    )
    anime_product = make_product(
        anime,
        make_category(
            anime, name="Frazada anime", slug="frazada-anime", option_schema=size_schema("MAT")
        ),
        anime_design,
    )

    home_variant = make_variant(home_product)
    anime_variant = make_variant(anime_product)

    assert home_variant.sku == anime_variant.sku == "FRZ-00012-MAT"


def test_a_variant_sku_never_changes():
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    design = make_design(home, supplier, number=12)
    category = make_category(home, option_schema=size_schema("MAT"))
    product = make_product(home, category, design)
    variant = make_variant(product)

    variant.sku = "FRZ-99999-MAT"
    with pytest.raises(ValidationError):
        variant.save()

    variant.refresh_from_db()
    assert variant.sku == "FRZ-00012-MAT"


def test_variant_option_values_are_validated_against_the_category_schema():
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    design = make_design(home, supplier)
    category = make_category(home, option_schema=size_schema("MAT"))
    product = make_product(home, category, design)

    with pytest.raises(ValidationError):
        make_variant(product, option_values={"size": "GIGANTIC"})

    with pytest.raises(ValidationError):
        make_variant(product, option_values={})

    with pytest.raises(ValidationError):
        make_variant(product, option_values={"size": "MAT", "color": "RED"})


def test_variant_option_values_never_change():
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    design = make_design(home, supplier)
    category = make_category(home, option_schema=size_schema("IND", "MAT"))
    product = make_product(home, category, design)
    variant = make_variant(product)

    variant.option_values = {"size": "IND"}
    with pytest.raises(ValidationError):
        variant.save()

    variant.refresh_from_db()
    assert variant.option_values == {"size": "MAT"}


def test_two_variants_of_a_product_cannot_share_option_values():
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    design = make_design(home, supplier)
    category = make_category(home, option_schema=size_schema("IND", "MAT"))
    product = make_product(home, category, design)
    make_variant(product)

    with pytest.raises(IntegrityError), transaction.atomic():
        make_variant(product)


def test_a_category_without_options_allows_only_one_variant():
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    design = make_design(home, supplier)
    category = make_category(home)
    product = make_product(home, category, design)
    make_variant(product, option_values={})

    with pytest.raises(IntegrityError), transaction.atomic():
        make_variant(product, option_values={})


def test_a_deactivated_variants_sku_is_never_reused():
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    design = make_design(home, supplier)
    category = make_category(home)
    product = make_product(home, category, design)
    variant = make_variant(product, option_values={})
    variant.is_active = False
    variant.save()

    with pytest.raises(IntegrityError), transaction.atomic():
        make_variant(product, option_values={})


@pytest.mark.parametrize(
    ("price", "compare_at_price", "cost"),
    [
        (Decimal("0.00"), None, Decimal("80.00")),
        (Decimal("-1.00"), None, Decimal("80.00")),
        (None, None, Decimal("80.00")),
        (Decimal("199.00"), Decimal("199.00"), Decimal("80.00")),
        (Decimal("199.00"), Decimal("150.00"), Decimal("80.00")),
        (Decimal("199.00"), None, None),
        (Decimal("199.00"), None, Decimal("-0.01")),
    ],
)
def test_a_variant_with_invalid_prices_is_rejected(price, compare_at_price, cost):
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    design = make_design(home, supplier)
    category = make_category(home)
    product = make_product(home, category, design)

    with pytest.raises(ValidationError):
        make_variant(
            product,
            option_values={},
            price=price,
            compare_at_price=compare_at_price,
            cost=cost,
        )

    assert not ProductVariant.objects.exists()


def test_a_variant_accepts_optional_shipping_fields():
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    design = make_design(home, supplier)
    category = make_category(home)
    product = make_product(home, category, design)

    variant = make_variant(
        product,
        option_values={},
        weight_grams=1200,
        package_length_cm=Decimal("40.00"),
        package_width_cm=Decimal("30.00"),
        package_height_cm=Decimal("10.00"),
    )

    assert variant.weight_grams == 1200
    assert variant.package_length_cm == Decimal("40.00")
