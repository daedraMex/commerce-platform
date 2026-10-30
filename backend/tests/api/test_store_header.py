import pytest
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import AccessToken

from apps.shared.domain.store import StoreReference
from apps.stores.models import Store
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


def get_store_scoped(client, auth_header, slug):
    return client.get(STORE_SCOPED_URL, HTTP_AUTHORIZATION=auth_header, HTTP_X_STORE=slug)


def test_anonymous_request_with_an_active_store_returns_401(client):
    Store.objects.create(slug="anime", name="Anime")

    response = client.get(STORE_SCOPED_URL, HTTP_X_STORE="anime")

    assert_problem_details(response, status=401, code="not_authenticated")


def test_anonymous_request_without_store_header_returns_401(client):
    response = client.get(STORE_SCOPED_URL)

    assert_problem_details(response, status=401, code="not_authenticated")


def test_missing_store_header_returns_400_problem_details(client, auth_header):
    response = client.get(STORE_SCOPED_URL, HTTP_AUTHORIZATION=auth_header)

    assert_problem_details(response, status=400, code="store_header_missing")


@pytest.mark.parametrize("slug", INVALID_STORE_SLUGS)
def test_malformed_store_header_returns_400_problem_details(client, auth_header, slug):
    response = get_store_scoped(client, auth_header, slug)

    assert_problem_details(response, status=400, code="store_header_invalid")


@pytest.mark.parametrize("slug", VALID_STORE_SLUGS)
def test_active_store_is_exposed_to_the_view_with_its_id_and_slug(client, auth_header, slug):
    store = Store.objects.create(slug=slug, name="Some store")

    response = get_store_scoped(client, auth_header, slug)

    assert response.status_code == 200
    assert response.json() == {"id": store.id, "slug": slug}


def test_store_header_resolves_only_the_named_store(client, auth_header):
    Store.objects.create(slug="anime", name="Anime")
    home = Store.objects.create(slug="home", name="Home")

    response = get_store_scoped(client, auth_header, "home")

    assert response.status_code == 200
    assert response.json() == {"id": home.id, "slug": "home"}


def test_well_formed_slug_without_a_store_returns_store_not_found(client, auth_header):
    response = get_store_scoped(client, auth_header, "missing")

    assert_problem_details(response, status=400, code="store_not_found")


def test_inactive_store_returns_store_not_found(client, auth_header):
    Store.objects.create(slug="home", name="Home", is_active=False)

    response = get_store_scoped(client, auth_header, "home")

    assert_problem_details(response, status=400, code="store_not_found")


def test_store_header_is_never_normalized_to_an_existing_store(client, auth_header):
    Store.objects.create(slug="home", name="Home")

    response = get_store_scoped(client, auth_header, "Home")

    assert_problem_details(response, status=400, code="store_header_invalid")


def test_tests_can_override_the_store_resolver(client, auth_header, override_store_resolver):
    class FakeStoreResolver:
        def resolve(self, slug):
            return StoreReference(id=42, slug=slug)

    override_store_resolver(FakeStoreResolver())

    response = get_store_scoped(client, auth_header, "no-such-store")

    assert response.status_code == 200
    assert response.json() == {"id": 42, "slug": "no-such-store"}
