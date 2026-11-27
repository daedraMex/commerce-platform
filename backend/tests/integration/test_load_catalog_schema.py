import json
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.catalog.models import Category, Design, Product, ProductVariant, Supplier
from apps.stores.models import Store

pytestmark = pytest.mark.django_db


def make_store(slug="home", name=None, *, is_active=True):
    return Store.objects.create(slug=slug, name=name or slug.title(), is_active=is_active)


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


def attribute_schema(*, required=True):
    return [
        {
            "code": "material",
            "label": "Material",
            "type": "text",
            "choices": [],
            "required": required,
        }
    ]


def category(slug="frazada", name="Frazada", sku_code="FRZ", **overrides):
    data = {
        "slug": slug,
        "name": name,
        "sku_code": sku_code,
        "shape": "rectangle",
        "option_schema": size_schema("IND", "MAT"),
        "attribute_schema": attribute_schema(),
    }
    data.update(overrides)
    return data


def definition(*categories, suppliers=("Beka", "Por definir"), **overrides):
    data = {
        "version": 1,
        "suppliers": list(suppliers),
        "categories": list(categories) or [category()],
    }
    data.update(overrides)
    return data


def write_definition(tmp_path, data, filename="catalog-definition.json"):
    path = tmp_path / filename
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def run_load(*args, **options):
    stdout = StringIO()
    call_command("load_catalog_schema", *args, stdout=stdout, **options)
    return stdout.getvalue()


def make_variant(store, category, *, option_values=None):
    supplier = Supplier.objects.create(store=store, name="Existing supplier")
    design = Design.objects.create(
        store=store,
        supplier=supplier,
        name="Existing design",
        supplier_design_name="EXISTING DESIGN",
    )
    product = Product.objects.create(
        store=store,
        category=category,
        design=design,
        attributes={"material": "Cotton"},
    )
    return ProductVariant.objects.create(
        product=product,
        option_values={"size": "IND"} if option_values is None else option_values,
        price=Decimal("199.00"),
        cost=Decimal("80.00"),
    )


def test_creates_the_categories_and_suppliers_from_the_file(tmp_path):
    make_store()
    path = write_definition(tmp_path, definition())

    output = run_load(store="home", file=str(path))

    frazada = Category.objects.get(store__slug="home", slug="frazada")
    assert frazada.name == "Frazada"
    assert frazada.sku_code == "FRZ"
    assert frazada.shape == Category.Shape.RECTANGLE
    assert frazada.option_schema == size_schema("IND", "MAT")
    assert frazada.attribute_schema == attribute_schema()
    assert set(Supplier.objects.values_list("name", flat=True)) == {"Beka", "Por definir"}
    assert "Categories created: 1" in output
    assert "Suppliers created: 2" in output


def test_rerunning_the_same_file_converges_without_duplicates_or_deletes(tmp_path):
    home = make_store()
    path = write_definition(tmp_path, definition())
    run_load(store="home", file=str(path))
    Category.objects.create(
        store=home, name="Kept", slug="kept", sku_code="KPT", shape=Category.Shape.RECTANGLE
    )
    Supplier.objects.create(store=home, name="Kept supplier")

    output = run_load(store="home", file=str(path))

    assert Category.objects.filter(store=home).count() == 2
    assert Supplier.objects.filter(store=home).count() == 3
    assert Category.objects.filter(store=home, slug="frazada").count() == 1
    assert Supplier.objects.filter(store=home, name="Beka").count() == 1
    assert "Categories unchanged: 1" in output
    assert "Suppliers unchanged: 2" in output


def test_an_evolved_file_updates_rows_and_leaves_omitted_rows_alone(tmp_path):
    home = make_store()
    run_load(store="home", file=str(write_definition(tmp_path, definition())))
    Category.objects.create(
        store=home, name="Kept", slug="kept", sku_code="KPT", shape=Category.Shape.RECTANGLE
    )
    Supplier.objects.create(store=home, name="Kept supplier")
    path = write_definition(
        tmp_path,
        definition(
            category(name="Frazadas", option_schema=size_schema("IND", "MAT", "MAX")),
            category(slug="almohada", name="Almohada", sku_code="ALM"),
        ),
    )

    output = run_load(store="home", file=str(path))

    frazada = Category.objects.get(store=home, slug="frazada")
    assert frazada.name == "Frazadas"
    assert frazada.option_schema == size_schema("IND", "MAT", "MAX")
    assert Category.objects.filter(store=home, slug="almohada").exists()
    assert Category.objects.filter(store=home, slug="kept").exists()
    assert Supplier.objects.filter(store=home, name="Kept supplier").exists()
    assert "Categories created: 1" in output
    assert "Categories updated: 1" in output


