import pytest
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.services import grant_membership
from apps.stores.models import Store
from tests.api.helpers import assert_problem_details

pytestmark = pytest.mark.django_db

STAFF_ME_URL = "/api/v1/staff/me/"


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


def get_staff_me(client, user, slug):
    return client.get(STAFF_ME_URL, HTTP_AUTHORIZATION=bearer(user), HTTP_X_STORE=slug)


def test_staff_get_their_store_role_and_sorted_permissions(client, home, user):
    grant_membership(user=user, store=home, role_name="store_admin")

    response = get_staff_me(client, user, "home")

    assert response.status_code == 200
    assert response.json() == {
        "store": {"slug": "home", "name": "Home"},
        "role": "store_admin",
        "permissions": [
            "catalog.manage",
            "inventory.adjust",
            "orders.place_manual",
            "social.approve_post",
        ],
    }


def test_user_without_a_membership_in_the_store_gets_403(client, home, user):
    response = get_staff_me(client, user, "home")

    assert_problem_details(response, status=403, code="permission_denied")


def test_request_without_credentials_and_without_store_header_gets_401(client, home):
    response = client.get(STAFF_ME_URL)

    assert_problem_details(response, status=401, code="not_authenticated")


def test_request_with_credentials_and_without_store_header_gets_400(client, home, user):
    grant_membership(user=user, store=home, role_name="owner")

    response = client.get(STAFF_ME_URL, HTTP_AUTHORIZATION=bearer(user))

    assert_problem_details(response, status=400, code="store_header_missing")


def test_store_header_is_never_normalized_to_an_existing_store(client, home, user):
    grant_membership(user=user, store=home, role_name="owner")

    response = get_staff_me(client, user, "Home")

    assert_problem_details(response, status=400, code="store_header_invalid")


def test_well_formed_slug_without_a_store_gets_store_not_found(client, user):
    response = get_staff_me(client, user, "missing")

    assert_problem_details(response, status=400, code="store_not_found")


def test_inactive_store_gets_store_not_found_even_for_its_staff(client, home, user):
    grant_membership(user=user, store=home, role_name="owner")
    home.is_active = False
    home.save()

    response = get_staff_me(client, user, "home")

    assert_problem_details(response, status=400, code="store_not_found")


def test_staff_of_one_store_get_403_in_another_store(client, home, anime, user):
    grant_membership(user=user, store=home, role_name="owner")

    home_response = get_staff_me(client, user, "home")
    anime_response = get_staff_me(client, user, "anime")

    assert home_response.status_code == 200
    assert home_response.json()["store"] == {"slug": "home", "name": "Home"}
    assert_problem_details(anime_response, status=403, code="permission_denied")


def test_superuser_without_a_membership_gets_403(client, home):
    superuser = get_user_model().objects.create_superuser(
        email="root@example.com", password="s3cret-pass"
    )

    response = get_staff_me(client, superuser, "home")

    assert_problem_details(response, status=403, code="permission_denied")


def test_deactivating_a_membership_turns_200_into_403(client, home, user):
    membership = grant_membership(user=user, store=home, role_name="support")
    assert get_staff_me(client, user, "home").status_code == 200

    membership.is_active = False
    membership.save()

    response = get_staff_me(client, user, "home")
    assert_problem_details(response, status=403, code="permission_denied")


# Copied from the ADR-0021 table by hand and sorted, so it never derives from the seed.
@pytest.mark.parametrize(
    ("role_name", "permissions"),
    [
        (
            "owner",
            [
                "catalog.manage",
                "inventory.adjust",
                "orders.place_manual",
                "orders.refund",
                "social.approve_post",
            ],
        ),
        (
            "store_admin",
            [
                "catalog.manage",
                "inventory.adjust",
                "orders.place_manual",
                "social.approve_post",
            ],
        ),
        ("content_editor", ["catalog.manage"]),
        ("warehouse", ["inventory.adjust"]),
        ("support", ["orders.place_manual"]),
    ],
)
def test_permissions_match_the_seeded_matrix_for_the_role(
    client, home, user, role_name, permissions
):
    grant_membership(user=user, store=home, role_name=role_name)

    response = get_staff_me(client, user, "home")

    assert response.status_code == 200
    assert response.json()["role"] == role_name
    assert response.json()["permissions"] == permissions
