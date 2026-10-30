import pytest

from tests.api.helpers import assert_problem_details
from tests.store_slugs import INVALID_STORE_SLUGS, VALID_STORE_SLUGS

STORE_SCOPED_URL = "/api/v1/store-scoped/"


@pytest.fixture(autouse=True)
def use_test_urlconf(settings):
    settings.ROOT_URLCONF = "tests.api.urls_for_tests"


def test_missing_store_header_returns_400_problem_details(client):
    response = client.get(STORE_SCOPED_URL)

    assert_problem_details(response, status=400, code="store_header_missing")


@pytest.mark.parametrize("slug", INVALID_STORE_SLUGS)
def test_malformed_store_header_returns_400_problem_details(client, slug):
    response = client.get(STORE_SCOPED_URL, HTTP_X_STORE=slug)

    assert_problem_details(response, status=400, code="store_header_invalid")


@pytest.mark.parametrize("slug", VALID_STORE_SLUGS)
def test_valid_store_header_exposes_the_store_to_the_view(client, slug):
    response = client.get(STORE_SCOPED_URL, HTTP_X_STORE=slug)

    assert response.status_code == 200
    assert response.json() == {"slug": slug}
