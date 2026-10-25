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
    component = schema["components"]["schemas"]["ProblemDetails"]
    properties = component["properties"]

    assert set(component["required"]) == {"type", "title", "status", "detail", "code"}
    assert set(properties) >= {"type", "title", "status", "detail", "code", "errors"}
    assert properties["errors"]["type"] == "array"
    assert set(properties["errors"]["items"]["required"]) == {"field", "code", "detail"}


def test_schema_documents_liveness_success_with_example(schema):
    operation = schema["paths"]["/api/v1/health/live/"]["get"]
    response = operation["responses"]["200"]
    examples = response["content"]["application/json"]["examples"].values()

    assert any(example["value"] == {"status": "ok"} for example in examples)
