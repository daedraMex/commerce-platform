import pytest

from tests.api.helpers import assert_problem_details

pytestmark = pytest.mark.django_db

STORE_SCOPED_URL = "/api/v1/store-scoped/"
LIVENESS_URL = "/api/v1/health/live/"


@pytest.fixture(autouse=True)
def use_test_urlconf(settings):
    settings.ROOT_URLCONF = "tests.api.urls_for_tests"


def test_missing_store_header_returns_400_problem_details(client):
    response = client.get(STORE_SCOPED_URL)

    assert_problem_details(response, status=400, code="store_header_missing")


@pytest.mark.parametrize(
    "slug",
    [
        "Anime",
        " anime ",
        "-anime",
        "anime-",
        "anime--store",
        "anime_store",
        "",
        "a" * 51,
    ],
)
def test_malformed_store_header_returns_400_problem_details(client, slug):
    response = client.get(STORE_SCOPED_URL, HTTP_X_STORE=slug)

    assert_problem_details(response, status=400, code="store_header_invalid")


@pytest.mark.parametrize("slug", ["anime", "a" * 50])
def test_valid_store_header_exposes_the_store_to_the_view(client, slug):
    response = client.get(STORE_SCOPED_URL, HTTP_X_STORE=slug)

    assert response.status_code == 200
    assert response.json() == {"slug": slug}


@pytest.mark.parametrize("slug", ["anime", "Not A Slug"])
def test_liveness_ignores_the_store_header(client, settings, slug):
    settings.ROOT_URLCONF = "config.urls"

    response = client.get(LIVENESS_URL, HTTP_X_STORE=slug)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
