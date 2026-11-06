import csv
import json
from decimal import Decimal
from io import StringIO
from pathlib import Path

import pytest
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management import CommandError, call_command

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

pytestmark = pytest.mark.django_db

FIELDNAMES = [
    "category",
    "supplier",
    "supplier_design_name",
    "design_name",
    "option_values",
    "price",
    "compare_at_price",
    "cost",
    "weight_grams",
    "package_length_cm",
    "package_width_cm",
    "package_height_cm",
    "collections",
    "attributes",
    "description",
    "main_image",
    "gallery_images",
]


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
        option_schema=size_schema("IND", "MAT") if option_schema is None else option_schema,
        attribute_schema=attribute_schema
        if attribute_schema is not None
        else [
            {
                "code": "material",
                "label": "Material",
                "type": "text",
                "choices": [],
                "required": True,
            }
        ],
    )


def make_supplier(store, name="Beka"):
    return Supplier.objects.create(store=store, name=name)


def row(**overrides):
    values = {
        "category": "frazada",
        "supplier": "Beka",
        "supplier_design_name": "JACK TODOS",
        "design_name": "Jack Todos",
        "option_values": "size=IND",
        "price": "199.00",
        "compare_at_price": "",
        "cost": "80.00",
        "weight_grams": "",
        "package_length_cm": "",
        "package_width_cm": "",
        "package_height_cm": "",
        "collections": "",
        "attributes": "material=Flannel premier",
        "description": "",
        "main_image": "",
        "gallery_images": "",
    }
    values.update(overrides)
    return values


def write_csv(tmp_path, rows, filename="catalog.csv", fieldnames=None):
    path = tmp_path / filename
    fieldnames = fieldnames or FIELDNAMES
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def run_import(*args, **options):
    stdout = StringIO()
    call_command("import_catalog", *args, stdout=stdout, **options)
    return stdout.getvalue()


def test_a_valid_file_creates_designs_products_variants_and_collections(tmp_path):
    home = make_store()
    make_superuser()
    make_category(home)
    make_supplier(home)
    path = write_csv(
        tmp_path,
        [
            row(option_values="size=IND", collections="Invierno 2026"),
            row(option_values="size=MAT", collections="Invierno 2026"),
            row(
                supplier_design_name="DONA AZUL",
                design_name="Dona Azul",
                option_values="size=IND",
            ),
        ],
    )

    output = run_import(
        store="home",
        csv=str(path),
        operator="operator@example.com",
    )

    designs = list(Design.objects.order_by("number"))
    assert [design.number for design in designs] == [1, 2]
    assert [design.name for design in designs] == ["Jack Todos", "Dona Azul"]
    assert Product.objects.count() == 2
    assert ProductVariant.objects.count() == 3
    assert set(ProductVariant.objects.values_list("sku", flat=True)) == {
        "FRZ-00001-IND",
        "FRZ-00001-MAT",
        "FRZ-00002-IND",
    }
    collection = Collection.objects.get(name="Invierno 2026")
    assert collection.store == home
    assert collection.memberships.count() == 1
    assert collection.memberships.get().product.design.supplier_design_name == "JACK TODOS"
    assert "Rows created: 3" in output
    assert "Rows updated: 0" in output
    assert "Rows rejected: 0" in output
    assert "Collections created: 1" in output
    assert "Invierno 2026" in output


def test_rows_create_the_collection_membership_in_file_order(tmp_path):
    home = make_store()
    make_superuser()
    make_category(home)
    make_supplier(home)
    path = write_csv(
        tmp_path,
        [
            row(supplier_design_name="FIRST", design_name="First", collections="Invierno"),
            row(supplier_design_name="SECOND", design_name="Second", collections="Invierno"),
        ],
    )

    run_import(store="home", csv=str(path), operator="operator@example.com")

    collection = Collection.objects.get(name="Invierno")
    ordered = list(
        CollectionProduct.objects.filter(collection=collection)
        .order_by("position")
        .values_list("product__design__name", flat=True)
    )
    assert ordered == ["First", "Second"]


