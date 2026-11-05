import json
from decimal import Decimal
from io import StringIO
from itertools import count

import pytest
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management import CommandError, call_command

from apps.catalog.models import Category, Design, Product, ProductVariant, Supplier
from apps.stores.models import Store

pytestmark = pytest.mark.django_db

_numbers = count(1)


def make_store(slug, name=None, *, is_active=True):
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
):
    return Category.objects.create(
        store=store,
        name=name,
        slug=slug,
        sku_code=sku_code,
        shape=Category.Shape.RECTANGLE,
        option_schema=option_schema or [],
    )


def make_variant(
    store,
    category,
    *,
    option_values=None,
    is_active=True,
    price="199.00",
    compare_at_price=None,
    cost="80.00",
):
    number = next(_numbers)
    supplier = Supplier.objects.create(store=store, name=f"Supplier {number}")
    design = Design.objects.create(
        store=store,
        supplier=supplier,
        name=f"Design {number}",
        supplier_design_name=f"DESIGN {number}",
    )
    product = Product.objects.create(store=store, category=category, design=design)
    return ProductVariant.objects.create(
        product=product,
        option_values={} if option_values is None else option_values,
        price=Decimal(price),
        compare_at_price=Decimal(compare_at_price) if compare_at_price is not None else None,
        cost=Decimal(cost),
        is_active=is_active,
    )


def run_set_prices(*args, **options):
    stdout = StringIO()
    call_command("set_prices", *args, stdout=stdout, **options)
    return stdout.getvalue()


def test_reprices_only_the_category_and_option_value_of_one_store():
    home = make_store("home", "Home")
    anime = make_store("anime", "Anime")
    make_superuser()
    frazada = make_category(home, option_schema=size_schema("IND", "MAT"))
    almohada = make_category(
        home, name="Almohada", slug="almohada", sku_code="ALM", option_schema=size_schema("MAT")
    )
    anime_frazada = make_category(anime, option_schema=size_schema("MAT"))

    mat_active = make_variant(home, frazada, option_values={"size": "MAT"})
    mat_inactive = make_variant(home, frazada, option_values={"size": "MAT"}, is_active=False)
    ind = make_variant(home, frazada, option_values={"size": "IND"})
    ind_inactive = make_variant(home, frazada, option_values={"size": "IND"}, is_active=False)
    other_category = make_variant(home, almohada, option_values={"size": "MAT"})
    other_store = make_variant(anime, anime_frazada, option_values={"size": "MAT"})

    run_set_prices(
        store="home",
        category="frazada",
        option_value="MAT",
        price="249.00",
        operator="operator@example.com",
    )

    for variant in (mat_active, mat_inactive):
        variant.refresh_from_db()
        assert variant.price == Decimal("249.00")
    for variant in (ind, ind_inactive, other_category, other_store):
        variant.refresh_from_db()
        assert variant.price == Decimal("199.00")


@pytest.mark.parametrize(
    ("email", "is_active", "is_superuser"),
    [
        ("nobody@example.com", True, True),
        ("operator@example.com", False, True),
        ("operator@example.com", True, False),
    ],
)
def test_an_unknown_inactive_or_non_superuser_operator_fails_before_any_change(
    email, is_active, is_superuser
):
    home = make_store("home", "Home")
    frazada = make_category(home, option_schema=size_schema("MAT"))
    variant = make_variant(home, frazada, option_values={"size": "MAT"})
    make_superuser(is_active=is_active, is_superuser=is_superuser)

    with pytest.raises(CommandError):
        run_set_prices(
            store="home",
            category="frazada",
            option_value="MAT",
            price="249.00",
            operator=email,
        )

    variant.refresh_from_db()
    assert variant.price == Decimal("199.00")


def test_the_operator_email_is_matched_ignoring_case():
    home = make_store("home", "Home")
    frazada = make_category(home, option_schema=size_schema("MAT"))
    variant = make_variant(home, frazada, option_values={"size": "MAT"})
    make_superuser("operator@example.com")

    run_set_prices(
        store="home",
        category="frazada",
        option_value="MAT",
        price="249.00",
        operator="Operator@Example.com",
    )

    variant.refresh_from_db()
    assert variant.price == Decimal("249.00")


def test_the_report_counts_matched_active_inactive_and_already_at_price_variants():
    home = make_store("home", "Home")
    make_superuser()
    frazada = make_category(home, option_schema=size_schema("MAT"))
    make_variant(home, frazada, option_values={"size": "MAT"}, price="249.00")
    make_variant(home, frazada, option_values={"size": "MAT"}, price="199.00")
    make_variant(home, frazada, option_values={"size": "MAT"}, price="199.00", is_active=False)

    output = run_set_prices(
        store="home",
        category="frazada",
        option_value="MAT",
        price="249.00",
        operator="operator@example.com",
    )

    assert "Matched active variants: 2" in output
    assert "Matched inactive variants: 1" in output
    assert "Already at these prices: 1" in output
    assert "Changed variants: 2" in output


