import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture
def schema(client):
    response = client.get("/api/v1/schema/", HTTP_ACCEPT="application/json")

    assert response.status_code == 200
    return response.json()


def test_schema_is_public(client):
    response = client.get("/api/v1/schema/", HTTP_ACCEPT="application/json")

    assert response.status_code == 200


def test_docs_are_public(client):
    response = client.get("/api/v1/docs/")

    assert response.status_code == 200
    assert b"swagger" in response.content.lower()
    assert b"/api/v1/schema/" in response.content


def test_schema_declares_problem_details_component(schema):
    schemas = schema["components"]["schemas"]
    component = schemas["ProblemDetails"]
    properties = component["properties"]

    assert set(component["required"]) == {"type", "title", "status", "detail", "code"}
    assert set(properties) == {"type", "title", "status", "detail", "code", "errors"}
    assert properties["errors"]["type"] == "array"
    assert properties["errors"]["items"] == {"$ref": "#/components/schemas/FieldError"}

    field_error = schemas["FieldError"]
    assert set(field_error["required"]) == {"field", "code", "detail"}


def test_schema_documents_liveness_success_with_example(schema):
    operation = schema["paths"]["/api/v1/health/live/"]["get"]
    response = operation["responses"]["200"]
    examples = response["content"]["application/json"]["examples"].values()

    assert any(example["value"] == {"status": "ok", "version": "1.4.0"} for example in examples)