def test_rerunning_the_same_file_updates_instead_of_duplicating(tmp_path):
    home = make_store()
    make_superuser()
    make_category(home)
    make_supplier(home)
    path = write_csv(
        tmp_path,
        [
            row(option_values="size=IND"),
            row(option_values="size=MAT"),
        ],
    )

    run_import(store="home", csv=str(path), operator="operator@example.com")
    design_number = Design.objects.get().number
    skus = set(ProductVariant.objects.values_list("sku", flat=True))

    output = run_import(store="home", csv=str(path), operator="operator@example.com")

    assert Design.objects.count() == 1
    assert Product.objects.count() == 1
    assert ProductVariant.objects.count() == 2
    assert Design.objects.get().number == design_number
    assert set(ProductVariant.objects.values_list("sku", flat=True)) == skus
    assert "Rows created: 0" in output
    assert "Rows updated: 2" in output


def test_a_rerun_updates_the_prices_and_dimensions_of_existing_variants(tmp_path):
    home = make_store()
    make_superuser()
    make_category(home)
    make_supplier(home)
    first = write_csv(tmp_path, [row(option_values="size=IND")], filename="first.csv")
    run_import(store="home", csv=str(first), operator="operator@example.com")

    changed = write_csv(
        tmp_path,
        [
            row(
                option_values="size=IND",
                price="249.00",
                compare_at_price="299.00",
                cost="90.00",
                weight_grams="1200",
                package_length_cm="40",
                package_width_cm="30",
                package_height_cm="10.50",
            )
        ],
        filename="changed.csv",
    )
    run_import(store="home", csv=str(changed), operator="operator@example.com")

    variant = ProductVariant.objects.get()
    assert variant.price == Decimal("249.00")
    assert variant.compare_at_price == Decimal("299.00")
    assert variant.cost == Decimal("90.00")
    assert variant.weight_grams == 1200
    assert variant.package_length_cm == Decimal("40.00")
    assert variant.package_height_cm == Decimal("10.50")


def run_import_expecting_error(*args, **options):
    stdout = StringIO()
    with pytest.raises(CommandError):
        call_command("import_catalog", *args, stdout=stdout, **options)
    return stdout.getvalue()


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"category": "beka"}, "Unknown category 'beka'"),
        ({"supplier": "Beka "}, "Unknown supplier 'Beka '"),
        ({"price": "0.00"}, "price must be greater than zero"),
        ({"compare_at_price": "199.00"}, "compare-at price must be greater than the price"),
        ({"cost": "-1.00"}, "cost must not be negative"),
    ],
)
def test_a_rejected_row_writes_nothing_and_exits_non_zero(tmp_path, overrides, reason):
    home = make_store()
    make_superuser()
    make_category(home)
    make_supplier(home)
    path = write_csv(
        tmp_path,
        [
            row(supplier_design_name="GOOD", design_name="Good"),
            row(**overrides),
        ],
    )

    output = run_import_expecting_error(
        store="home",
        csv=str(path),
        operator="operator@example.com",
    )

    assert not Design.objects.exists()
    assert not Product.objects.exists()
    assert not ProductVariant.objects.exists()
    assert not Collection.objects.exists()
    assert "Rows created: 0" in output
    assert "Rows rejected: 1" in output
    assert "Row 3:" in output
    assert reason in output


@pytest.mark.parametrize(
    ("email", "is_active", "is_superuser"),
    [
        ("nobody@example.com", True, True),
        ("operator@example.com", False, True),
        ("operator@example.com", True, False),
    ],
)
def test_the_operator_is_checked_before_the_file_is_read(tmp_path, email, is_active, is_superuser):
    make_superuser(is_active=is_active, is_superuser=is_superuser)
    missing = tmp_path / "does-not-exist.csv"

    with pytest.raises(CommandError, match="superuser|user with email"):
        call_command(
            "import_catalog",
            store="home",
            csv=str(missing),
            operator=email,
            stdout=StringIO(),
        )


def test_an_inactive_store_is_rejected(tmp_path):
    make_store(is_active=False)
    make_superuser()
    path = write_csv(tmp_path, [row()])

    with pytest.raises(CommandError, match="inactive"):
        call_command(
            "import_catalog",
            store="home",
            csv=str(path),
            operator="operator@example.com",
            stdout=StringIO(),
        )


