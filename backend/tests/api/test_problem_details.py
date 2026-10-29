import logging

import pytest

from tests.api.helpers import assert_problem_details


@pytest.fixture(autouse=True)
def use_test_urlconf(settings):
    settings.ROOT_URLCONF = "tests.api.urls_for_tests"


def test_protected_endpoint_without_credentials_returns_401(client):
    response = client.get("/api/v1/protected/")

    assert_problem_details(response, status=401, code="not_authenticated")
    assert response["WWW-Authenticate"].startswith("Bearer")


def test_invalid_bearer_token_returns_401_token_invalid(client):
    response = client.get(
        "/api/v1/protected/",
        HTTP_AUTHORIZATION="Bearer garbage",
    )

    assert_problem_details(response, status=401, code="token_invalid")
    assert response["WWW-Authenticate"].startswith("Bearer")


def test_method_not_allowed_returns_405_with_default_code(client):
    response = client.post("/api/v1/get-only/")

    assert_problem_details(response, status=405, code="method_not_allowed")
    assert "GET" in response["Allow"]


def test_throttled_returns_429_with_retry_after(client):
    response = client.get("/api/v1/throttled/")

    assert_problem_details(response, status=429, code="throttled")
    assert response["Retry-After"] == "7"


def test_malformed_json_returns_400_parse_error_without_errors_list(client):
    response = client.post(
        "/api/v1/validate/",
        data="{not json",
        content_type="application/json",
    )

    body = assert_problem_details(response, status=400, code="parse_error")
    assert "errors" not in body


def test_unmapped_domain_error_returns_500_and_is_logged(client, caplog):
    caplog.set_level(logging.ERROR)

    response = client.get("/api/v1/domain-unmapped/")

    body = assert_problem_details(response, status=500, code="internal_error")
    assert "Sensitive unmapped detail." not in body["detail"]
    assert any("Unmapped domain error" in record.getMessage() for record in caplog.records)


def test_unhandled_exception_returns_500_and_is_logged(client, caplog):
    caplog.set_level(logging.ERROR)

    response = client.get("/api/v1/exploding/")

    body = assert_problem_details(response, status=500, code="internal_error")
    assert "Sensitive unexpected detail." not in body["detail"]
    assert any("Unhandled API exception" in record.getMessage() for record in caplog.records)


def test_domain_permission_error_returns_403(client):
    response = client.get("/api/v1/domain-permission/")

    body = assert_problem_details(response, status=403, code="permission_denied")
    assert body["detail"] == "You cannot do this."


def test_domain_not_found_error_returns_404(client):
    response = client.get("/api/v1/domain-not-found/")

    body = assert_problem_details(response, status=404, code="not_found")
    assert body["detail"] == "Product not found."


def test_domain_not_found_subclass_keeps_its_code_and_status(client):
    response = client.get("/api/v1/product-not-found/")

    body = assert_problem_details(response, status=404, code="product_not_found")
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