def test_schema_uses_a_fixed_liveness_example_regardless_of_app_version():
    env = {**os.environ, "APP_VERSION": "9.9.9"}
    result = subprocess.run(
        [sys.executable, "manage.py", "spectacular", "--format", "openapi-json"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    schema = json.loads(result.stdout)
    operation = schema["paths"]["/api/v1/health/live/"]["get"]
    examples = operation["responses"]["200"]["content"]["application/json"]["examples"].values()

    assert any(example["value"] == {"status": "ok", "version": "1.4.0"} for example in examples)


def test_schema_documents_the_liveness_version_field(schema):
    properties = schema["components"]["schemas"]["LivenessResponse"]["properties"]

    assert set(properties) == {"status", "version"}


def test_schema_documents_liveness_internal_error_with_problem_details(schema):
    operation = schema["paths"]["/api/v1/health/live/"]["get"]
    media = operation["responses"]["500"]["content"]["application/problem+json"]

    assert media["schema"] == {"$ref": "#/components/schemas/ProblemDetails"}
    assert any(
        example["value"]["code"] == "internal_error" for example in media["examples"].values()
    )


def test_schema_documents_readiness_success_with_example(schema):
    operation = schema["paths"]["/api/v1/health/ready/"]["get"]
    response = operation["responses"]["200"]
    examples = response["content"]["application/json"]["examples"].values()

    assert any(
        example["value"] == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}
        for example in examples
    )


def test_schema_documents_readiness_unavailable_with_problem_details(schema):
    operation = schema["paths"]["/api/v1/health/ready/"]["get"]
    media = operation["responses"]["503"]["content"]["application/problem+json"]

    assert media["schema"] == {"$ref": "#/components/schemas/ReadinessProblemDetails"}
    assert any(
        example["value"]["code"] == "service_unavailable"
        and example["value"]["checks"] == {"database": "error", "redis": "ok"}
        for example in media["examples"].values()
    )


@pytest.fixture
def test_view_schema(client, settings):
    settings.ROOT_URLCONF = "tests.api.urls_for_tests"

    response = client.get("/api/v1/schema/", HTTP_ACCEPT="application/json")

    assert response.status_code == 200
    return response.json()


def test_problem_response_helper_references_reusable_component(test_view_schema):
    operation = test_view_schema["paths"]["/api/v1/problem-response/"]["get"]
    media = operation["responses"]["404"]["content"]["application/problem+json"]

    assert media["schema"] == {"$ref": "#/components/schemas/ProblemDetails"}
    assert any(example["value"]["code"] == "not_found" for example in media["examples"].values())


def test_problem_response_helper_documents_several_codes_for_one_status(test_view_schema):
    operation = test_view_schema["paths"]["/api/v1/multi-problem-response/"]["get"]
    media = operation["responses"]["401"]["content"]["application/problem+json"]

    codes = {example["value"]["code"] for example in media["examples"].values()}
    assert codes == {"not_authenticated", "token_invalid"}


def test_schema_documents_token_obtain_with_an_example_per_status(schema):
    operation = schema["paths"]["/api/v1/auth/token/"]["post"]

    success = operation["responses"]["200"]["content"]["application/json"]
    assert any(
        "access" in example["value"] and "refresh" in example["value"]
        for example in success["examples"].values()
    )

    validation = operation["responses"]["400"]["content"]["application/problem+json"]
    assert any(
        example["value"]["code"] == "validation_error" and example["value"]["errors"]
        for example in validation["examples"].values()
    )

    unauthorized = operation["responses"]["401"]["content"]["application/problem+json"]
    assert any(
        example["value"]["code"] == "invalid_credentials"
        for example in unauthorized["examples"].values()
    )


def test_refresh_401_example_matches_the_invalid_token_response(client, schema):
    response = client.post(
        "/api/v1/auth/token/refresh/",
        {"refresh": "not-a-token"},
        content_type="application/json",
    )
    detail = response.json()["detail"]

    media = schema["paths"]["/api/v1/auth/token/refresh/"]["post"]["responses"]["401"]["content"][
        "application/problem+json"
    ]

    assert any(example["value"]["detail"] == detail for example in media["examples"].values())


def test_schema_documents_token_refresh_with_an_example_per_status(schema):
    operation = schema["paths"]["/api/v1/auth/token/refresh/"]["post"]

    success = operation["responses"]["200"]["content"]["application/json"]
    assert any("access" in example["value"] for example in success["examples"].values())

    validation = operation["responses"]["400"]["content"]["application/problem+json"]
    assert any(
        example["value"]["code"] == "validation_error"
        for example in validation["examples"].values()
    )

    unauthorized = operation["responses"]["401"]["content"]["application/problem+json"]
    assert any(
        example["value"]["code"] == "token_invalid" for example in unauthorized["examples"].values()
    )


def _example_codes(operation, status):
    media = operation["responses"][status]["content"]["application/problem+json"]
    assert media["schema"] == {"$ref": "#/components/schemas/ProblemDetails"}
    return {example["value"]["code"] for example in media["examples"].values()}


def test_schema_documents_staff_me_with_an_example_per_status(schema):
    operation = schema["paths"]["/api/v1/staff/me/"]["get"]

    success = operation["responses"]["200"]["content"]["application/json"]
    assert any(
        example["value"]
        == {
            "store": {"slug": "home", "name": "Home"},
            "role": "store_admin",
            "permissions": [
                "catalog.manage",
                "inventory.adjust",
                "orders.place_manual",
                "social.approve_post",
            ],
        }
        for example in success["examples"].values()
    )
    assert _example_codes(operation, "400") == {
        "store_header_missing",
        "store_header_invalid",
        "store_not_found",
    }
    assert _example_codes(operation, "401") == {"not_authenticated", "token_invalid"}
    assert _example_codes(operation, "403") == {"permission_denied"}


def test_schema_documents_staff_me_requires_the_store_header(schema):
    parameters = schema["paths"]["/api/v1/staff/me/"]["get"]["parameters"]

    assert any(
        parameter["name"] == "X-Store" and parameter["in"] == "header" and parameter["required"]
        for parameter in parameters
    )


def _parameter_names(operation):
    return {(parameter["name"], parameter["in"]) for parameter in operation["parameters"]}


def _success_example(operation):
    media = operation["responses"]["200"]["content"]["application/json"]
    return next(iter(media["examples"].values()))["value"]


def test_schema_documents_catalog_categories(schema):
    operation = schema["paths"]["/api/v1/catalog/categories/"]["get"]

    assert ("X-Store", "header") in _parameter_names(operation)
    assert _success_example(operation)[0]["slug"] == "frazada"
    assert _example_codes(operation, "400") == {
        "store_header_missing",
        "store_header_invalid",
        "store_not_found",
    }


def test_schema_documents_catalog_collections(schema):
    operation = schema["paths"]["/api/v1/catalog/collections/"]["get"]

    assert ("X-Store", "header") in _parameter_names(operation)
    assert _success_example(operation)[0]["slug"] == "halloween-2026"
    assert _example_codes(operation, "400") == {
        "store_header_missing",
        "store_header_invalid",
        "store_not_found",
    }


def test_schema_documents_the_catalog_product_list(schema):
    operation = schema["paths"]["/api/v1/catalog/products/"]["get"]

    assert {
        ("X-Store", "header"),
        ("category", "query"),
        ("collection", "query"),
        ("search", "query"),
    } <= _parameter_names(operation)
    example = _success_example(operation)
    assert example["results"][0]["slug"] == "frazada-termica"
    assert _example_codes(operation, "400") == {
        "store_header_missing",
        "store_header_invalid",
        "store_not_found",
    }


def test_schema_documents_catalog_product_detail(schema):
    operation = schema["paths"]["/api/v1/catalog/products/{slug}/"]["get"]

    assert {("X-Store", "header"), ("slug", "path")} <= _parameter_names(operation)
    assert _success_example(operation)["description"]
    assert _success_example(operation)["collections"][0]["slug"] == "halloween-2026"
    assert _example_codes(operation, "404") == {"not_found"}
    assert _example_codes(operation, "400") == {
        "store_header_missing",
        "store_header_invalid",
        "store_not_found",
    }


def test_schema_documents_the_catalog_variant_lookup(schema):
    operation = schema["paths"]["/api/v1/catalog/variants/{sku}/"]["get"]

    assert {("X-Store", "header"), ("sku", "path")} <= _parameter_names(operation)
    example = _success_example(operation)
    assert example["sku"] == "FRZ-00012-MAT"
    assert example["product"]["slug"] == "frazada-termica"
    assert _example_codes(operation, "404") == {"not_found"}
    assert _example_codes(operation, "400") == {
        "store_header_missing",
        "store_header_invalid",
        "store_not_found",
    }


def test_schema_documents_the_collection_filter_with_an_example(schema):
    operation = schema["paths"]["/api/v1/catalog/products/"]["get"]
    parameter = next(
        parameter for parameter in operation["parameters"] if parameter["name"] == "collection"
    )

    assert any(example["value"] == "halloween-2026" for example in parameter["examples"].values())
