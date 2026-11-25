import re
from pathlib import Path

CI = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"


def _factory_job() -> str:
    text = CI.read_text()
    match = re.search(r"^  factory:\n(.*?)(?=^  \S|\Z)", text, re.MULTILINE | re.DOTALL)
    assert match, "ci.yml has no factory job"
    return match.group(1)


def test_ci_has_a_factory_job_named_for_the_required_checks():
    assert "    name: Factory\n" in _factory_job()


def test_factory_job_runs_in_tools_factory():
    assert "working-directory: tools/factory" in _factory_job()


def test_factory_job_checks_the_lock_lint_format_and_tests():
    job = _factory_job()
    for command in (
        "uv lock --check",
        "uv run --locked ruff check .",
        "uv run --locked ruff format --check .",
        "uv run --locked pytest -q",
    ):
        assert f"run: {command}\n" in job, command


def test_factory_job_runs_only_for_factory_changes():
    job = _factory_job()
    assert "^(tools/factory/|docs/factory\\.md$|\\.github/workflows/)" in job
    # Every check step is gated, so the job still reports (and passes) when skipped.
    steps = re.findall(r"- name: (?:Lock file|Lint|Format|Tests)\n(.*?)run:", job, re.DOTALL)
    assert len(steps) == 4
    for step in steps:
        assert "if: steps.changes.outputs.relevant == 'true'" in step


def test_factory_job_pins_every_action_to_a_commit_sha():
    uses = re.findall(r"uses: (\S+)", _factory_job())
    assert uses
    for ref in uses:
        assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref), ref