def test_the_placeholder_supplier_is_created_even_when_the_file_omits_it(tmp_path):
    home = make_store()
    path = write_definition(tmp_path, definition(suppliers=("Beka",)))

    run_load(store="home", file=str(path))

    assert Supplier.objects.filter(store=home, name="Por definir").exists()


def test_dry_run_shows_the_exact_diff_and_writes_nothing(tmp_path):
    home = make_store()
    path = write_definition(tmp_path, definition())

    output = run_load(store="home", file=str(path), dry_run=True)

    assert not Category.objects.exists()
    assert not Supplier.objects.exists()
    assert "Category 'frazada' (create)" in output
    assert "name: 'Frazada'" in output
    assert "Supplier 'Beka' (create)" in output
    assert "Supplier 'Por definir' (create)" in output
    assert "Dry run: nothing was written." in output

    run_load(store="home", file=str(path))
    updated = write_definition(
        tmp_path,
        definition(category(name="Frazadas", sku_code="FRZ")),
        filename="catalog-definition-v2.json",
    )
    output = run_load(store="home", file=str(updated), dry_run=True)

    assert "Category 'frazada' (update)" in output
    assert "name: 'Frazada' -> 'Frazadas'" in output
    assert Category.objects.get(store=home, slug="frazada").name == "Frazada"


def test_a_sku_code_used_by_a_variant_can_never_change(tmp_path):
    home = make_store()
    run_load(store="home", file=str(write_definition(tmp_path, definition())))
    frazada = Category.objects.get(store=home, slug="frazada")
    make_variant(home, frazada)
    path = write_definition(tmp_path, definition(category(sku_code="NEW")))

    with pytest.raises(CommandError, match="SKU code cannot change"):
        run_load(store="home", file=str(path))

    frazada.refresh_from_db()
    assert frazada.sku_code == "FRZ"


def test_an_invalid_schema_is_rejected_clearly_and_nothing_is_written(tmp_path):
    make_store()
    broken = category(option_schema=[{"code": "size", "label": "Size", "values": []}])
    path = write_definition(tmp_path, definition(broken))

    with pytest.raises(CommandError, match="size"):
        run_load(store="home", file=str(path))

    assert not Category.objects.exists()
    assert not Supplier.objects.exists()


def test_a_later_invalid_row_rolls_back_the_earlier_updates(tmp_path):
    home = make_store()
    run_load(store="home", file=str(write_definition(tmp_path, definition())))
    frazada = Category.objects.get(store=home, slug="frazada")
    make_variant(home, frazada)
    path = write_definition(
        tmp_path,
        definition(
            category(name="Frazadas"),
            category(slug="almohada", name="Almohada", sku_code="ALM", option_schema="not a list"),
        ),
    )

    with pytest.raises(CommandError):
        run_load(store="home", file=str(path))

    frazada.refresh_from_db()
    assert frazada.name == "Frazada"
    assert not Category.objects.filter(store=home, slug="almohada").exists()


def test_a_file_naming_another_store_is_rejected(tmp_path):
    make_store()
    path = write_definition(tmp_path, definition(store="anime"))

    with pytest.raises(CommandError, match="anime"):
        run_load(store="home", file=str(path))

    assert not Category.objects.exists()


def test_a_bad_json_file_is_rejected_before_anything_is_written(tmp_path):
    make_store()
    path = tmp_path / "catalog-definition.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(CommandError, match="not valid JSON"):
        run_load(store="home", file=str(path))

    assert not Category.objects.exists()
    assert not Supplier.objects.exists()


def test_an_unknown_or_inactive_store_is_rejected(tmp_path):
    path = write_definition(tmp_path, definition())
    make_store(is_active=False)

    with pytest.raises(CommandError, match="inactive"):
        run_load(store="home", file=str(path))
    with pytest.raises(CommandError, match="No store"):
        run_load(store="missing", file=str(path))
