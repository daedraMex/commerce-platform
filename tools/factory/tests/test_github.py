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
