import json
from decimal import Decimal
from io import StringIO

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.urls import reverse

from apps.catalog.models import Category, Design, Media, Product, ProductVariant, Supplier
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


def test_admin_rejects_a_removed_choice_in_use_naming_the_active_product(
    admin_client_by_email,
):
    home = make_store("home", "Home")
    old_schema = [
        {
            "code": "finish",
            "label": "Finish",
            "type": "choice",
            "choices": ["Matte", "Gloss"],
            "required": False,
        }
    ]
    category = Category.objects.create(
        store=home,
        name="Frazada",
        slug="frazada",
        sku_code="FRZ",
        shape=Category.Shape.RECTANGLE,
        attribute_schema=old_schema,
    )
    Product.objects.create(
        store=home, category=category, attributes={"finish": "Matte"}, name="Frazada Jack Todos"
    )

    response = admin_client_by_email.post(
        f"/admin/catalog/category/{category.pk}/change/",
        category_form(
            home,
            name="Frazada",
            sku_code="FRZ",
            option_schema=[],
            attribute_schema=[{**old_schema[0], "choices": ["Gloss"]}],
        ),
    )

    assert response.status_code == 200
    assert b"Frazada Jack Todos" in response.content
    assert b"finish" in response.content
    category.refresh_from_db()
    assert category.attribute_schema == old_schema


def test_admin_rejects_a_removed_option_value_in_use_naming_the_variant_sku(
    admin_client_by_email,
):
    home = make_store("home", "Home")
    old_schema = size_schema(("IND", "Individual", 110, 160), ("MAX", "Maxi", 175, 160))
    category = make_category(
        home,
        name="Frazada",
        slug="frazada",
        sku_code="FRZ",
        option_schema=old_schema,
    )
    product = Product.objects.create(store=home, category=category)
    variant = ProductVariant.objects.create(
        product=product,
        option_values={"size": "IND"},
        sku="FRZ-00001-IND",
        price=Decimal("199.00"),
        cost=Decimal("80.00"),
    )

    response = admin_client_by_email.post(
        f"/admin/catalog/category/{category.pk}/change/",
        category_form(
            home,
            name="Frazada",
            sku_code="FRZ",
            option_schema=size_schema(("MAX", "Maxi", 175, 160)),
        ),
    )

    assert response.status_code == 200
    assert variant.sku.encode() in response.content
    category.refresh_from_db()
    assert category.option_schema == old_schema


def test_admin_rejects_changing_the_sku_code_once_a_variant_exists(admin_client_by_email):
    home = make_store("home", "Home")
    old_schema = size_schema(("IND", "Individual", 110, 160))
    category = make_category(
        home,
        name="Frazada",
        slug="frazada",
        sku_code="FRZ",
        option_schema=old_schema,
    )
    product = Product.objects.create(store=home, category=category)
    variant = ProductVariant.objects.create(
        product=product,
        option_values={"size": "IND"},
        sku="FRZ-00001-IND",
        price=Decimal("199.00"),
        cost=Decimal("80.00"),
    )

    response = admin_client_by_email.post(
        f"/admin/catalog/category/{category.pk}/change/",
        category_form(
            home,
            name="Frazada",
            sku_code="FRZD",
            option_schema=old_schema,
        ),
    )

    assert response.status_code == 200
    assert variant.sku.encode() in response.content
    category.refresh_from_db()
    assert category.sku_code == "FRZ"


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


def test_every_catalog_model_registered_in_the_admin_opens_its_change_page(
    admin_client_by_email, settings
):
    settings.DEBUG = True
    home = make_store("home", "Home")
    call_command(
        "seed_demo",
        store="home",
        operator="owner@example.com",
        stdout=StringIO(),
    )

    catalog_models = [model for model in admin.site._registry if model._meta.app_label == "catalog"]
    objects = {}
    for model in catalog_models:
        obj = model.objects.filter(store=home).first()
        if obj is None and model is Media:
            # The demo has no images, so give the Media admin a row to open.
            obj = Media.objects.create(
                store=home,
                storage_key="demo/placeholder.jpg",
                content_hash="demo-placeholder",
                mime_type="image/jpeg",
                width=1,
                height=1,
            )
        assert obj is not None, model
        objects[model] = obj

    for model, obj in objects.items():
        url = reverse(
            f"admin:{model._meta.app_label}_{model._meta.model_name}_change",
            args=[obj.pk],
        )
        assert admin_client_by_email.get(url).status_code == 200, model
