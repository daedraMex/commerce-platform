import logging

import pytest

from tests.api.helpers import assert_problem_details

pytestmark = pytest.mark.django_db

READY_URL = "/api/v1/health/ready/"


def test_liveness_returns_200_without_credentials(client):
    response = client.get("/api/v1/health/live/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_returns_200_when_dependencies_are_up(client):
    response = client.get(READY_URL)

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"database": "ok", "redis": "ok"},
    }


@pytest.mark.parametrize(
    ("check_name", "expected_checks"),
    [
        ("check_database", {"database": "error", "redis": "ok"}),
        ("check_redis", {"database": "ok", "redis": "error"}),
    ],
)
def test_dependency_failure_returns_503_problem_details(
    client, monkeypatch, caplog, check_name, expected_checks
):
    caplog.set_level(logging.ERROR)

    def failing_check():
        raise RuntimeError("dependency password is hunter2")

    monkeypatch.setattr(f"apps.health.views.{check_name}", failing_check)

    response = client.get(READY_URL)

    body = assert_problem_details(response, status=503, code="service_unavailable")
    assert body["checks"] == expected_checks
    assert "hunter2" not in response.content.decode()
    assert any(
        check_name.removeprefix("check_") in record.getMessage() for record in caplog.records
    )
