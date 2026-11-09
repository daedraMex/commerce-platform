from pathlib import Path

import pytest

from factory.git import (
    BOT_COMMIT_NAME,
    CLEANUP_PROBE_SCRIPT,
    Git,
    GitIdentityError,
    GitVersionError,
    WorktreeCleanupError,
    bot_commit_email,
    commit_identity_args,
    parse_git_version,
    verify_git_version,
    worktree_cleanup_path,
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


class SequenceRun:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, argv, cwd, *, timeout, env=None, replace_env=False):
        self.calls.append((argv, cwd, env, replace_env))
        return self.results.pop(0)


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


def test_delete_branch_raises_a_clear_error_on_failure():
    run = RecordingRun(CommandResult(1, "", "error: branch 'nf/7-x' not found"))

    with pytest.raises(WorktreeCleanupError, match="could not delete local branch"):
        Git(run=run).delete_branch(Path("/srv/factory/repo"), "nf/7-x")


def test_worktree_cleanup_path_accepts_a_direct_child(tmp_path):
    worktrees = tmp_path / "worktrees"
    worktree = worktrees / "nf-7-x"

    assert worktree_cleanup_path(worktrees, worktree) == worktree.resolve()


def test_worktree_cleanup_path_refuses_a_path_outside_the_worktrees_dir(tmp_path):
    worktrees = tmp_path / "worktrees"
    outside = tmp_path / "repo" / "nf-7-x"

    with pytest.raises(WorktreeCleanupError, match="direct child"):
        worktree_cleanup_path(worktrees, outside)


def test_worktree_cleanup_path_refuses_a_path_containing_dotdot(tmp_path):
    worktrees = tmp_path / "worktrees"

    with pytest.raises(WorktreeCleanupError, match="contains '\\.\\.'"):
        worktree_cleanup_path(worktrees, worktrees / ".." / "repo")


def test_remove_worktree_deletes_as_the_agent_then_prunes(tmp_path):
    worktrees = tmp_path / "worktrees"
    worktree = worktrees / "nf-7-x"
    repo = tmp_path / "repo"
    run = SequenceRun([CommandResult(0, "", ""), CommandResult(0, "", "")])

    Git(run=run, agent_user="factory-agent").remove_worktree(repo, worktree, worktrees)

    target = worktree.resolve()
    assert run.calls == [
        (
            ["sudo", "-n", "-u", "factory-agent", "--", "/usr/bin/rm", "-rf", str(target)],
            "/",
            None,
            False,
        ),
        (["git", "worktree", "prune"], str(repo), None, False),
    ]


def test_remove_worktree_raises_when_the_agent_cannot_delete(tmp_path):
    worktrees = tmp_path / "worktrees"
    run = SequenceRun([CommandResult(1, "", "rm: cannot remove: Permission denied")])

    with pytest.raises(WorktreeCleanupError, match="could not delete worktree"):
        Git(run=run, agent_user="factory-agent").remove_worktree(
            tmp_path / "repo", worktrees / "nf-7-x", worktrees
        )

    assert len(run.calls) == 1


def test_remove_worktree_raises_when_prune_fails(tmp_path):
    worktrees = tmp_path / "worktrees"
    run = SequenceRun([CommandResult(0, "", ""), CommandResult(1, "", "fatal: prune failed")])

    with pytest.raises(WorktreeCleanupError, match="worktree prune failed"):
        Git(run=run, agent_user="factory-agent").remove_worktree(
            tmp_path / "repo", worktrees / "nf-7-x", worktrees
        )


def test_remove_worktree_requires_the_agent_user(tmp_path):
    worktrees = tmp_path / "worktrees"
    run = RecordingRun()

    with pytest.raises(WorktreeCleanupError, match="FACTORY_AGENT_USER"):
        Git(run=run).remove_worktree(tmp_path / "repo", worktrees / "nf-7-x", worktrees)

    assert run.calls == []


