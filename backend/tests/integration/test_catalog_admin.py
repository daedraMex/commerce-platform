import json

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse

from apps.catalog.models import Category, Design, Supplier
from apps.stores.models import Store

pytestmark = pytest.mark.django_db


def make_store(slug, name=None):
    return Store.objects.create(slug=slug, name=name or slug.title())


def make_supplier(store, name="Beka"):
    return Supplier.objects.create(store=store, name=name)


def make_design(store, supplier, supplier_design_name="JACK TODOS"):
    return Design.objects.create(
        store=store,
        supplier=supplier,
        name="Jack Todos",
        supplier_design_name=supplier_design_name,
    )


def size_schema(*values):
    return [
        {
            "code": "size",
            "label": "Size",
            "values": [
                {
                    "code": code,
                    "label": label,
                    "width_cm": width,
                    "height_cm": height,
                }
                for code, label, width, height in values
            ],
        }
    ]


def make_category(store, *, name, slug, sku_code, option_schema):
    return Category.objects.create(
        store=store,
        name=name,
        slug=slug,
        sku_code=sku_code,
        shape=Category.Shape.CONTOUR,
        option_schema=option_schema,
    )


def category_form(
    store,
    *,
    name,
    sku_code,
    option_schema,
    slug="",
    shape=Category.Shape.RECTANGLE,
    attribute_schema=None,
):
    return {
        "store": str(store.pk),
        "name": name,
        "slug": slug,
        "sku_code": sku_code,
        "shape": shape,
        "attribute_schema": json.dumps(attribute_schema or []),
        "option_schema": json.dumps(option_schema),
        "is_active": "on",
    }


def test_the_category_admin_uses_the_correct_plural(admin_client_by_email):
    response = admin_client_by_email.get("/admin/catalog/category/")

    assert response.status_code == 200
    assert b"categories" in response.content
    assert b"categorys" not in response.content


def test_admin_creates_a_supplier(admin_client_by_email):
    home = make_store("home", "Home")

    response = admin_client_by_email.post(
        "/admin/catalog/supplier/add/",
        {"store": str(home.pk), "name": "Beka", "is_active": "on"},
    )

    assert response.status_code == 302
    assert Supplier.objects.filter(store=home, name="Beka").exists()


def test_admin_assigns_a_design_number_and_never_edits_it(admin_client_by_email):
    home = make_store("home", "Home")
    supplier = make_supplier(home)

    admin_client_by_email.post(
        "/admin/catalog/design/add/",
        {
            "store": str(home.pk),
            "number": "99",
            "name": "Jack Todos",
            "supplier": str(supplier.pk),
            "supplier_design_name": "JACK TODOS",
            "is_active": "on",
        },
    )

    design = Design.objects.get()
    assert design.number == 1

    admin_client_by_email.post(
        f"/admin/catalog/design/{design.pk}/change/",
        {
            "store": str(home.pk),
            "number": "42",
            "name": "Jack Todos",
            "supplier": str(supplier.pk),
            "supplier_design_name": "JACK TODOS",
            "is_active": "on",
        },
    )

    design.refresh_from_db()
    assert design.number == 1


def test_admin_shows_a_design_number_with_five_digits(admin_client_by_email):
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    design = make_design(home, supplier)

    response = admin_client_by_email.get(f"/admin/catalog/design/{design.pk}/change/")

    assert response.status_code == 200
    assert b"00001" in response.content


def test_admin_rejects_a_design_whose_supplier_belongs_to_another_store(
    admin_client_by_email,
):
    home = make_store("home", "Home")
    anime = make_store("anime", "Anime")
    home_supplier = make_supplier(home)

    response = admin_client_by_email.post(
        "/admin/catalog/design/add/",
        {
            "store": str(anime.pk),
            "name": "Jack Todos",
            "supplier": str(home_supplier.pk),
            "supplier_design_name": "JACK TODOS",
            "is_active": "on",
        },
    )

    assert response.status_code == 200
    assert b"supplier must belong to the design" in response.content
    assert not Design.objects.exists()


def test_admin_rejects_a_malformed_schema_naming_the_wrong_entry(admin_client_by_email):
    home = make_store("home", "Home")

    response = admin_client_by_email.post(
        "/admin/catalog/category/add/",
        category_form(
            home,
            name="Frazada",
            sku_code="FRZ",
            option_schema=[],
            attribute_schema=[
                {"code": "material", "type": "text", "choices": [], "required": True}
            ],
        ),
    )

    assert response.status_code == 200
    assert b"material" in response.content
    assert not Category.objects.exists()