def test_unknown_option_values_and_attributes_reject_the_row(tmp_path):
    home = make_store()
    make_superuser()
    make_category(home)
    make_supplier(home)

    for overrides in (
        {"option_values": "size=GIGANTIC"},
        {"attributes": "material=Flannel;unknown=yes"},
    ):
        path = write_csv(tmp_path, [row(**overrides)], filename="bad.csv")
        output = run_import_expecting_error(
            store="home", csv=str(path), operator="operator@example.com"
        )
        assert "Rows rejected: 1" in output
        assert not ProductVariant.objects.exists()


def test_dry_run_lists_new_collections_and_writes_nothing(tmp_path):
    home = make_store()
    make_superuser()
    make_category(home)
    make_supplier(home)
    first = write_csv(tmp_path, [row(option_values="size=IND")], filename="first.csv")
    run_import(store="home", csv=str(first), operator="operator@example.com")
    variant = ProductVariant.objects.get()

    dry = write_csv(
        tmp_path,
        [
            row(
                option_values="size=IND",
                price="249.00",
                collections="Halloween 2026;Invierno",
            )
        ],
        filename="dry.csv",
    )
    output = run_import(
        store="home",
        csv=str(dry),
        operator="operator@example.com",
        dry_run=True,
    )

    variant.refresh_from_db()
    assert variant.price == Decimal("199.00")
    assert not Collection.objects.exists()
    assert not CollectionProduct.objects.exists()
    assert not LogEntry.objects.exists()
    assert "Rows updated: 1" in output
    assert "Collections created: 2" in output
    assert "Halloween 2026" in output
    assert "Invierno" in output
    assert "Dry run" in output


def test_dry_run_on_an_empty_catalog_creates_nothing(tmp_path):
    home = make_store()
    make_superuser()
    make_category(home)
    make_supplier(home)
    path = write_csv(tmp_path, [row(option_values="size=MAT")])

    output = run_import(store="home", csv=str(path), operator="operator@example.com", dry_run=True)

    assert "Rows created: 1" in output
    assert not Design.objects.exists()
    assert not Product.objects.exists()
    assert not ProductVariant.objects.exists()


def test_changed_prices_log_one_admin_entry_per_variant_with_old_and_new_values(tmp_path):
    home = make_store()
    operator = make_superuser()
    make_category(home)
    make_supplier(home)
    first = write_csv(
        tmp_path,
        [
            row(option_values="size=IND"),
            row(option_values="size=MAT"),
        ],
        filename="first.csv",
    )
    run_import(store="home", csv=str(first), operator="operator@example.com")
    changed = ProductVariant.objects.get(sku="FRZ-00001-IND")
    unchanged = ProductVariant.objects.get(sku="FRZ-00001-MAT")

    second = write_csv(
        tmp_path,
        [
            row(
                option_values="size=IND",
                price="249.00",
                compare_at_price="299.00",
                cost="90.00",
            ),
            row(option_values="size=MAT"),
        ],
        filename="second.csv",
    )
    run_import(store="home", csv=str(second), operator="operator@example.com")

    content_type = ContentType.objects.get_for_model(ProductVariant)
    entries = LogEntry.objects.filter(content_type=content_type, object_id=str(changed.pk))
    assert entries.count() == 1
    entry = entries.get()
    assert entry.user == operator
    assert entry.action_flag == CHANGE
    assert entry.object_repr == "FRZ-00001-IND"
    changed_fields = json.loads(entry.change_message)[0]["changed"]
    assert changed_fields["price"] == {"old": "199.00", "new": "249.00"}
    assert changed_fields["compare_at_price"] == {"old": None, "new": "299.00"}
    assert changed_fields["cost"] == {"old": "80.00", "new": "90.00"}
    assert not LogEntry.objects.filter(object_id=str(unchanged.pk)).exists()


def test_an_unchanged_rerun_writes_no_log_entries(tmp_path):
    home = make_store()
    make_superuser()
    make_category(home)
    make_supplier(home)
    path = write_csv(tmp_path, [row(option_values="size=IND")])

    run_import(store="home", csv=str(path), operator="operator@example.com")
    run_import(store="home", csv=str(path), operator="operator@example.com")

    assert not LogEntry.objects.exists()


