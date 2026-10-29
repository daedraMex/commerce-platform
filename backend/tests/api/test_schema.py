import pytest


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

    assert any(example["value"] == {"status": "ok"} for example in examples)


def test_schema_documents_liveness_internal_error_with_problem_details(schema):
    operation = schema["paths"]["/api/v1/health/live/"]["get"]
    media = operation["responses"]["500"]["content"]["application/problem+json"]

    assert media["schema"] == {"$ref": "#/components/schemas/ProblemDetails"}
    assert any(
        example["value"]["code"] == "internal_error" for example in media["examples"].values()
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
