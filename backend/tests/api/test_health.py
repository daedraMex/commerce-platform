import copy
import logging

import pytest
from django.conf import settings

from apps.health.views import check_database
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


def test_database_failure_returns_503_problem_details(client, monkeypatch, caplog):
    caplog.set_level(logging.ERROR)

    def failing_database():
        raise RuntimeError("database password is hunter2")

    monkeypatch.setattr("apps.health.views.check_database", failing_database)

    response = client.get(READY_URL)

    body = assert_problem_details(response, status=503, code="service_unavailable")
    assert body["checks"] == {"database": "error", "redis": "ok"}
    assert "hunter2" not in response.content.decode()
    assert any("database" in record.getMessage() for record in caplog.records)


def test_redis_failure_returns_503_problem_details(client, monkeypatch, caplog):
    caplog.set_level(logging.ERROR)

    def failing_redis():
        raise RuntimeError("redis password is hunter2")

    monkeypatch.setattr("apps.health.views.check_redis", failing_redis)

    response = client.get(READY_URL)

    body = assert_problem_details(response, status=503, code="service_unavailable")
    assert body["checks"] == {"database": "ok", "redis": "error"}
    assert "hunter2" not in response.content.decode()
    assert any("redis" in record.getMessage() for record in caplog.records)


def test_database_check_does_not_change_global_database_settings():
    before = copy.deepcopy(settings.DATABASES)

    check_database()

    assert settings.DATABASES == before