def test_a_rerun_never_changes_skus_design_numbers_categories_or_option_values(tmp_path):
    home = make_store()
    make_superuser()
    make_category(home)
    category = Category.objects.get()
    make_supplier(home)
    first = write_csv(tmp_path, [row(option_values="size=IND")], filename="first.csv")
    run_import(store="home", csv=str(first), operator="operator@example.com")
    variant = ProductVariant.objects.get()
    design = Design.objects.get()
    original_sku = variant.sku
    original_number = design.number

    second = write_csv(
        tmp_path,
        [
            row(
                option_values="size=IND",
                design_name="A Different Name",
                price="299.00",
            )
        ],
        filename="second.csv",
    )
    run_import(store="home", csv=str(second), operator="operator@example.com")

    variant.refresh_from_db()
    design.refresh_from_db()
    assert variant.sku == original_sku
    assert variant.option_values == {"size": "IND"}
    assert variant.product.category_id == category.pk
    assert design.number == original_number


def test_a_rerun_never_deactivates_rows_that_are_missing_from_the_file(tmp_path):
    home = make_store()
    make_superuser()
    make_category(home)
    make_supplier(home)
    first = write_csv(
        tmp_path,
        [
            row(option_values="size=IND"),
            row(option_values="size=MAT"),
        ],
        filename="first.csv",
    )
    run_import(store="home", csv=str(first), operator="operator@example.com")

    only_ind = write_csv(tmp_path, [row(option_values="size=IND")], filename="only-ind.csv")
    run_import(store="home", csv=str(only_ind), operator="operator@example.com")

    assert ProductVariant.objects.filter(sku="FRZ-00001-MAT", is_active=True).exists()
    assert ProductVariant.objects.filter(sku="FRZ-00001-IND", is_active=True).exists()


def test_a_new_option_value_creates_a_new_variant_without_touching_the_old_one(tmp_path):
    home = make_store()
    make_superuser()
    make_category(home)
    make_supplier(home)
    first = write_csv(tmp_path, [row(option_values="size=IND")], filename="first.csv")
    run_import(store="home", csv=str(first), operator="operator@example.com")
    old_variant = ProductVariant.objects.get()

    second = write_csv(
        tmp_path,
        [
            row(option_values="size=IND"),
            row(option_values="size=MAT"),
        ],
        filename="second.csv",
    )
    run_import(store="home", csv=str(second), operator="operator@example.com")

    old_variant.refresh_from_db()
    assert old_variant.sku == "FRZ-00001-IND"
    assert old_variant.option_values == {"size": "IND"}
    assert ProductVariant.objects.filter(sku="FRZ-00001-MAT").exists()


def test_a_home_import_never_touches_anime(tmp_path):
    home = make_store("home", "Home")
    anime = make_store("anime", "Anime")
    make_superuser()
    make_category(home)
    make_category(anime, name="Frazada anime", slug="frazada", sku_code="FRZ")
    make_supplier(home)
    make_supplier(anime, "Beka")
    path = write_csv(tmp_path, [row(option_values="size=IND")])

    run_import(store="home", csv=str(path), operator="operator@example.com")

    assert Design.objects.filter(store=home).count() == 1
    assert Product.objects.filter(store=home).count() == 1
    assert ProductVariant.objects.filter(store=home).count() == 1
    assert not Design.objects.filter(store=anime).exists()
    assert not Product.objects.filter(store=anime).exists()
    assert not ProductVariant.objects.filter(store=anime).exists()
    assert not Collection.objects.filter(store=anime).exists()


def test_a_3000_row_import_runs_a_bounded_number_of_queries(
    tmp_path, django_assert_max_num_queries
):
    home = make_store()
    make_superuser()
    make_category(home, option_schema=size_schema("IND", "MAT", "MAX"))
    make_supplier(home)
    rows = []
    for design_number in range(1, 1001):
        for size in ("IND", "MAT", "MAX"):
            rows.append(
                row(
                    supplier_design_name=f"DESIGN {design_number}",
                    design_name=f"Design {design_number}",
                    option_values=f"size={size}",
                )
            )
    path = write_csv(tmp_path, rows)

    with django_assert_max_num_queries(30):
        output = run_import(store="home", csv=str(path), operator="operator@example.com")

    assert "Rows created: 3000" in output
    assert Design.objects.count() == 1000
    assert Product.objects.count() == 1000
    assert ProductVariant.objects.count() == 3000