def test_admin_rejects_a_duplicate_generated_slug(admin_client_by_email):
    home = make_store("home", "Home")
    make_category(
        home,
        name="Frazada Térmica",
        slug="frazada-termica",
        sku_code="FRZ",
        option_schema=[],
    )

    response = admin_client_by_email.post(
        "/admin/catalog/category/add/",
        category_form(
            home,
            name="Frazada Termica",
            sku_code="ALM",
            option_schema=[],
        ),
    )

    assert response.status_code == 200
    assert b"already exists" in response.content
    assert Category.objects.count() == 1


def test_admin_rejects_overlapping_option_value_codes_naming_the_other_category(
    admin_client_by_email,
):
    home = make_store("home", "Home")
    make_category(
        home,
        name="Almohada de figura",
        slug="almohada-de-figura",
        sku_code="ALM",
        option_schema=size_schema(("FIG-80", "Figure", 80, 80)),
    )

    response = admin_client_by_email.post(
        "/admin/catalog/category/add/",
        category_form(
            home,
            name="Almohada de figura nueva",
            sku_code="ALM",
            option_schema=size_schema(("FIG-80", "Figure", 80, 80)),
        ),
    )

    assert response.status_code == 200
    assert b"Almohada de figura" in response.content
    assert b"FIG-80" in response.content
    assert Category.objects.count() == 1


def test_admin_accepts_non_overlapping_suffixes_under_the_same_sku_code(
    admin_client_by_email,
):
    home = make_store("home", "Home")
    make_category(
        home,
        name="Almohada de figura",
        slug="almohada-de-figura",
        sku_code="ALM",
        option_schema=size_schema(("FIG-80", "Figure", 80, 80)),
    )

    response = admin_client_by_email.post(
        "/admin/catalog/category/add/",
        category_form(
            home,
            name="Almohada rectangular",
            sku_code="ALM",
            option_schema=size_schema(
                ("REC-45X35", "Rectangular", 45, 35),
                ("REC-50X120", "Abrazable", 50, 120),
            ),
        ),
    )

    assert response.status_code == 302
    assert Category.objects.count() == 2


def test_admin_accepts_overlapping_codes_in_another_store(admin_client_by_email):
    home = make_store("home", "Home")
    anime = make_store("anime", "Anime")
    make_category(
        home,
        name="Almohada de figura",
        slug="almohada-de-figura",
        sku_code="ALM",
        option_schema=size_schema(("FIG-80", "Figure", 80, 80)),
    )

    response = admin_client_by_email.post(
        "/admin/catalog/category/add/",
        category_form(
            anime,
            name="Almohada de figura anime",
            sku_code="ALM",
            option_schema=size_schema(("FIG-80", "Figure", 80, 80)),
        ),
    )

    assert response.status_code == 302
    assert Category.objects.filter(store=anime).count() == 1


@pytest.mark.parametrize(
    "model_name",
    ["supplier", "design", "category"],
)
def test_catalog_rows_are_not_deleted_from_the_admin(admin_client_by_email, model_name):
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    design = make_design(home, supplier)
    category = make_category(
        home,
        name="Frazada",
        slug="frazada",
        sku_code="FRZ",
        option_schema=[],
    )
    obj = {"supplier": supplier, "design": design, "category": category}[model_name]

    response = admin_client_by_email.post(
        reverse(f"admin:catalog_{model_name}_delete", args=[obj.pk]),
        {"post": "yes"},
    )

    assert response.status_code == 403
    assert type(obj).objects.filter(pk=obj.pk).exists()


@pytest.mark.parametrize(
    "url_name",
    [
        "admin:catalog_supplier_changelist",
        "admin:catalog_supplier_add",
        "admin:catalog_design_changelist",
        "admin:catalog_design_add",
        "admin:catalog_category_changelist",
        "admin:catalog_category_add",
    ],
)
def test_catalog_admin_is_reachable_by_superusers_only(client, url_name):
    staff = get_user_model().objects.create_user(email="staff@example.com", is_staff=True)
    staff.user_permissions.set(Permission.objects.all())
    client.force_login(staff)

    response = client.get(reverse(url_name))

    assert response.status_code == 302
    assert response.url.startswith(reverse("admin:login"))
