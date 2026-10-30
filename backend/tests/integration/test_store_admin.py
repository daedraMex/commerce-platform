import pytest

from apps.stores.models import Store

pytestmark = pytest.mark.django_db


def test_admin_lists_stores(admin_client_by_email):
    Store.objects.create(slug="anime", name="Anime")
    Store.objects.create(slug="home", name="Home")

    response = admin_client_by_email.get("/admin/stores/store/")

    assert response.status_code == 200
    assert b"anime" in response.content
    assert b"home" in response.content


def test_admin_deactivates_a_store(admin_client_by_email):
    store = Store.objects.create(slug="home", name="Home")

    response = admin_client_by_email.post(
        f"/admin/stores/store/{store.pk}/change/",
        # An unchecked checkbox is left out of the form, which clears is_active.
        {"slug": "home", "name": "Home", "domain": ""},
    )

    assert response.status_code == 302
    store.refresh_from_db()
    assert store.is_active is False


def test_admin_stores_a_blank_domain_as_null_and_a_domain_lowercase(admin_client_by_email):
    admin_client_by_email.post(
        "/admin/stores/store/add/", {"slug": "anime", "name": "Anime", "domain": ""}
    )
    admin_client_by_email.post(
        "/admin/stores/store/add/", {"slug": "home", "name": "Home", "domain": ""}
    )
    admin_client_by_email.post(
        "/admin/stores/store/add/",
        {"slug": "blankets", "name": "Blankets", "domain": "Blankets.Example.com"},
    )

    domains = dict(Store.objects.values_list("slug", "domain"))
    assert domains == {"anime": None, "home": None, "blankets": "blankets.example.com"}


def test_admin_never_deletes_a_store(admin_client_by_email):
    store = Store.objects.create(slug="home", name="Home")

    response = admin_client_by_email.post(
        f"/admin/stores/store/{store.pk}/delete/", {"post": "yes"}
    )

    assert response.status_code == 403
    assert Store.objects.filter(pk=store.pk).exists()


def test_admin_rejects_a_malformed_slug(admin_client_by_email):
    response = admin_client_by_email.post(
        "/admin/stores/store/add/", {"slug": "Home", "name": "Home", "domain": ""}
    )

    assert response.status_code == 200
    assert not Store.objects.exists()