def test_the_template_spreadsheet_is_committed_with_the_command_columns():
    template = Path(__file__).resolve().parents[3] / "docs" / "catalog-import-template.csv"

    with template.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        assert list(reader.fieldnames) == FIELDNAMES
        assert next(reader)["category"] == "frazada"


def test_one_design_creates_a_product_in_each_category(tmp_path):
    home = make_store()
    make_superuser()
    make_category(home, option_schema=size_schema("IND", "MAT"))
    make_category(
        home,
        name="Almohada de figura",
        slug="almohada-de-figura",
        sku_code="ALM",
        option_schema=size_schema("FIG-80"),
    )
    make_supplier(home)
    path = write_csv(
        tmp_path,
        [
            row(option_values="size=IND"),
            row(category="almohada-de-figura", option_values="size=FIG-80"),
        ],
    )

    run_import(store="home", csv=str(path), operator="operator@example.com")

    assert Design.objects.count() == 1
    assert Product.objects.count() == 2
    assert set(ProductVariant.objects.values_list("sku", flat=True)) == {
        "FRZ-00001-IND",
        "ALM-00001-FIG-80",
    }


def test_a_category_without_options_imports_a_variant_without_a_suffix(tmp_path):
    home = make_store()
    make_superuser()
    make_category(
        home,
        name="Individual",
        slug="individual",
        sku_code="IND",
        option_schema=[],
    )
    make_supplier(home)
    path = write_csv(tmp_path, [row(category="individual", option_values="")])

    run_import(store="home", csv=str(path), operator="operator@example.com")

    assert ProductVariant.objects.get().sku == "IND-00001"


def test_direct_option_and_attribute_columns_are_accepted(tmp_path):
    home = make_store()
    make_superuser()
    make_category(home)
    make_supplier(home)
    fieldnames = FIELDNAMES + ["size", "material"]
    path = write_csv(
        tmp_path,
        [row(option_values="", attributes="", size="MAT", material="Flannel premier")],
        fieldnames=fieldnames,
    )

    run_import(store="home", csv=str(path), operator="operator@example.com")

    variant = ProductVariant.objects.get()
    assert variant.sku == "FRZ-00001-MAT"
    assert variant.product.attributes == {"material": "Flannel premier"}


def test_missing_required_columns_fail_before_anything_is_written(tmp_path):
    home = make_store()
    make_superuser()
    make_category(home)
    make_supplier(home)
    path = write_csv(
        tmp_path,
        [{"category": "frazada", "supplier": "Beka"}],
        fieldnames=["category", "supplier"],
    )

    with pytest.raises(CommandError, match="missing the column"):
        call_command(
            "import_catalog",
            store="home",
            csv=str(path),
            operator="operator@example.com",
            stdout=StringIO(),
        )

    assert not Design.objects.exists()


def test_adding_variants_to_existing_products_stays_within_a_bounded_query_count(
    tmp_path, django_assert_max_num_queries
):
    home = make_store()
    make_superuser()
    make_category(home, option_schema=size_schema("IND", "MAT", "MAX"))
    make_supplier(home)
    initial = write_csv(
        tmp_path,
        [
            row(
                supplier_design_name=f"DESIGN {number}",
                design_name=f"Design {number}",
                option_values="size=IND",
            )
            for number in range(1, 201)
        ],
        filename="initial.csv",
    )
    run_import(store="home", csv=str(initial), operator="operator@example.com")

    additions = write_csv(
        tmp_path,
        [
            row(
                supplier_design_name=f"DESIGN {number}",
                design_name=f"Design {number}",
                option_values=f"size={size}",
            )
            for number in range(1, 201)
            for size in ("MAT", "MAX")
        ],
        filename="additions.csv",
    )
    with django_assert_max_num_queries(30):
        output = run_import(store="home", csv=str(additions), operator="operator@example.com")

    assert "Rows created: 400" in output
    assert ProductVariant.objects.count() == 600
