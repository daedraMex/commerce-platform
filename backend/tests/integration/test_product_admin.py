import json
import re
from decimal import Decimal

import pytest
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.admin.widgets import AutocompleteSelect
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from apps.catalog.models import (
    Category,
    Design,
    Media,
    Product,
    ProductMedia,
    ProductVariant,
    Supplier,
)
from apps.stores.models import Store
from tests.integration.admin_forms import empty_inline, inline

pytestmark = pytest.mark.django_db


def make_store(slug, name=None):
    return Store.objects.create(slug=slug, name=name or slug.title())


def make_supplier(store, name="Beka"):
    return Supplier.objects.create(store=store, name=name)


def make_design(
    store, supplier, supplier_design_name="JACK TODOS", *, number=None, name="Jack Todos"
):
    design = Design.objects.create(
        store=store,
        supplier=supplier,
        name=name,
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


def product_form(store, category, design=None, *, attributes=None, name="", slug=""):
    return {
        "store": str(store.pk),
        "category": str(category.pk),
        "design": str(design.pk) if design else "",
        "name": name,
        "slug": slug,
        "description": "",
        "attributes": json.dumps(attributes or {}),
        "is_active": "on",
        **empty_inline("product_media"),
    }


def variant_row(*, option_values=None, price="199.00", compare_at_price="", cost="80.00"):
    return {
        "sku": "",
        "option_values": json.dumps(option_values or {}),
        "price": price,
        "compare_at_price": compare_at_price,
        "cost": cost,
        "weight_grams": "",
        "package_length_cm": "",
        "package_width_cm": "",
        "package_height_cm": "",
        "is_active": "on",
    }


def test_admin_saves_a_product_with_its_variant_inline(admin_client_by_email):
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    design = make_design(home, supplier, number=12)
    category = make_category(home, option_schema=size_schema("MAT"))

    response = admin_client_by_email.post(
        "/admin/catalog/product/add/",
        {
            **product_form(home, category, design),
            **inline("variants", [variant_row(option_values={"size": "MAT"})]),
        },
    )

    assert response.status_code == 302
    product = Product.objects.get()
    assert product.name == "Frazada Jack Todos"
    assert product.variants.get().sku == "FRZ-00012-MAT"


def test_admin_shows_a_generated_sku_read_only(admin_client_by_email):
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    design = make_design(home, supplier, number=12)
    category = make_category(home, option_schema=size_schema("MAT"))
    product = Product.objects.create(store=home, category=category, design=design)
    ProductVariant.objects.create(
        product=product,
        option_values={"size": "MAT"},
        price=Decimal("199.00"),
        cost=Decimal("80.00"),
    )

    response = admin_client_by_email.get(f"/admin/catalog/product/{product.pk}/change/")

    assert response.status_code == 200
    assert b"FRZ-00012-MAT" in response.content
    field = re.search(rb'<input[^>]*name="variants-0-sku"[^>]*>', response.content)
    assert field is not None
    assert b"disabled" in field.group(0)


def sku_input(content, prefix):
    field = re.search(rb'<input[^>]*name="' + prefix.encode() + rb'-sku"[^>]*>', content)
    assert field is not None
    return field.group(0)


def test_admin_shows_the_sku_read_only_for_a_designed_product(admin_client_by_email):
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    design = make_design(home, supplier)
    category = make_category(home)
    product = Product.objects.create(store=home, category=category, design=design)

    response = admin_client_by_email.get(f"/admin/catalog/product/{product.pk}/change/")

    assert response.status_code == 200
    assert b"disabled" in sku_input(response.content, "variants-__prefix__")


def test_admin_keeps_the_sku_editable_without_a_design(admin_client_by_email):
    home = make_store("home", "Home")
    category = make_category(home)
    product = Product.objects.create(store=home, category=category)

    response = admin_client_by_email.get(f"/admin/catalog/product/{product.pk}/change/")

    assert response.status_code == 200
    assert b"disabled" not in sku_input(response.content, "variants-__prefix__")


def test_admin_rejects_a_typed_sku_for_a_designed_product(admin_client_by_email):
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    design = make_design(home, supplier)
    category = make_category(home)

    response = admin_client_by_email.post(
        "/admin/catalog/product/add/",
        {
            **product_form(home, category, design),
            **inline(
                "variants",
                [{**variant_row(), "sku": "typed-by-hand"}],
            ),
        },
    )

    assert response.status_code == 200
    assert b"without a design" in response.content
    assert not Product.objects.exists()


def test_admin_shows_an_invalid_attribute_rule_message(admin_client_by_email):
    home = make_store("home", "Home")
    category = make_category(home)

    response = admin_client_by_email.post(
        "/admin/catalog/product/add/",
        {
            **product_form(home, category, attributes={"unknown": "value"}),
            **empty_inline("variants"),
        },
    )

    assert response.status_code == 200
    assert b"Unknown attribute" in response.content
    assert not Product.objects.exists()


def test_admin_shows_an_invalid_option_value_rule_message(admin_client_by_email):
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    design = make_design(home, supplier)
    category = make_category(home, option_schema=size_schema("MAT"))

    response = admin_client_by_email.post(
        "/admin/catalog/product/add/",
        {
            **product_form(home, category, design),
            **inline("variants", [variant_row(option_values={"size": "GIGANTIC"})]),
        },
    )

    assert response.status_code == 200
    assert b"Unknown value" in response.content
    assert not Product.objects.exists()


def test_admin_accepts_a_hand_typed_sku_without_a_design(admin_client_by_email):
    home = make_store("home", "Home")
    category = make_category(home)

    response = admin_client_by_email.post(
        "/admin/catalog/product/add/",
        {
            **product_form(home, category),
            **inline("variants", [{**variant_row(), "sku": "frz-custom"}]),
        },
    )

    assert response.status_code == 302
    assert Product.objects.get().variants.get().sku == "FRZ-CUSTOM"


def test_admin_shows_an_invalid_price_rule_message(admin_client_by_email):
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    design = make_design(home, supplier)
    category = make_category(home)

    response = admin_client_by_email.post(
        "/admin/catalog/product/add/",
        {
            **product_form(home, category, design),
            **inline("variants", [variant_row(price="0.00")]),
        },
    )

    assert response.status_code == 200
    assert b"greater than zero" in response.content
    assert not Product.objects.exists()


@pytest.mark.parametrize(
    "query",
    ["FRZ-00012-MAT", "00012", "Jack Todos", "JACK TODOS"],
)
def test_admin_finds_a_product_by_sku_design_number_name_and_supplier_design_name(
    admin_client_by_email, query
):
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    design = make_design(home, supplier, number=12)
    category = make_category(home, option_schema=size_schema("MAT"))
    product = Product.objects.create(store=home, category=category, design=design)
    ProductVariant.objects.create(
        product=product,
        option_values={"size": "MAT"},
        price=Decimal("199.00"),
        cost=Decimal("80.00"),
    )

    response = admin_client_by_email.get("/admin/catalog/product/", {"q": query})

    assert response.status_code == 200
    assert b"Frazada Jack Todos" in response.content


def test_a_design_number_search_keeps_the_active_store_filter(admin_client_by_email):
    home = make_store("home", "Home")
    anime = make_store("anime", "Anime")
    home_design = make_design(home, make_supplier(home), number=12)
    anime_design = make_design(
        anime, make_supplier(anime, "Kawaii"), "NEKO", number=12, name="Neko"
    )
    Product.objects.create(store=home, category=make_category(home), design=home_design)
    Product.objects.create(
        store=anime,
        category=make_category(anime, name="Frazada anime", slug="frazada-anime"),
        design=anime_design,
    )

    response = admin_client_by_email.get(
        "/admin/catalog/product/", {"q": "00012", "store__id__exact": str(anime.pk)}
    )

    assert response.status_code == 200
    assert b"Frazada anime Neko" in response.content
    assert b"Frazada Jack Todos" not in response.content


def test_an_admin_edit_is_written_to_the_admin_log(admin_client_by_email):
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    design = make_design(home, supplier)
    category = make_category(home)
    product = Product.objects.create(store=home, category=category, design=design)

    admin_client_by_email.post(
        f"/admin/catalog/product/{product.pk}/change/",
        {
            **product_form(home, category, design, name="Edited blanket"),
            **empty_inline("variants"),
        },
    )

    product.refresh_from_db()
    assert product.name == "Edited blanket"
    assert LogEntry.objects.filter(
        content_type=ContentType.objects.get_for_model(Product),
        object_id=str(product.pk),
        action_flag=CHANGE,
    ).exists()


def test_products_are_not_deleted_from_the_admin(admin_client_by_email):
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    design = make_design(home, supplier)
    category = make_category(home)
    product = Product.objects.create(store=home, category=category, design=design)

    response = admin_client_by_email.post(
        reverse("admin:catalog_product_delete", args=[product.pk]),
        {"post": "yes"},
    )

    assert response.status_code == 403
    assert Product.objects.filter(pk=product.pk).exists()


@pytest.mark.parametrize(
    "url_name",
    [
        "admin:catalog_product_changelist",
        "admin:catalog_product_add",
    ],
)
def test_product_admin_is_reachable_by_superusers_only(client, url_name):
    staff = get_user_model().objects.create_user(email="staff@example.com", is_staff=True)
    staff.user_permissions.set(Permission.objects.all())
    client.force_login(staff)

    response = client.get(reverse(url_name))

    assert response.status_code == 302
    assert response.url.startswith(reverse("admin:login"))


def test_admin_links_media_to_a_product(admin_client_by_email):
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    design = make_design(home, supplier)
    category = make_category(home)
    product = Product.objects.create(store=home, category=category, design=design)
    media = Media.objects.create(
        store=home,
        storage_key="stores/1/media/photo.jpg",
        content_hash="photo",
        mime_type="image/jpeg",
        width=800,
        height=600,
    )

    response = admin_client_by_email.post(
        f"/admin/catalog/product/{product.pk}/change/",
        {
            **product_form(home, category, design),
            **empty_inline("variants"),
            **inline(
                "product_media",
                [{"media": str(media.pk), "variant": "", "role": "main", "position": "1"}],
            ),
        },
    )

    assert response.status_code == 302
    link = ProductMedia.objects.get()
    assert link.product == product
    assert link.media == media
    assert link.role == ProductMedia.Role.MAIN


def test_product_media_inline_offers_only_the_products_store_media(admin_client_by_email):
    home = make_store("home", "Home")
    anime = make_store("anime", "Anime")
    supplier = make_supplier(home)
    design = make_design(home, supplier)
    category = make_category(home)
    product = Product.objects.create(store=home, category=category, design=design)
    home_media = Media.objects.create(
        store=home,
        storage_key="stores/1/media/home.jpg",
        content_hash="home",
        mime_type="image/jpeg",
        width=800,
        height=600,
    )
    Media.objects.create(
        store=anime,
        storage_key="stores/2/media/other.jpg",
        content_hash="other",
        mime_type="image/jpeg",
        width=800,
        height=600,
    )
    ProductMedia.objects.create(product=product, media=home_media)

    response = admin_client_by_email.get(f"/admin/catalog/product/{product.pk}/change/")

    assert response.status_code == 200
    formsets = [
        inline_formset.formset
        for inline_formset in response.context["inline_admin_formsets"]
        if inline_formset.formset.model is ProductMedia
    ]
    assert len(formsets) == 1
    field = formsets[0].forms[0].fields["media"]
    assert list(field.queryset) == [home_media]
    assert isinstance(field.widget.widget, AutocompleteSelect)


def test_admin_removes_the_link_but_not_the_media(admin_client_by_email):
    home = make_store("home", "Home")
    supplier = make_supplier(home)
    design = make_design(home, supplier)
    category = make_category(home)
    product = Product.objects.create(store=home, category=category, design=design)
    media = Media.objects.create(
        store=home,
        storage_key="stores/1/media/photo.jpg",
        content_hash="photo",
        mime_type="image/jpeg",
        width=800,
        height=600,
    )
    link = ProductMedia.objects.create(product=product, media=media)

    response = admin_client_by_email.post(
        f"/admin/catalog/product/{product.pk}/change/",
        {
            **product_form(home, category, design),
            **empty_inline("variants"),
            **inline(
                "product_media",
                [
                    {
                        "id": str(link.pk),
                        "media": str(media.pk),
                        "variant": "",
                        "role": "main",
                        "position": "1",
                        "DELETE": "on",
                    }
                ],
                initial=1,
            ),
        },
    )

    assert response.status_code == 302
    assert not ProductMedia.objects.filter(pk=link.pk).exists()
    assert Media.objects.filter(pk=media.pk).exists()
