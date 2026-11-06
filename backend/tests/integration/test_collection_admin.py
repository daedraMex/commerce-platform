import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse

from apps.catalog.models import Category, Collection, CollectionProduct, Product, Supplier
from apps.stores.models import Store
from tests.integration.admin_forms import inline

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


def collection_form(store, *, name="Halloween 2026", slug="", supplier=None):
    return {
        "store": str(store.pk),
        "name": name,
        "slug": slug,
        "description": "Seasonal blankets.",
        "supplier": str(supplier.pk) if supplier else "",
        "is_active": "on",
    }


def membership_row(product, position):
    return {"product": str(product.pk), "position": str(position)}


def test_admin_creates_a_collection_with_ordered_products(admin_client_by_email):
    home = make_store("home")
    first = make_product(home, name="First")
    second = make_product(home, name="Second")

    response = admin_client_by_email.post(
        "/admin/catalog/collection/add/",
        {
            **collection_form(home),
            **inline(
                "memberships",
                [membership_row(second, 1), membership_row(first, 2)],
            ),
        },
    )

    assert response.status_code == 302
    collection = Collection.objects.get()
    assert collection.slug == "halloween-2026"
    assert list(collection.memberships.values_list("product__name", flat=True)) == [
        "Second",
        "First",
    ]


def test_admin_rejects_a_product_of_another_store(admin_client_by_email):
    home = make_store("home")
    anime = make_store("anime")
    anime_product = make_product(anime)

    response = admin_client_by_email.post(
        "/admin/catalog/collection/add/",
        {
            **collection_form(home),
            **inline("memberships", [membership_row(anime_product, 1)]),
        },
    )

    assert response.status_code == 200
    assert b"must belong to the collection" in response.content
    assert not Collection.objects.exists()


def test_admin_rejects_a_supplier_of_another_store(admin_client_by_email):
    home = make_store("home")
    anime = make_store("anime")
    anime_supplier = Supplier.objects.create(store=anime, name="Kawaii")

    response = admin_client_by_email.post(
        "/admin/catalog/collection/add/",
        {
            **collection_form(home, supplier=anime_supplier),
            **inline("memberships"),
        },
    )

    assert response.status_code == 200
    assert b"supplier must belong to the collection" in response.content
    assert not Collection.objects.exists()


def test_collections_are_not_deleted_from_the_admin(admin_client_by_email):
    home = make_store("home")
    collection = Collection.objects.create(store=home, name="Halloween 2026")

    response = admin_client_by_email.post(
        reverse("admin:catalog_collection_delete", args=[collection.pk]),
        {"post": "yes"},
    )

    assert response.status_code == 403
    assert Collection.objects.filter(pk=collection.pk).exists()


@pytest.mark.parametrize(
    "url_name",
    [
        "admin:catalog_collection_changelist",
        "admin:catalog_collection_add",
    ],
)
def test_collection_admin_is_reachable_by_superusers_only(client, url_name):
    staff = get_user_model().objects.create_user(email="staff@example.com", is_staff=True)
    staff.user_permissions.set(Permission.objects.all())
    client.force_login(staff)

    response = client.get(reverse(url_name))

    assert response.status_code == 302
    assert response.url.startswith(reverse("admin:login"))


def test_the_collection_admin_lists_its_ordered_products(admin_client_by_email):
    home = make_store("home")
    product = make_product(home)
    collection = Collection.objects.create(store=home, name="Halloween 2026")
    CollectionProduct.objects.create(collection=collection, product=product, position=1)

    response = admin_client_by_email.get(f"/admin/catalog/collection/{collection.pk}/change/")

    assert response.status_code == 200
    assert product.name.encode() in response.content


def test_admin_removes_a_product_from_a_collection(admin_client_by_email):
    home = make_store("home")
    product = make_product(home)
    collection = Collection.objects.create(store=home, name="Halloween 2026")
    membership = CollectionProduct.objects.create(
        collection=collection, product=product, position=1
    )

    response = admin_client_by_email.post(
        f"/admin/catalog/collection/{collection.pk}/change/",
        {
            **collection_form(home),
            **inline(
                "memberships",
                [
                    {
                        "id": str(membership.pk),
                        "product": str(product.pk),
                        "position": "1",
                        "DELETE": "on",
                    }
                ],
                initial=1,
            ),
        },
    )

    assert response.status_code == 302
    assert not CollectionProduct.objects.exists()


@pytest.mark.parametrize(
    "url_name",
    [
        "admin:catalog_collection_changelist",
        "admin:catalog_collection_add",
    ],
)
def test_collection_admin_denies_inactive_users(client, url_name):
    staff = get_user_model().objects.create_user(
        email="inactive@example.com", is_staff=True, is_active=False
    )
    staff.user_permissions.set(Permission.objects.all())
    client.force_login(staff)

    response = client.get(reverse(url_name))

    assert response.status_code == 302
    assert response.url.startswith(reverse("admin:login"))


def test_admin_assigns_the_next_position_when_it_is_left_empty(admin_client_by_email):
    home = make_store("home")
    first = make_product(home, name="First")
    second = make_product(home, name="Second")
    third = make_product(home, name="Third")

    response = admin_client_by_email.post(
        "/admin/catalog/collection/add/",
        {
            **collection_form(home),
            **inline(
                "memberships",
                [
                    {"product": str(first.pk), "position": ""},
                    {"product": str(second.pk), "position": ""},
                    {"product": str(third.pk), "position": ""},
                ],
            ),
        },
    )

    assert response.status_code == 302
    collection = Collection.objects.get()
    assert list(collection.memberships.values_list("product__name", "position")) == [
        ("First", 1),
        ("Second", 2),
        ("Third", 3),
    ]
