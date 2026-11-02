import pytest
from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from apps.accounts.models import Permission, Role, StoreMembership
from apps.stores.models import Store
from tests.integration.admin_forms import STORE_ADMIN_EMPTY_INLINES, inline

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("url_name", "lookup"),
    [
        ("role", lambda: Role.objects.get(name="owner")),
        ("permission", lambda: Permission.objects.get(code="orders.refund")),
    ],
)
def test_roles_and_permissions_are_listed_and_shown_but_never_added_changed_or_deleted(
    admin_client_by_email, url_name, lookup
):
    obj = lookup()
    base = f"/admin/accounts/{url_name}/"

    assert admin_client_by_email.get(base).status_code == 200
    detail = admin_client_by_email.get(f"{base}{obj.pk}/change/")
    assert detail.status_code == 200
    assert b'name="_save"' not in detail.content
    assert admin_client_by_email.get(f"{base}add/").status_code == 403
    assert admin_client_by_email.post(f"{base}{obj.pk}/change/", {}).status_code == 403
    assert admin_client_by_email.post(f"{base}{obj.pk}/delete/", {"post": "yes"}).status_code == 403
    assert type(obj).objects.filter(pk=obj.pk).exists()


def test_the_seeded_matrix_survives_a_change_attempt_through_the_admin(admin_client_by_email):
    owner = Role.objects.get(name="owner")

    admin_client_by_email.post(
        f"/admin/accounts/role/{owner.pk}/change/", {"name": "boss", "permissions": []}
    )

    owner.refresh_from_db()
    assert owner.name == "owner"
    assert owner.permissions.count() == 5


def test_django_groups_are_not_in_the_admin(admin_client_by_email):
    assert not admin.site.is_registered(Group)
    assert admin_client_by_email.get("/admin/auth/group/").status_code == 404


def test_the_user_page_shows_the_users_memberships_inline(admin_client_by_email):
    user = get_user_model().objects.create_user(email="staff@example.com")
    store = Store.objects.create(slug="home", name="Home")
    StoreMembership.objects.create(user=user, store=store, role=Role.objects.get(name="warehouse"))

    response = admin_client_by_email.get(f"/admin/accounts/user/{user.pk}/change/")

    assert response.status_code == 200
    assert b'name="store_memberships-TOTAL_FORMS"' in response.content
    assert b'name="store_memberships-0-store"' in response.content


def test_adding_a_membership_on_the_store_page_is_recorded_in_the_admin_log(
    admin_client_by_email,
):
    user = get_user_model().objects.create_user(email="staff@example.com")
    store = Store.objects.create(slug="home", name="Home")
    support = Role.objects.get(name="support")

    response = admin_client_by_email.post(
        f"/admin/stores/store/{store.pk}/change/",
        {
            "name": "Home",
            "domain": "",
            "is_active": "on",
            **STORE_ADMIN_EMPTY_INLINES,
            **inline(
                "memberships",
                [{"user": str(user.pk), "role": str(support.pk), "is_active": "on"}],
            ),
        },
    )

    assert response.status_code == 302
    membership = StoreMembership.objects.get(user=user, store=store)
    assert membership.role == support
    entry = LogEntry.objects.get(object_id=str(store.pk))
    assert "store membership" in entry.get_change_message().lower()


def test_adding_a_membership_on_the_user_page_is_recorded_in_the_admin_log(
    admin_client_by_email, user, store
):
    warehouse = Role.objects.get(name="warehouse")

    response = admin_client_by_email.post(
        f"/admin/accounts/user/{user.pk}/change/",
        {
            "email": user.email,
            "is_active": "on",
            "date_joined_0": user.date_joined.strftime("%Y-%m-%d"),
            "date_joined_1": user.date_joined.strftime("%H:%M:%S"),
            "store_memberships-TOTAL_FORMS": "1",
            "store_memberships-INITIAL_FORMS": "0",
            "store_memberships-MIN_NUM_FORMS": "0",
            "store_memberships-MAX_NUM_FORMS": "1000",
            "store_memberships-0-store": str(store.pk),
            "store_memberships-0-role": str(warehouse.pk),
            "store_memberships-0-is_active": "on",
        },
    )

    assert response.status_code == 302
    assert StoreMembership.objects.get(user=user, store=store).role == warehouse
    entry = LogEntry.objects.get(object_id=str(user.pk))
    assert "store membership" in entry.get_change_message().lower()
