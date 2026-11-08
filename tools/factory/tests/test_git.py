from pathlib import Path

from factory.git import Git
from factory.shell import CommandResult


class RecordingRun:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, cwd, *, timeout, env=None, replace_env=False):
        self.calls.append((argv, cwd))
        return CommandResult(exit_code=0, stdout="", stderr="")


def test_fetch_main_fetches_from_origin():
    run = RecordingRun()
    repo = Path("/srv/factory/repo")

    Git(run=run).fetch_main(repo)

    assert run.calls == [(["git", "fetch", "origin", "main"], str(repo))]
