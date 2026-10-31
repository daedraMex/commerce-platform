import pytest
from django.contrib.auth import get_user_model

from apps.accounts.models import Role, StoreMembership
from apps.stores.models import Store, StoreFeatureFlag
from tests.integration.admin_forms import empty_inline

NO_INLINES = {**empty_inline("memberships"), **empty_inline("feature_flags")}

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
        {"slug": "home", "name": "Home", "domain": "", **NO_INLINES},
    )

    assert response.status_code == 302
    store.refresh_from_db()
    assert store.is_active is False


def test_admin_stores_a_blank_domain_as_null_and_a_domain_lowercase(admin_client_by_email):
    admin_client_by_email.post(
        "/admin/stores/store/add/",
        {"slug": "anime", "name": "Anime", "domain": "", **NO_INLINES},
    )
    admin_client_by_email.post(
        "/admin/stores/store/add/", {"slug": "home", "name": "Home", "domain": "", **NO_INLINES}
    )
    admin_client_by_email.post(
        "/admin/stores/store/add/",
        {
            "slug": "blankets",
            "name": "Blankets",
            "domain": "Blankets.Example.com",
            **NO_INLINES,
        },
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
        "/admin/stores/store/add/", {"slug": "Home", "name": "Home", "domain": "", **NO_INLINES}
    )

    assert response.status_code == 200
    assert not Store.objects.exists()


def test_admin_does_not_rename_an_existing_store(admin_client_by_email):
    store = Store.objects.create(slug="home", name="Home")

    admin_client_by_email.post(
        f"/admin/stores/store/{store.pk}/change/",
        {"slug": "blankets", "name": "Home", "domain": "", "is_active": "on", **NO_INLINES},
    )

    store.refresh_from_db()
    assert store.slug == "home"


def _membership(store):
    user = get_user_model().objects.create_user(email="staff@example.com")
    return StoreMembership.objects.create(user=user, store=store, role=Role.objects.first())


def test_admin_offers_no_delete_checkbox_for_a_membership(admin_client_by_email):
    store = Store.objects.create(slug="home", name="Home")
    _membership(store)

    response = admin_client_by_email.get(f"/admin/stores/store/{store.pk}/change/")

    assert response.status_code == 200
    assert b'name="memberships-0-DELETE"' not in response.content


def test_admin_posting_a_membership_delete_leaves_the_row(admin_client_by_email):
    store = Store.objects.create(slug="home", name="Home")
    membership = _membership(store)

    response = admin_client_by_email.post(
        f"/admin/stores/store/{store.pk}/change/",
        {
            "slug": "home",
            "name": "Home",
            "domain": "",
            "is_active": "on",
            "memberships-TOTAL_FORMS": "1",
            "memberships-INITIAL_FORMS": "1",
            "memberships-MIN_NUM_FORMS": "0",
            "memberships-MAX_NUM_FORMS": "1000",
            "memberships-0-id": str(membership.pk),
            "memberships-0-store": str(store.pk),
            "memberships-0-user": str(membership.user_id),
            "memberships-0-role": str(membership.role_id),
            "memberships-0-is_active": "on",
            "memberships-0-DELETE": "on",
            **empty_inline("feature_flags"),
        },
    )

    assert response.status_code == 302
    assert StoreMembership.objects.filter(pk=membership.pk, is_active=True).exists()


def test_admin_shows_feature_flags_as_an_inline(admin_client_by_email):
    store = Store.objects.create(slug="home", name="Home")
    StoreFeatureFlag.objects.create(store=store, code="instagram-publishing", enabled=True)

    response = admin_client_by_email.get(f"/admin/stores/store/{store.pk}/change/")

    assert response.status_code == 200
    assert b'name="feature_flags-0-code"' in response.content
    assert b'value="instagram-publishing"' in response.content


def test_admin_turns_a_feature_flag_on_for_a_store(admin_client_by_email):
    store = Store.objects.create(slug="home", name="Home")

    response = admin_client_by_email.post(
        f"/admin/stores/store/{store.pk}/change/",
        {
            "slug": "home",
            "name": "Home",
            "domain": "",
            "is_active": "on",
            **empty_inline("memberships"),
            "feature_flags-TOTAL_FORMS": "1",
            "feature_flags-INITIAL_FORMS": "0",
            "feature_flags-MIN_NUM_FORMS": "0",
            "feature_flags-MAX_NUM_FORMS": "1000",
            "feature_flags-0-store": str(store.pk),
            "feature_flags-0-code": "instagram-publishing",
            "feature_flags-0-enabled": "on",
        },
    )

    assert response.status_code == 302
    assert StoreFeatureFlag.objects.filter(
        store=store, code="instagram-publishing", enabled=True
    ).exists()