def test_omitting_the_option_value_fails_for_a_category_with_options():
    home = make_store("home", "Home")
    make_superuser()
    frazada = make_category(home, option_schema=size_schema("MAT"))
    variant = make_variant(home, frazada, option_values={"size": "MAT"})

    with pytest.raises(CommandError, match="option"):
        run_set_prices(
            store="home",
            category="frazada",
            price="249.00",
            operator="operator@example.com",
        )

    variant.refresh_from_db()
    assert variant.price == Decimal("199.00")


def test_a_category_without_options_reprices_all_its_variants_without_an_option_value():
    home = make_store("home", "Home")
    make_superuser()
    single = make_category(home, name="Individual", slug="individual", sku_code="IND")
    first = make_variant(home, single)
    second = make_variant(home, single, is_active=False)

    run_set_prices(
        store="home",
        category="individual",
        price="249.00",
        operator="operator@example.com",
    )

    for variant in (first, second):
        variant.refresh_from_db()
        assert variant.price == Decimal("249.00")


@pytest.mark.parametrize("compare_at_price", ["249.00", "200.00"])
def test_a_compare_at_price_not_greater_than_the_price_fails_and_changes_nothing(
    compare_at_price,
):
    home = make_store("home", "Home")
    make_superuser()
    frazada = make_category(home, option_schema=size_schema("MAT"))
    variant = make_variant(home, frazada, option_values={"size": "MAT"})

    with pytest.raises(CommandError, match="compare-at"):
        run_set_prices(
            store="home",
            category="frazada",
            option_value="MAT",
            price="249.00",
            compare_at_price=compare_at_price,
            operator="operator@example.com",
        )

    variant.refresh_from_db()
    assert variant.price == Decimal("199.00")
    assert variant.compare_at_price is None


def test_a_valid_compare_at_price_is_stored():
    home = make_store("home", "Home")
    make_superuser()
    frazada = make_category(home, option_schema=size_schema("MAT"))
    variant = make_variant(home, frazada, option_values={"size": "MAT"})

    run_set_prices(
        store="home",
        category="frazada",
        option_value="MAT",
        price="249.00",
        compare_at_price="299.00",
        operator="operator@example.com",
    )

    variant.refresh_from_db()
    assert variant.price == Decimal("249.00")
    assert variant.compare_at_price == Decimal("299.00")


def test_clear_compare_at_price_empties_it():
    home = make_store("home", "Home")
    make_superuser()
    frazada = make_category(home, option_schema=size_schema("MAT"))
    variant = make_variant(home, frazada, option_values={"size": "MAT"}, compare_at_price="299.00")

    run_set_prices(
        store="home",
        category="frazada",
        option_value="MAT",
        price="249.00",
        clear_compare_at_price=True,
        operator="operator@example.com",
    )

    variant.refresh_from_db()
    assert variant.compare_at_price is None


def test_a_compare_at_price_is_left_alone_when_neither_flag_is_given():
    home = make_store("home", "Home")
    make_superuser()
    frazada = make_category(home, option_schema=size_schema("MAT"))
    variant = make_variant(home, frazada, option_values={"size": "MAT"}, compare_at_price="299.00")

    run_set_prices(
        store="home",
        category="frazada",
        option_value="MAT",
        price="249.00",
        operator="operator@example.com",
    )

    variant.refresh_from_db()
    assert variant.compare_at_price == Decimal("299.00")


def test_raising_the_price_above_the_existing_compare_at_price_fails_and_changes_nothing():
    home = make_store("home", "Home")
    make_superuser()
    frazada = make_category(home, option_schema=size_schema("MAT"))
    variant = make_variant(home, frazada, option_values={"size": "MAT"}, compare_at_price="249.00")

    with pytest.raises(CommandError, match="compare-at"):
        run_set_prices(
            store="home",
            category="frazada",
            option_value="MAT",
            price="299.00",
            operator="operator@example.com",
        )

    variant.refresh_from_db()
    assert variant.price == Decimal("199.00")
    assert variant.compare_at_price == Decimal("249.00")


@pytest.mark.parametrize("price", ["0", "-1", "abc", "NaN", "Infinity", "249.999"])
def test_an_invalid_price_fails_and_changes_nothing(price):
    home = make_store("home", "Home")
    make_superuser()
    frazada = make_category(home, option_schema=size_schema("MAT"))
    variant = make_variant(home, frazada, option_values={"size": "MAT"})

    with pytest.raises(CommandError):
        run_set_prices(
            store="home",
            category="frazada",
            option_value="MAT",
            price=price,
            operator="operator@example.com",
        )

    variant.refresh_from_db()
    assert variant.price == Decimal("199.00")


