from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"

REQUIRED_STEPS = [
    "uv sync --locked",
    "uv run ruff check .",
    "uv run ruff format --check .",
    "uv run python manage.py makemigrations --check --dry-run",
    "uv run pytest",
]


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def backend_job(workflow) -> dict:
    return workflow["jobs"]["backend"]


def triggers(workflow: dict) -> dict:
    # PyYAML reads unquoted `on` as the boolean True, so accept both spellings.
    return workflow["on"] if "on" in workflow else workflow[True]


def test_workflow_runs_on_pull_requests_and_pushes_to_main(workflow):
    events = triggers(workflow)
    assert "pull_request" in events
    assert events["push"]["branches"] == ["main"]


def test_workflow_runs_the_services_tests_need(backend_job):
    services = backend_job["services"]
    assert services["postgres"]["image"] == "postgres:16"
    assert services["redis"]["image"] == "redis:7"


def test_workflow_points_django_at_the_services(backend_job):
    env = backend_job["env"]
    assert env["DATABASE_URL"].startswith("postgres://")
    assert env["REDIS_URL"].startswith("redis://")


def test_workflow_installs_with_the_lockfile_and_runs_every_check(backend_job):
    commands = [step.get("run", "") for step in backend_job["steps"]]
    for required in REQUIRED_STEPS:
        assert any(required in command for command in commands), f"missing CI step: {required}"


def test_no_step_hides_a_failure(backend_job):
    for step in backend_job["steps"]:
        assert step.get("continue-on-error", False) is False, step
