import json

from factory.github import GitHub
from factory.shell import CommandResult


class RecordingRun:
    def __init__(self, stdout="[]"):
        self.stdout = stdout
        self.calls = []

    def __call__(self, argv, cwd, *, timeout, env=None, replace_env=False):
        self.calls.append((argv, cwd, env))
        return CommandResult(exit_code=0, stdout=self.stdout, stderr="")


def test_list_tickets_uses_gh_token_for_every_read():
    run = RecordingRun()
    GitHub("daedraMex/commerce-platform", run=run).list_tickets("TOKEN")

    assert run.calls[0][0][:3] == ["gh", "issue", "list"]
    assert run.calls[1][0][:3] == ["gh", "pr", "list"]
    assert all(env == {"GH_TOKEN": "TOKEN"} for _argv, _cwd, env in run.calls)


def test_list_tickets_without_token_leaves_env_to_gh():
    run = RecordingRun()
    GitHub("daedraMex/commerce-platform", run=run).list_tickets()

    assert all(env is None for _argv, _cwd, env in run.calls)


class FakeGh:
    """Answers the reads list_tickets makes with realistic gh JSON shapes."""

    def __init__(self, issues):
        self.issues = issues
        self.calls = []

    def __call__(self, argv, cwd, *, timeout, env=None, replace_env=False):
        self.calls.append(argv)
        if argv[:3] == ["gh", "issue", "list"]:
            return CommandResult(exit_code=0, stdout=json.dumps(self.issues), stderr="")
        if argv[:3] == ["gh", "pr", "list"]:
            return CommandResult(exit_code=0, stdout="[]", stderr="")
        return CommandResult(exit_code=0, stdout="{}", stderr="")


def test_list_tickets_reads_label_names_from_gh_label_objects():
    # `gh issue list --json labels` returns label objects, not strings.
    issues = [
        {
            "number": 7,
            "title": "Add widget endpoint",
            "body": "",
            "labels": [
                {"id": "LA_1", "name": "ready-for-agent", "description": "", "color": "0e8a16"},
                {"id": "LA_2", "name": "strong-model", "description": None, "color": "ededed"},
            ],
        }
    ]
    run = FakeGh(issues)

    tickets = GitHub("daedraMex/commerce-platform", run=run).list_tickets("TOKEN")

    assert len(tickets) == 1
    assert tickets[0].number == 7
    assert tickets[0].labels == frozenset({"ready-for-agent", "strong-model"})
