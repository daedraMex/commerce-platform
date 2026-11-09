from pathlib import Path

import pytest

from factory.git import (
    BOT_COMMIT_NAME,
    Git,
    GitIdentityError,
    GitVersionError,
    bot_commit_email,
    commit_identity_args,
    parse_git_version,
    verify_git_version,
)
from factory.runner import TEST_SETTINGS
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


def test_worktree_exists_reads_the_porcelain_list():
    stdout = "worktree /srv/factory/repo\n\nworktree /srv/factory/worktrees/nf-7-x\n"
    run = RecordingRun(CommandResult(0, stdout, ""))
    repo = Path("/srv/factory/repo")

    assert Git(run=run).worktree_exists(repo, Path("/srv/factory/worktrees/nf-7-x")) is True
    assert Git(run=run).worktree_exists(repo, Path("/srv/factory/worktrees/other")) is False
    assert run.calls[0][0] == ["git", "worktree", "list", "--porcelain"]


def test_branch_exists_checks_the_local_branch_only():
    run = RecordingRun(CommandResult(0, "", ""))
    repo = Path("/srv/factory/repo")

    assert Git(run=run).branch_exists(repo, "nf/7-x") is True
    assert run.calls[0][0] == [
        "git",
        "show-ref",
        "--verify",
        "--quiet",
        "refs/heads/nf/7-x",
    ]


def test_create_worktree_raises_a_clear_error_on_failure():
    run = RecordingRun(CommandResult(128, "", "fatal: a branch named 'nf/7-x' already exists"))
    repo = Path("/srv/factory/repo")
    worktree = Path("/srv/factory/worktrees/nf-7-x")

    with pytest.raises(RuntimeError, match="could not create worktree for nf/7-x"):
        Git(run=run).create_worktree(repo, worktree, "nf/7-x")


def test_delete_branch_forces_branch_removal():
    run = RecordingRun()
    repo = Path("/srv/factory/repo")

    Git(run=run).delete_branch(repo, "preflight-42")

    assert run.calls == [
        (["git", "branch", "-D", "preflight-42"], str(repo), None, False),
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
        "--preserve-env=PATH,HOME,LANG,DATABASE_URL,SECRET_KEY,DEBUG,ALLOWED_HOSTS,REDIS_URL",
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
        **TEST_SETTINGS,
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

    Git(run=run, bot_user_id="12345").commit_all(worktree, "feat: something")

    assert run.calls[1][0] == [
        "git",
        "-c",
        "user.name=xolo-bot[bot]",
        "-c",
        "user.email=12345+xolo-bot[bot]@users.noreply.github.com",
        "-c",
        "core.hooksPath=/dev/null",
        "commit",
        "--no-verify",
        "-m",
        "feat: something",
    ]


def test_bot_commit_identity_uses_the_github_noreply_address():
    assert BOT_COMMIT_NAME == "xolo-bot[bot]"
    assert bot_commit_email("12345") == "12345+xolo-bot[bot]@users.noreply.github.com"


def test_commit_identity_args_are_explicit_git_config():
    assert commit_identity_args("12345") == [
        "-c",
        "user.name=xolo-bot[bot]",
        "-c",
        "user.email=12345+xolo-bot[bot]@users.noreply.github.com",
    ]


def test_commit_requires_the_bot_user_id_before_staging():
    run = RecordingRun()

    with pytest.raises(GitIdentityError, match="XOLO_BOT_USER_ID"):
        Git(run=run).commit_all(Path("/work"), "feat: something")

    assert run.calls == []


def test_verify_commit_identity_is_a_dry_git_var_check():
    run = RecordingRun()
    repo = Path("/srv/factory/repo")

    Git(run=run, bot_user_id="12345").verify_commit_identity(repo)

    identity = [
        "-c",
        "user.name=xolo-bot[bot]",
        "-c",
        "user.email=12345+xolo-bot[bot]@users.noreply.github.com",
    ]
    assert run.calls == [
        (["git", *identity, "var", "GIT_AUTHOR_IDENT"], str(repo), None, False),
        (["git", *identity, "var", "GIT_COMMITTER_IDENT"], str(repo), None, False),
    ]


def test_verify_commit_identity_raises_when_git_cannot_build_it():
    run = RecordingRun(CommandResult(exit_code=128, stdout="", stderr="Author identity unknown"))

    with pytest.raises(GitIdentityError, match="Author identity unknown"):
        Git(run=run, bot_user_id="12345").verify_commit_identity(Path("/srv/factory/repo"))


def test_verify_commit_identity_requires_the_bot_user_id():
    run = RecordingRun()

    with pytest.raises(GitIdentityError, match="XOLO_BOT_USER_ID"):
        Git(run=run).verify_commit_identity(Path("/srv/factory/repo"))

    assert run.calls == []


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
