from pathlib import Path

from factory.git import Git
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
