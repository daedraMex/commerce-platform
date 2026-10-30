import pytest
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import AccessToken

from tests.api.helpers import assert_problem_details
from tests.store_slugs import INVALID_STORE_SLUGS, VALID_STORE_SLUGS

pytestmark = pytest.mark.django_db

STORE_SCOPED_URL = "/api/v1/store-scoped/"


@pytest.fixture(autouse=True)
def use_test_urlconf(settings):
    settings.ROOT_URLCONF = "tests.api.urls_for_tests"


@pytest.fixture
def auth_header():
    user = get_user_model().objects.create_user(
        email="ana@example.com",
        password="s3cret-pass",
    )
    return f"Bearer {AccessToken.for_user(user)}"


def test_anonymous_request_with_valid_store_header_returns_401(client):
    response = client.get(STORE_SCOPED_URL, HTTP_X_STORE="anime")

    assert_problem_details(response, status=401, code="not_authenticated")


def test_missing_store_header_returns_400_problem_details(client, auth_header):
    response = client.get(STORE_SCOPED_URL, HTTP_AUTHORIZATION=auth_header)

    assert_problem_details(response, status=400, code="store_header_missing")


@pytest.mark.parametrize("slug", INVALID_STORE_SLUGS)
def test_malformed_store_header_returns_400_problem_details(client, auth_header, slug):
    response = client.get(
        STORE_SCOPED_URL,
        HTTP_AUTHORIZATION=auth_header,
        HTTP_X_STORE=slug,
    )

    assert_problem_details(response, status=400, code="store_header_invalid")


@pytest.mark.parametrize("slug", VALID_STORE_SLUGS)
def test_valid_store_header_exposes_the_store_to_the_view(client, auth_header, slug):
    response = client.get(
        STORE_SCOPED_URL,
        HTTP_AUTHORIZATION=auth_header,
        HTTP_X_STORE=slug,
    )

    assert response.status_code == 200
    assert response.json() == {"slug": slug}