def test_create_agent_cleanup_probe_uses_the_check_script_as_agent(tmp_path):
    worktree = tmp_path / "worktrees" / "nf-7-x"
    scripts = worktree / "backend" / "scripts"
    scripts.mkdir(parents=True)
    check = scripts / "check.sh"
    check.write_text("#!/bin/sh\n")
    probe = worktree / "backend" / ".cleanup-probe"
    run = RecordingRun()

    result = Git(
        run=run,
        agent_user="factory-agent",
        agent_home="/home/factory-agent",
        base_env={"PATH": "/usr/bin", "HOME": "/home/factory", "LANG": "C"},
    ).create_agent_cleanup_probe(worktree)

    assert result == probe
    assert check.read_text() == CLEANUP_PROBE_SCRIPT
    assert check.stat().st_mode & 0o777 == 0o755
    argv, cwd, env, replace_env = run.calls[0]
    assert argv == [
        "sudo",
        "-n",
        "--preserve-env=PATH,HOME,LANG,SECRET_KEY,DEBUG,ALLOWED_HOSTS,REDIS_URL,PYTEST_ADDOPTS",
        "-u",
        "factory-agent",
        "--",
        str(check),
    ]
    assert cwd == str(scripts)
    assert replace_env is True
    assert env["HOME"] == "/home/factory-agent"
    assert env["PYTEST_ADDOPTS"] == "-p no:cacheprovider"
    assert "mkdir -m 0770" in CLEANUP_PROBE_SCRIPT
    assert "chgrp" in CLEANUP_PROBE_SCRIPT
    assert 'mv "$probe" "$worktree/backend/.cleanup-probe"' in CLEANUP_PROBE_SCRIPT


def test_create_agent_cleanup_probe_raises_on_failure(tmp_path):
    worktree = tmp_path / "worktrees" / "nf-7-x"
    (worktree / "backend" / "scripts").mkdir(parents=True)
    run = RecordingRun(CommandResult(1, "", "probe failed"))

    with pytest.raises(WorktreeCleanupError, match="could not create the cleanup probe"):
        Git(run=run, agent_user="factory-agent").create_agent_cleanup_probe(worktree)


def test_create_agent_cleanup_probe_requires_the_agent_user(tmp_path):
    run = RecordingRun()

    with pytest.raises(WorktreeCleanupError, match="FACTORY_AGENT_USER"):
        Git(run=run).create_agent_cleanup_probe(tmp_path / "worktrees" / "nf-7-x")

    assert run.calls == []


def test_verify_no_leaked_worktrees_accepts_only_live_entries(tmp_path):
    worktrees = tmp_path / "worktrees"
    live = worktrees / "nf-7-x"
    leaked = worktrees / "nf-6-old"
    live.mkdir(parents=True)
    leaked.mkdir()
    stdout = f"worktree {live.resolve()}\nbranch refs/heads/nf/7-x\n"
    run = RecordingRun(CommandResult(0, stdout, ""))

    with pytest.raises(WorktreeCleanupError, match="nf-6-old"):
        Git(run=run).verify_no_leaked_worktrees(tmp_path / "repo", worktrees)


def test_verify_no_leaked_worktrees_passes_when_every_entry_is_live(tmp_path):
    worktrees = tmp_path / "worktrees"
    live = worktrees / "nf-7-x"
    live.mkdir(parents=True)
    stdout = f"worktree {live.resolve()}\nbranch refs/heads/nf/7-x\n"
    run = RecordingRun(CommandResult(0, stdout, ""))

    Git(run=run).verify_no_leaked_worktrees(tmp_path / "repo", worktrees)


def test_verify_no_leaked_worktrees_raises_when_listing_fails(tmp_path):
    worktrees = tmp_path / "worktrees"
    worktrees.mkdir()
    run = RecordingRun(CommandResult(1, "", "not a git repository"))

    with pytest.raises(WorktreeCleanupError, match="could not list git worktrees"):
        Git(run=run).verify_no_leaked_worktrees(tmp_path / "repo", worktrees)


def test_live_worktree_paths_parses_the_porcelain_list(tmp_path):
    first = tmp_path / "repo"
    second = tmp_path / "worktrees" / "nf-7-x"
    stdout = (
        f"worktree {first}\nHEAD abc\nbranch refs/heads/main\n\n"
        f"worktree {second}\nHEAD def\nbranch refs/heads/nf/7-x\n"
    )
    run = RecordingRun(CommandResult(0, stdout, ""))

    assert Git(run=run).live_worktree_paths(first) == {first.resolve(), second.resolve()}


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
        "--preserve-env=PATH,HOME,LANG,DATABASE_URL,SECRET_KEY,DEBUG,ALLOWED_HOSTS,REDIS_URL,PYTEST_ADDOPTS",
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
