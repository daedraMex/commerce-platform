from pathlib import Path

import pytest

from factory.git import (
    Git,
    GitVersionError,
    parse_git_version,
    verify_git_version,
)
from factory.shell import CommandResult


class RecordingRun:
    def __init__(self, result=None):
        self.result = result or CommandResult(exit_code=0, stdout="", stderr="")
        self.calls = []

    def __call__(self, argv, cwd, *, timeout, env=None, replace_env=False):
        self.calls.append((argv, cwd, env, replace_env))
        return self.result


def test_fetch_main_fetches_from_origin():
    run = RecordingRun()
    repo = Path("/srv/factory/repo")

    Git(run=run).fetch_main(repo)

    assert run.calls == [
        (["git", "fetch", "origin", "main"], str(repo), None, False),
    ]


def test_fetch_main_raises_when_the_fetch_fails():
    run = RecordingRun(CommandResult(exit_code=128, stdout="", stderr="could not read from remote"))

    with pytest.raises(RuntimeError, match="git fetch failed: could not read from remote"):
        Git(run=run).fetch_main(Path("/srv/factory/repo"))


def test_check_runs_the_script_as_the_agent_user_without_secrets():
    run = RecordingRun()
    worktree = Path("/srv/factory/worktrees/nf/1")

    Git(
        run=run,
        agent_user="factory-agent",
        agent_home="/home/factory-agent",
        base_env={
            "PATH": "/usr/bin",
            "HOME": "/home/factory",
            "LANG": "C",
            "DATABASE_URL": "postgres://db",
            "DEEPSEEK_API_KEY": "dk-123",
            "GH_TOKEN": "secret",
        },
    ).check(worktree)

    argv, cwd, env, replace_env = run.calls[0]
    assert argv == [
        "sudo",
        "-n",
        "--preserve-env=PATH,HOME,LANG,DATABASE_URL",
        "-u",
        "factory-agent",
        "--",
        str(worktree / "backend" / "scripts" / "check.sh"),
    ]
    assert cwd == str(worktree / "backend")
    assert replace_env is True
    assert env == {
        "PATH": "/usr/bin",
        "HOME": "/home/factory-agent",
        "LANG": "C",
        "DATABASE_URL": "postgres://db",
    }


def test_check_truncates_output_fed_to_the_agent():
    run = RecordingRun(CommandResult(exit_code=1, stdout="x" * 9000, stderr=""))

    passed, output = Git(run=run).check(Path("/work"))

    assert passed is False
    assert len(output) < 9000
    assert output.endswith("x" * 100)
    assert "truncated" in output


def test_commit_never_runs_hooks():
    run = RecordingRun()
    worktree = Path("/work")

    Git(run=run).commit_all(worktree, "feat: something")

    assert run.calls[1][0] == [
        "git",
        "-c",
        "core.hooksPath=/dev/null",
        "commit",
        "--no-verify",
        "-m",
        "feat: something",
    ]


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("git version 2.43.0", (2, 43, 0)),
        ("git version 2.46.1", (2, 46, 1)),
        ("git version 2.47.0.windows.1", (2, 47, 0)),
    ],
)
def test_parse_git_version(output, expected):
    assert parse_git_version(output) == expected


def test_verify_git_version_accepts_2_46_and_newer():
    verify_git_version(run=RecordingRun(CommandResult(0, "git version 2.46.1", "")))


def test_verify_git_version_rejects_older_and_names_the_ppa():
    with pytest.raises(GitVersionError, match="ppa:git-core/ppa"):
        verify_git_version(run=RecordingRun(CommandResult(0, "git version 2.43.0", "")))


def test_verify_git_version_rejects_unparseable_output():
    with pytest.raises(GitVersionError, match="could not determine"):
        verify_git_version(run=RecordingRun(CommandResult(0, "not git", "")))


def test_verify_git_version_rejects_a_failed_command():
    with pytest.raises(GitVersionError, match="could not determine"):
        verify_git_version(run=RecordingRun(CommandResult(127, "", "git: command not found")))