def test_a_cost_is_updated_only_when_given():
    home = make_store("home", "Home")
    make_superuser()
    frazada = make_category(home, option_schema=size_schema("MAT"))
    variant = make_variant(home, frazada, option_values={"size": "MAT"})

    run_set_prices(
        store="home",
        category="frazada",
        option_value="MAT",
        price="249.00",
        cost="90.00",
        operator="operator@example.com",
    )
    variant.refresh_from_db()
    assert variant.cost == Decimal("90.00")

    run_set_prices(
        store="home",
        category="frazada",
        option_value="MAT",
        price="259.00",
        operator="operator@example.com",
    )
    variant.refresh_from_db()
    assert variant.cost == Decimal("90.00")


def test_a_variant_already_at_the_given_price_compare_at_and_cost_is_not_changed():
    home = make_store("home", "Home")
    make_superuser()
    frazada = make_category(home, option_schema=size_schema("MAT"))
    make_variant(
        home,
        frazada,
        option_values={"size": "MAT"},
        price="249.00",
        compare_at_price="299.00",
        cost="90.00",
    )

    output = run_set_prices(
        store="home",
        category="frazada",
        option_value="MAT",
        price="249.00",
        compare_at_price="299.00",
        cost="90.00",
        operator="operator@example.com",
    )

    assert "Already at these prices: 1" in output
    assert "Changed variants: 0" in output


def test_one_admin_log_entry_per_changed_variant_with_old_and_new_prices():
    home = make_store("home", "Home")
    operator = make_superuser()
    frazada = make_category(home, option_schema=size_schema("MAT"))
    changed = make_variant(home, frazada, option_values={"size": "MAT"})
    already = make_variant(
        home,
        frazada,
        option_values={"size": "MAT"},
        price="249.00",
        compare_at_price="299.00",
        cost="90.00",
    )

    run_set_prices(
        store="home",
        category="frazada",
        option_value="MAT",
        price="249.00",
        compare_at_price="299.00",
        cost="90.00",
        operator="operator@example.com",
    )

    content_type = ContentType.objects.get_for_model(ProductVariant)
    entries = LogEntry.objects.filter(content_type=content_type, object_id=str(changed.pk))
    assert entries.count() == 1
    entry = entries.get()
    assert entry.user == operator
    assert entry.action_flag == CHANGE
    assert entry.object_repr == changed.sku

    changed_fields = json.loads(entry.change_message)[0]["changed"]
    assert changed_fields["fields"] == ["price", "compare_at_price", "cost"]
    assert changed_fields["price"] == {"old": "199.00", "new": "249.00"}
    assert changed_fields["compare_at_price"] == {"old": None, "new": "299.00"}
    assert changed_fields["cost"] == {"old": "80.00", "new": "90.00"}
    assert not LogEntry.objects.filter(object_id=str(already.pk)).exists()
    assert "price" in entry.get_change_message()


def test_clearing_the_compare_at_price_is_logged_with_the_old_value():
    home = make_store("home", "Home")
    make_superuser()
    frazada = make_category(home, option_schema=size_schema("MAT"))
    variant = make_variant(home, frazada, option_values={"size": "MAT"}, compare_at_price="299.00")

    run_set_prices(
        store="home",
        category="frazada",
        option_value="MAT",
        price="249.00",
        clear_compare_at_price=True,
        operator="operator@example.com",
    )

    entry = LogEntry.objects.get(object_id=str(variant.pk))
    changed_fields = json.loads(entry.change_message)[0]["changed"]
    assert changed_fields["compare_at_price"] == {"old": "299.00", "new": None}


def test_dry_run_still_rejects_an_invalid_price():
    home = make_store("home", "Home")
    make_superuser()
    frazada = make_category(home, option_schema=size_schema("MAT"))
    variant = make_variant(home, frazada, option_values={"size": "MAT"})

    with pytest.raises(CommandError):
        run_set_prices(
            store="home",
            category="frazada",
            option_value="MAT",
            price="0",
            operator="operator@example.com",
            dry_run=True,
        )

    variant.refresh_from_db()
    assert variant.price == Decimal("199.00")


def test_dry_run_writes_no_prices_and_no_log_entries():
    home = make_store("home", "Home")
    make_superuser()
    frazada = make_category(home, option_schema=size_schema("MAT"))
    variant = make_variant(home, frazada, option_values={"size": "MAT"})

    output = run_set_prices(
        store="home",
        category="frazada",
        option_value="MAT",
        price="249.00",
        operator="operator@example.com",
        dry_run=True,
    )

    variant.refresh_from_db()
    assert variant.price == Decimal("199.00")
    assert not LogEntry.objects.exists()
    assert "Dry run" in output
    assert "Changed variants: 1" in output


