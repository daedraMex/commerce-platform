import pytest


def assert_problem_details(response, *, status, code):
    assert response.status_code == status
    assert response["Content-Type"] == "application/problem+json"

    body = response.json()
    assert body["type"] == "about:blank"
    assert body["title"]
    assert body["status"] == status
    assert body["detail"]
    assert body["code"] == code
    return body


@pytest.fixture(autouse=True)
def use_test_urlconf(settings):
    settings.ROOT_URLCONF = "tests.api.urls_for_tests"


def test_protected_endpoint_without_credentials_returns_401(client):
    response = client.get("/api/v1/protected/")

    assert_problem_details(response, status=401, code="not_authenticated")


def test_domain_permission_error_returns_403(client):
    response = client.get("/api/v1/domain-permission/")

    body = assert_problem_details(response, status=403, code="permission_denied")
    assert body["detail"] == "You cannot do this."


def test_domain_not_found_error_returns_404(client):
    response = client.get("/api/v1/domain-not-found/")

    body = assert_problem_details(response, status=404, code="not_found")
    assert body["detail"] == "Product not found."


def test_django_permission_error_returns_403(client):
    response = client.get("/api/v1/django-permission/")

    assert_problem_details(response, status=403, code="permission_denied")


def test_django_not_found_error_returns_404(client):
    response = client.get("/api/v1/django-not-found/")

    assert_problem_details(response, status=404, code="not_found")


def test_validation_failure_returns_400_with_errors(client):
    response = client.post("/api/v1/validate/", {"name": ""}, content_type="application/json")

    body = assert_problem_details(response, status=400, code="validation_error")
    assert body["errors"] == [
        {
            "field": "name",
            "code": "blank",
            "detail": "This field may not be blank.",
        }
    ]


def test_unsupported_api_version_returns_problem_details(client, settings):
    settings.ROOT_URLCONF = "config.urls"

    response = client.get("/api/v2/health/live/")

    assert_problem_details(response, status=404, code="not_found")


def test_unknown_route_under_api_returns_problem_details(client, settings):
    settings.ROOT_URLCONF = "config.urls"

    response = client.get("/api/v1/does-not-exist/")

    assert_problem_details(response, status=404, code="not_found")


def test_lists_are_paginated_to_20_items_by_default(client):
    response = client.get("/api/v1/items/")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"count", "next", "previous", "results"}
    assert body["count"] == 150
    assert len(body["results"]) == 20
    assert body["next"] is not None
    assert body["previous"] is None


def test_page_size_query_parameter_is_honoured(client):
    body = client.get("/api/v1/items/?page_size=5").json()

    assert len(body["results"]) == 5


def test_page_size_is_capped_at_100(client):
    body = client.get("/api/v1/items/?page_size=1000").json()

    assert len(body["results"]) == 100
