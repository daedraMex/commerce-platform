import logging
import time

import pytest
from django.test import override_settings

from tests.api.helpers import assert_problem_details

pytestmark = pytest.mark.django_db

LIVE_URL = "/api/v1/health/live/"
READY_URL = "/api/v1/health/ready/"


def test_liveness_returns_200_without_credentials(client):
    response = client.get(LIVE_URL)

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "dev"}


@pytest.mark.parametrize("store_header", ["anime", "Not A Slug"])
def test_liveness_ignores_the_store_header(client, store_header):
    response = client.get(LIVE_URL, HTTP_X_STORE=store_header)

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "dev"}


@override_settings(APP_VERSION="1.2.3")
def test_liveness_reports_the_configured_app_version(client):
    response = client.get(LIVE_URL)

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "1.2.3"}


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


def test_slow_check_counts_as_error_within_deadline(client, monkeypatch, caplog):
    caplog.set_level(logging.ERROR)

    def slow_check():
        time.sleep(2)

    monkeypatch.setattr("apps.health.views.check_database", slow_check)

    started = time.monotonic()
    response = client.get(READY_URL)
    elapsed = time.monotonic() - started

    body = assert_problem_details(response, status=503, code="service_unavailable")
    assert body["checks"] == {"database": "error", "redis": "ok"}
    assert elapsed < 1.5
    assert any(
        "database" in record.getMessage()
        and "timed out" in record.getMessage()
        and record.levelno == logging.ERROR
        for record in caplog.records
    )
