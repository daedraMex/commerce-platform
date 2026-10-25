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
def job(workflow) -> dict:
    jobs = workflow["jobs"]
    assert len(jobs) == 1, f"expected a single CI job, got {sorted(jobs)}"
    return next(iter(jobs.values()))


def test_workflow_runs_on_pull_requests_and_pushes_to_main(workflow):
    triggers = workflow["on"]
    assert "pull_request" in triggers
    assert triggers["push"]["branches"] == ["main"]


def test_workflow_runs_the_services_tests_need(job):
    services = job["services"]
    assert services["postgres"]["image"] == "postgres:16"
    assert services["redis"]["image"] == "redis:7"


def test_workflow_points_django_at_the_services(job):
    env = job["env"]
    assert env["DATABASE_URL"].startswith("postgres://")
    assert env["REDIS_URL"].startswith("redis://")


def test_workflow_installs_with_the_lockfile_and_runs_every_check(job):
    commands = [step.get("run") for step in job["steps"]]
    for required in REQUIRED_STEPS:
        assert required in commands, f"missing CI step: {required}"


def test_no_step_hides_a_failure(job):
    for step in job["steps"]:
        assert step.get("continue-on-error", False) is False, step
