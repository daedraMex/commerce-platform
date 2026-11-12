import pytest
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import Permission, Role
from apps.accounts.services import grant_membership
from apps.stores.models import Store
from tests.api.helpers import assert_problem_details

pytestmark = pytest.mark.django_db

ME_URL = "/api/v1/me/"
REMOVED_STAFF_ME_URL = "/api/v1/staff/me/"


@pytest.fixture
def home():
    return Store.objects.create(slug="home", name="Home")


@pytest.fixture
def anime():
    return Store.objects.create(slug="anime", name="Anime")


@pytest.fixture
def user():
    return get_user_model().objects.create_user(email="ana@example.com", password="s3cret-pass")


def bearer(user):
    return f"Bearer {AccessToken.for_user(user)}"


def get_me(client, user, **headers):
    return client.get(ME_URL, HTTP_AUTHORIZATION=bearer(user), **headers)


def test_platform_operator_without_memberships_gets_an_empty_list(client):
    operator = get_user_model().objects.create_superuser(
        email="root@example.com", password="s3cret-pass"
    )

    response = get_me(client, operator)

    assert response.status_code == 200
    assert response.json() == {
        "user": {"id": operator.id, "email": "root@example.com"},
        "memberships": [],
    }


def test_user_with_one_store_gets_its_store_role_and_sorted_permissions(client, home, user):
    grant_membership(user=user, store=home, role_name="store_admin")

    response = get_me(client, user)

    assert response.status_code == 200
    assert response.json() == {
        "user": {"id": user.id, "email": "ana@example.com"},
        "memberships": [
            {
                "store": {
                    "slug": "home",
                    "name": "Home",
                    "accent_color": "#4f46e5",
                },
                "role": "store_admin",
                "permissions": [
                    "catalog.manage",
                    "inventory.adjust",
                    "orders.place_manual",
                    "social.approve_post",
                ],
            }
        ],
    }


def test_user_with_two_stores_gets_both_memberships(client, home, anime, user):
    home.name = "Alpha Store"
    home.save()
    anime.name = "Zulu Store"
    anime.save()
    grant_membership(user=user, store=home, role_name="owner")
    grant_membership(user=user, store=anime, role_name="support")

    response = get_me(client, user)

    assert response.status_code == 200
    memberships = response.json()["memberships"]
    assert [membership["store"]["slug"] for membership in memberships] == ["home", "anime"]
    assert memberships[0]["role"] == "owner"
    assert memberships[0]["store"] == {
        "slug": "home",
        "name": "Alpha Store",
        "accent_color": "#4f46e5",
    }
    assert memberships[1]["role"] == "support"
    assert memberships[1]["permissions"] == ["orders.place_manual"]


def test_memberships_with_the_same_name_are_ordered_by_slug(client, home, anime, user):
    home.name = "Same Store"
    home.save()
    anime.name = "Same Store"
    anime.save()
    grant_membership(user=user, store=home, role_name="owner")
    grant_membership(user=user, store=anime, role_name="support")

    response = get_me(client, user)

    assert response.status_code == 200
    assert [membership["store"]["slug"] for membership in response.json()["memberships"]] == [
        "anime",
        "home",
    ]


def test_store_accent_color_is_returned(client, home, user):
    home.accent_color = "#123abc"
    home.save()
    grant_membership(user=user, store=home, role_name="owner")

    response = get_me(client, user)

    assert response.status_code == 200
    assert response.json()["memberships"][0]["store"]["accent_color"] == "#123abc"


def test_inactive_memberships_are_excluded(client, home, anime, user):
    grant_membership(user=user, store=home, role_name="owner")
    membership = grant_membership(user=user, store=anime, role_name="owner")
    membership.is_active = False
    membership.save()

    response = get_me(client, user)

    assert response.status_code == 200
    assert [membership["store"]["slug"] for membership in response.json()["memberships"]] == [
        "home"
    ]


def test_memberships_in_inactive_stores_are_excluded(client, home, anime, user):
    grant_membership(user=user, store=home, role_name="owner")
    grant_membership(user=user, store=anime, role_name="owner")
    anime.is_active = False
    anime.save()

    response = get_me(client, user)

    assert response.status_code == 200
    assert [membership["store"]["slug"] for membership in response.json()["memberships"]] == [
        "home"
    ]


def test_no_store_header_is_required(client, home, user):
    grant_membership(user=user, store=home, role_name="owner")

    response = client.get(ME_URL, HTTP_AUTHORIZATION=bearer(user))

    assert response.status_code == 200


def test_a_store_header_is_ignored_because_the_endpoint_is_global(client, home, user):
    grant_membership(user=user, store=home, role_name="owner")

    response = get_me(client, user, HTTP_X_STORE="missing")

    assert response.status_code == 200
    assert response.json()["memberships"][0]["store"]["slug"] == "home"


def test_permissions_are_sorted_alphabetically(client, home, user):
    role = Role.objects.create(name="custom")
    for code in ("orders.refund", "catalog.manage", "inventory.adjust"):
        role.permissions.add(Permission.objects.get(code=code))
    grant_membership(user=user, store=home, role_name="custom")

    response = get_me(client, user)

    assert response.status_code == 200
    assert response.json()["memberships"][0]["permissions"] == [
        "catalog.manage",
        "inventory.adjust",
        "orders.refund",
    ]


def test_request_without_credentials_gets_401(client):
    response = client.get(ME_URL)

    assert_problem_details(response, status=401, code="not_authenticated")


def test_the_removed_store_scoped_endpoint_is_gone(client, home, user):
    grant_membership(user=user, store=home, role_name="owner")

    response = client.get(
        REMOVED_STAFF_ME_URL,
        HTTP_AUTHORIZATION=bearer(user),
        HTTP_X_STORE="home",
    )

    assert_problem_details(response, status=404, code="not_found")