def test_a_failure_partway_through_leaves_every_variant_and_log_unchanged(monkeypatch):
    home = make_store("home", "Home")
    make_superuser()
    frazada = make_category(home, option_schema=size_schema("MAT"))
    first = make_variant(home, frazada, option_values={"size": "MAT"})
    second = make_variant(home, frazada, option_values={"size": "MAT"})

    original_save = ProductVariant.save
    calls = {"count": 0}

    def flaky_save(self, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("the second write failed")
        return original_save(self, *args, **kwargs)

    monkeypatch.setattr(ProductVariant, "save", flaky_save)

    with pytest.raises(RuntimeError):
        run_set_prices(
            store="home",
            category="frazada",
            option_value="MAT",
            price="249.00",
            operator="operator@example.com",
        )

    for variant in (first, second):
        variant.refresh_from_db()
        assert variant.price == Decimal("199.00")
    assert not LogEntry.objects.exists()


def test_two_categories_sharing_a_sku_code_are_repriced_independently():
    home = make_store("home", "Home")
    make_superuser()
    figure = make_category(
        home,
        name="Almohada de figura",
        slug="almohada-figura",
        sku_code="ALM",
        option_schema=size_schema("FIG-80"),
    )
    rectangular = make_category(
        home,
        name="Almohada rectangular",
        slug="almohada-rectangular",
        sku_code="ALM",
        option_schema=size_schema("REC-45X35"),
    )
    figure_variant = make_variant(home, figure, option_values={"size": "FIG-80"})
    rectangular_variant = make_variant(home, rectangular, option_values={"size": "REC-45X35"})

    run_set_prices(
        store="home",
        category="almohada-figura",
        option_value="FIG-80",
        price="249.00",
        operator="operator@example.com",
    )

    figure_variant.refresh_from_db()
    rectangular_variant.refresh_from_db()
    assert figure_variant.price == Decimal("249.00")
    assert rectangular_variant.price == Decimal("199.00")


def test_an_unknown_option_value_fails_and_changes_nothing():
    home = make_store("home", "Home")
    make_superuser()
    frazada = make_category(home, option_schema=size_schema("MAT"))
    variant = make_variant(home, frazada, option_values={"size": "MAT"})

    with pytest.raises(CommandError, match="option value"):
        run_set_prices(
            store="home",
            category="frazada",
            option_value="NOPE",
            price="249.00",
            operator="operator@example.com",
        )

    variant.refresh_from_db()
    assert variant.price == Decimal("199.00")


def test_an_inactive_store_fails_and_changes_nothing():
    home = make_store("home", "Home", is_active=False)
    make_superuser()
    frazada = make_category(home, option_schema=size_schema("MAT"))
    variant = make_variant(home, frazada, option_values={"size": "MAT"})

    with pytest.raises(CommandError, match="inactive"):
        run_set_prices(
            store="home",
            category="frazada",
            option_value="MAT",
            price="249.00",
            operator="operator@example.com",
        )

    variant.refresh_from_db()
    assert variant.price == Decimal("199.00")


def test_an_unknown_store_or_category_fails():
    home = make_store("home", "Home")
    make_superuser()
    make_category(home, option_schema=size_schema("MAT"))

    with pytest.raises(CommandError, match="store"):
        run_set_prices(
            store="anime",
            category="frazada",
            option_value="MAT",
            price="249.00",
            operator="operator@example.com",
        )

    with pytest.raises(CommandError, match="category"):
        run_set_prices(
            store="home",
            category="almohada",
            option_value="MAT",
            price="249.00",
            operator="operator@example.com",
        )


def test_a_negative_cost_fails_and_changes_nothing():
    home = make_store("home", "Home")
    make_superuser()
    frazada = make_category(home, option_schema=size_schema("MAT"))
    variant = make_variant(home, frazada, option_values={"size": "MAT"})

    with pytest.raises(CommandError, match="cost"):
        run_set_prices(
            store="home",
            category="frazada",
            option_value="MAT",
            price="249.00",
            cost="-1.00",
            operator="operator@example.com",
        )

    variant.refresh_from_db()
    assert variant.cost == Decimal("80.00")


def test_an_option_value_is_accepted_for_a_category_without_options():
    home = make_store("home", "Home")
    make_superuser()
    single = make_category(home, name="Individual", slug="individual", sku_code="IND")
    variant = make_variant(home, single)

    run_set_prices(
        store="home",
        category="individual",
        option_value="IGNORED",
        price="249.00",
        operator="operator@example.com",
    )

    variant.refresh_from_db()
    assert variant.price == Decimal("249.00")
