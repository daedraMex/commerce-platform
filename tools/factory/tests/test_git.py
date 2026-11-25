from pathlib import Path

import pytest

from factory.areas import AREAS, BACKEND, CONSOLE
from factory.git import (
    BOT_COMMIT_NAME,
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
from factory.runner import TEST_SETTINGS, AgentSandboxError
from factory.shell import CommandResult, CommandTimeout


class RecordingRun:
    """Answer like the machine: pkill exits 1 once no agent process is left."""

    def __init__(self, result=None):
        self.result = result or CommandResult(exit_code=0, stdout="", stderr="")
        self.calls = []

    def __call__(self, argv, cwd, *, timeout, env=None, replace_env=False):
        self.calls.append((argv, cwd, env, replace_env))
        if "/usr/bin/pkill" in argv:
            return CommandResult(exit_code=1, stdout="", stderr="")
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


NOTHING_TO_KILL = CommandResult(1, "", "")  # pkill: no agent process matched
AGENT_PKILL = (
    ["sudo", "-n", "-u", "factory-agent", "/usr/bin/pkill", "-KILL", "-u", "factory-agent"],
    "/",
    None,
    False,
)


def test_remove_worktree_kills_agent_processes_then_deletes_as_the_agent_then_prunes(tmp_path):
    worktrees = tmp_path / "worktrees"
    worktree = worktrees / "nf-7-x"
    repo = tmp_path / "repo"
    run = SequenceRun([NOTHING_TO_KILL, CommandResult(0, "", ""), CommandResult(0, "", "")])

    Git(run=run, agent_user="factory-agent").remove_worktree(repo, worktree, worktrees)

    target = worktree.resolve()
    assert run.calls == [
        AGENT_PKILL,
        (
            ["sudo", "-n", "-u", "factory-agent", "--", "/usr/bin/rm", "-rf", str(target)],
            "/",
            None,
            False,
        ),
        (["git", "worktree", "prune"], str(repo), None, False),
    ]


def test_remove_worktree_repeats_the_kill_while_agent_processes_remain(tmp_path):
    """A uv still installing into .venv made rm fail with "Directory not empty" (#194)."""
    worktrees = tmp_path / "worktrees"
    run = SequenceRun(
        [
            CommandResult(0, "", ""),  # killed something
            NOTHING_TO_KILL,
            CommandResult(0, "", ""),
            CommandResult(0, "", ""),
        ]
    )

    Git(run=run, agent_user="factory-agent").remove_worktree(
        tmp_path / "repo", worktrees / "preflight-42", worktrees
    )

    assert [call[0][4] for call in run.calls[:3]] == ["/usr/bin/pkill", "/usr/bin/pkill", "--"]


def test_remove_worktree_deletes_nothing_when_the_agent_cleanup_is_refused(tmp_path):
    worktrees = tmp_path / "worktrees"
    run = SequenceRun([CommandResult(1, "", "sudo: a password is required")])

    with pytest.raises(AgentSandboxError, match="refused by sudo"):
        Git(run=run, agent_user="factory-agent").remove_worktree(
            tmp_path / "repo", worktrees / "nf-7-x", worktrees
        )

    assert run.calls == [AGENT_PKILL]


def test_remove_worktree_raises_when_the_agent_cannot_delete(tmp_path):
    worktrees = tmp_path / "worktrees"
    run = SequenceRun(
        [NOTHING_TO_KILL, CommandResult(1, "", "rm: cannot remove: Permission denied")]
    )

    with pytest.raises(WorktreeCleanupError, match="could not delete worktree"):
        Git(run=run, agent_user="factory-agent").remove_worktree(
            tmp_path / "repo", worktrees / "nf-7-x", worktrees
        )

    assert len(run.calls) == 2


def test_remove_worktree_raises_when_prune_fails(tmp_path):
    worktrees = tmp_path / "worktrees"
    run = SequenceRun(
        [NOTHING_TO_KILL, CommandResult(0, "", ""), CommandResult(1, "", "fatal: prune failed")]
    )

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


def test_create_agent_cleanup_probe_runs_the_installed_script_as_agent(tmp_path):
    worktree = tmp_path / "worktrees" / "nf-7-x"
    scripts = worktree / "backend" / "scripts"
    scripts.mkdir(parents=True)
    check = scripts / "check.sh"
    check.write_text("#!/bin/sh\n")
    run = RecordingRun()

    result = Git(
        run=run,
        agent_user="factory-agent",
        agent_home="/home/factory-agent",
        base_env={"PATH": "/usr/bin", "HOME": "/home/factory", "LANG": "C"},
    ).create_agent_cleanup_probe(worktree)

    assert result == worktree / "backend" / ".cleanup-probe"
    assert check.read_text() == "#!/bin/sh\n"
    argv, cwd, _env, _replace_env = run.calls[0]
    assert argv == [
        "sudo",
        "-n",
        "-u",
        "factory-agent",
        "--",
        "/usr/local/lib/factory/cleanup-probe",
        str(worktree),
    ]
    assert cwd == "/"


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


def test_preflight_leftovers_lists_only_preflight_entries(tmp_path):
    worktrees = tmp_path / "worktrees"
    for name in ("preflight-9", "preflight-10", "nf-66-x", "notes"):
        (worktrees / name).mkdir(parents=True)

    leftovers = Git(run=RecordingRun()).preflight_leftovers(worktrees)

    assert leftovers == [worktrees / "preflight-10", worktrees / "preflight-9"]


def test_preflight_leftovers_without_a_worktrees_directory(tmp_path):
    assert Git(run=RecordingRun()).preflight_leftovers(tmp_path / "missing") == []


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


def write_script(worktree: Path, area) -> Path:
    script = worktree / area.script
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("#!/bin/sh\n")
    return script


def test_check_runs_the_script_as_the_agent_user_without_secrets(tmp_path):
    run = RecordingRun()
    worktree = tmp_path
    script = write_script(worktree, BACKEND)

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
    ).check(worktree, areas=(BACKEND,))

    argv, cwd, env, replace_env = run.calls[0]
    assert argv == [
        "sudo",
        "-n",
        "--preserve-env=PATH,HOME,LANG,DATABASE_URL,SECRET_KEY,DEBUG,ALLOWED_HOSTS,REDIS_URL,PYTEST_ADDOPTS",
        "-u",
        "factory-agent",
        "--",
        str(script),
    ]
    assert cwd == str(worktree / "backend" / "scripts")
    assert replace_env is True
    assert env == {
        "PATH": "/usr/bin",
        "HOME": "/home/factory-agent",
        "LANG": "C",
        "DATABASE_URL": "postgres://db",
        **TEST_SETTINGS,
    }


def test_check_console_env_sets_ci_and_the_playwright_browser_path(tmp_path):
    run = RecordingRun()
    worktree = tmp_path
    script = write_script(worktree, CONSOLE)

    Git(
        run=run,
        agent_user="factory-agent",
        agent_home="/home/factory-agent",
        base_env={
            "PATH": "/usr/local/bin:/usr/bin",
            "HOME": "/home/factory",
            "LANG": "C",
            "DATABASE_URL": "postgres://db",
            "DEEPSEEK_API_KEY": "dk-123",
        },
        port_in_use=lambda _port: False,
    ).check(worktree, areas=(CONSOLE,))

    argv, cwd, env, replace_env = run.calls[0]
    assert argv == [
        "sudo",
        "-n",
        "--preserve-env=PATH,HOME,LANG,CI,PLAYWRIGHT_BROWSERS_PATH",
        "-u",
        "factory-agent",
        "--",
        str(script),
    ]
    assert cwd == str(worktree / "web" / "console" / "scripts")
    assert replace_env is True
    assert env == {
        "PATH": "/usr/local/bin:/usr/bin",
        "HOME": "/home/factory-agent",
        "LANG": "C",
        "CI": "true",
        "PLAYWRIGHT_BROWSERS_PATH": "/home/factory-agent/.cache/ms-playwright",
    }
    assert "SECRET_KEY" not in env
    assert "DEEPSEEK_API_KEY" not in env


def test_check_runs_every_selected_area_in_labeled_output(tmp_path):
    worktree = tmp_path
    write_script(worktree, BACKEND)
    write_script(worktree, CONSOLE)
    results = [
        CommandResult(exit_code=0, stdout="backend ok", stderr=""),
        CommandResult(exit_code=0, stdout="console ok", stderr=""),
    ]
    run = SequenceRun(results)

    result = Git(run=run, port_in_use=lambda _port: False).check(worktree, areas=AREAS)

    assert result.passed is True
    assert result.failed_areas == ()
    assert result.checked_areas == AREAS
    assert len(run.calls) == 2
    assert "=== backend (backend/scripts/check.sh) ===" in result.output
    assert "=== console (web/console/scripts/check.sh) ===" in result.output
    assert "backend ok" in result.output
    assert "console ok" in result.output


def test_check_fails_when_any_area_fails_and_names_the_failing_area(tmp_path):
    worktree = tmp_path
    write_script(worktree, BACKEND)
    write_script(worktree, CONSOLE)
    results = [
        CommandResult(exit_code=0, stdout="backend ok", stderr=""),
        CommandResult(exit_code=1, stdout="1 failed", stderr="boom"),
    ]

    result = Git(run=SequenceRun(results), port_in_use=lambda _port: False).check(
        worktree, areas=AREAS
    )

    assert result.passed is False
    assert result.failed_areas == (CONSOLE,)
    assert "=== console (web/console/scripts/check.sh) ===" in result.output
    assert "1 failed" in result.output
    assert "boom" in result.output


def test_check_skips_an_area_whose_script_is_absent(tmp_path):
    run = RecordingRun()

    result = Git(run=run).check(tmp_path, areas=AREAS)

    assert result.passed is True
    assert result.failed_areas == ()
    assert result.checked_areas == ()
    assert result.skipped_areas == AREAS
    assert run.calls == []
    assert "backend" in result.output
    assert "skipped" in result.output
    assert "console" in result.output


def test_check_maps_the_changed_files_to_areas(tmp_path):
    worktree = tmp_path
    write_script(worktree, BACKEND)
    write_script(worktree, CONSOLE)

    def run(argv, cwd, *, timeout, env=None, replace_env=False):
        run.calls.append(argv)
        if argv[:3] == ["git", "diff", "origin/main...HEAD"]:
            return CommandResult(0, "backend/apps/catalog/views.py\n", "")
        if argv[:3] == ["git", "diff", "HEAD"]:
            return CommandResult(0, "", "")
        if argv[:2] == ["git", "ls-files"]:
            return CommandResult(0, "packages/api-client/openapi.json\n", "")
        return CommandResult(0, "ok", "")

    run.calls = []

    result = Git(run=run, port_in_use=lambda _port: False).check(worktree)

    assert result.passed is True
    script_calls = [argv for argv in run.calls if argv[:1] != ["git"]]
    assert len(script_calls) == 2
    assert script_calls[0][-1] == str(worktree / BACKEND.script)
    assert script_calls[1][-1] == str(worktree / CONSOLE.script)


def test_check_truncates_output_fed_to_the_agent(tmp_path):
    worktree = tmp_path
    write_script(worktree, BACKEND)
    run = RecordingRun(CommandResult(exit_code=1, stdout="x" * 9000, stderr=""))

    result = Git(run=run).check(worktree, areas=(BACKEND,))

    assert result.passed is False
    assert len(result.output) < 9000
    assert result.output.endswith("x" * 100)
    assert "truncated" in result.output


class TimeoutThenRecord:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, cwd, *, timeout, env=None, replace_env=False):
        self.calls.append((argv, cwd, env, replace_env))
        if len(self.calls) == 1:
            raise CommandTimeout("slow")
        return CommandResult(exit_code=1, stdout="", stderr="")


def test_an_interrupted_check_kills_every_agent_process_before_it_propagates(tmp_path):
    write_script(tmp_path, BACKEND)
    calls = []

    def run(argv, cwd, *, timeout, env=None, replace_env=False):
        calls.append(argv)
        if len(calls) == 1:
            raise KeyboardInterrupt
        return CommandResult(exit_code=1, stdout="", stderr="")

    with pytest.raises(KeyboardInterrupt):
        Git(run=run, agent_user="factory-agent").check(tmp_path, areas=(BACKEND,))

    assert "/usr/bin/pkill" in calls[1]


def test_check_on_timeout_runs_the_agent_cleanup_through_sudo(tmp_path):
    worktree = tmp_path
    write_script(worktree, BACKEND)
    run = TimeoutThenRecord()

    result = Git(run=run, agent_user="factory-agent").check(worktree, areas=(BACKEND,))

    assert result.passed is False
    assert result.failed_areas == (BACKEND,)
    assert "timed out" in result.output
    assert run.calls[1] == (
        [
            "sudo",
            "-n",
            "-u",
            "factory-agent",
            "/usr/bin/pkill",
            "-KILL",
            "-u",
            "factory-agent",
        ],
        "/",
        None,
        False,
    )


def test_check_cleans_up_a_busy_console_port_once_then_runs(tmp_path):
    worktree = tmp_path
    write_script(worktree, CONSOLE)
    run = RecordingRun()
    ports = iter([True, False])

    result = Git(
        run=run,
        agent_user="factory-agent",
        port_in_use=lambda _port: next(ports),
    ).check(worktree, areas=(CONSOLE,))

    assert result.passed is True
    assert run.calls[0][0] == [
        "sudo",
        "-n",
        "-u",
        "factory-agent",
        "/usr/bin/pkill",
        "-KILL",
        "-u",
        "factory-agent",
    ]
    script = [
        i for i, call in enumerate(run.calls) if call[0][-1] == str(worktree / CONSOLE.script)
    ]
    assert len(script) == 1
    assert all("/usr/bin/pkill" in call[0] for call in run.calls[: script[0]])


def test_check_fails_with_a_clear_message_when_port_3000_stays_busy(tmp_path):
    worktree = tmp_path
    write_script(worktree, CONSOLE)
    run = RecordingRun()

    result = Git(
        run=run,
        agent_user="factory-agent",
        port_in_use=lambda _port: True,
    ).check(worktree, areas=(CONSOLE,))

    assert result.passed is False
    assert result.failed_areas == (CONSOLE,)
    assert "port 3000 busy" in result.output
    # Only agent cleanups ran (the busy-port one and the final one); never the script.
    assert all(
        call[0][-4:] == ["/usr/bin/pkill", "-KILL", "-u", "factory-agent"] for call in run.calls
    )
    assert all(str(worktree / CONSOLE.script) not in call[0] for call in run.calls)


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


def test_fetch_branch_fetches_the_review_branch():
    run = RecordingRun()
    repo = Path("/srv/factory/repo")

    Git(run=run).fetch_branch(repo, "nf/7-ticket-7")

    assert run.calls == [
        (["git", "fetch", "origin", "nf/7-ticket-7"], str(repo), None, False),
    ]


def test_fetch_branch_raises_when_the_fetch_fails():
    run = RecordingRun(CommandResult(exit_code=128, stdout="", stderr="could not read from remote"))

    with pytest.raises(RuntimeError, match="git fetch failed: could not read from remote"):
        Git(run=run).fetch_branch(Path("/srv/factory/repo"), "nf/7-ticket-7")


def test_create_worktree_from_uses_the_given_base():
    run = RecordingRun()
    repo = Path("/srv/factory/repo")
    worktree = Path("/srv/factory/worktrees/nf-7-ticket-7")

    Git(run=run).create_worktree_from(repo, worktree, "nf/7-ticket-7", "origin/nf/7-ticket-7")

    assert run.calls == [
        (
            [
                "git",
                "worktree",
                "add",
                "-b",
                "nf/7-ticket-7",
                str(worktree),
                "origin/nf/7-ticket-7",
            ],
            str(repo),
            None,
            False,
        ),
    ]


def test_head_sha_reads_rev_parse():
    run = RecordingRun(CommandResult(0, "abc123\n", ""))

    assert Git(run=run).head_sha(Path("/work")) == "abc123"
    assert run.calls[0][0] == ["git", "rev-parse", "HEAD"]


def test_head_sha_raises_when_rev_parse_fails():
    run = RecordingRun(CommandResult(128, "", "fatal: not a git repository"))

    with pytest.raises(RuntimeError, match="could not read HEAD"):
        Git(run=run).head_sha(Path("/work"))


def test_diff_stats_defaults_to_origin_main():
    results = [
        CommandResult(0, "2\t1\tbackend/apps/x/views.py\n", ""),
        CommandResult(0, "", ""),
    ]
    run = SequenceRun(results)

    Git(run=run).diff_stats(Path("/work"))

    assert run.calls[0][0] == ["git", "diff", "origin/main...HEAD", "--numstat"]
    assert run.calls[1][0] == [
        "git",
        "diff",
        "origin/main...HEAD",
        "--diff-filter=A",
        "--name-only",
    ]


def test_diff_stats_since_a_sha_compares_trees_not_merge_bases():
    """A review fix compares the tree at ``since`` with HEAD (two-dot).

    The agent can amend or reset the runner's merge commit, so ``since`` may stop
    being an ancestor of HEAD; a merge-base range would then count everything
    main brought in as the agent's own change.
    """
    results = [
        CommandResult(0, "2\t1\tbackend/apps/x/views.py\n", ""),
        CommandResult(0, "backend/tests/test_x.py\n", ""),
    ]
    run = SequenceRun(results)

    stats = Git(run=run).diff_stats(Path("/work"), since="base123")

    assert stats.files[0].path == "backend/apps/x/views.py"
    assert stats.new_tests == ("backend/tests/test_x.py",)
    assert run.calls[0][0] == ["git", "diff", "base123", "HEAD", "--numstat"]
    assert run.calls[1][0] == [
        "git",
        "diff",
        "base123",
        "HEAD",
        "--diff-filter=A",
        "--name-only",
    ]


def test_git_has_a_single_diff_stats_method():
    assert not hasattr(Git, "diff_stats_since")


def test_merge_main_merges_origin_main_with_the_bot_identity_and_no_hooks():
    run = RecordingRun()
    worktree = Path("/srv/factory/worktrees/nf-7-ticket-7")

    merged = Git(run=run, bot_user_id="353808367").merge_main(worktree)

    assert merged is True
    assert run.calls == [
        (
            [
                "git",
                *commit_identity_args("353808367"),
                "-c",
                "core.hooksPath=/dev/null",
                "merge",
                "--no-edit",
                "--no-ff",
                "origin/main",
            ],
            str(worktree),
            None,
            False,
        ),
    ]


def test_merge_main_aborts_and_reports_a_conflict():
    run = SequenceRun(
        [
            CommandResult(exit_code=1, stdout="CONFLICT (content): Merge conflict", stderr=""),
            CommandResult(exit_code=0, stdout="", stderr=""),
        ]
    )
    worktree = Path("/srv/factory/worktrees/nf-7-ticket-7")

    merged = Git(run=run, bot_user_id="353808367").merge_main(worktree)

    assert merged is False
    assert run.calls[1] == (["git", "merge", "--abort"], str(worktree), None, False)


def test_merge_main_raises_when_the_abort_fails():
    run = SequenceRun(
        [
            CommandResult(exit_code=1, stdout="CONFLICT (content): Merge conflict", stderr=""),
            CommandResult(exit_code=128, stdout="", stderr="no merge to abort"),
        ]
    )

    with pytest.raises(RuntimeError, match="git merge --abort failed: no merge to abort"):
        Git(run=run, bot_user_id="353808367").merge_main(
            Path("/srv/factory/worktrees/nf-7-ticket-7")
        )


def test_remote_branch_exists_asks_ls_remote_with_the_token_scoped_to_the_push():
    run = RecordingRun(CommandResult(0, "abc123\trefs/heads/nf/7-x\n", ""))

    assert Git(run=run).remote_branch_exists(Path("/srv/factory/repo"), "nf/7-x", "TOKEN") is True
    argv, _cwd, env, _replace = run.calls[0]
    assert argv[3:] == ["ls-remote", "--heads", "origin", "refs/heads/nf/7-x"]
    assert env == {"FACTORY_GIT_TOKEN": "TOKEN"}


def test_remote_branch_exists_is_false_when_ls_remote_lists_nothing():
    run = RecordingRun(CommandResult(0, "", ""))

    assert Git(run=run).remote_branch_exists(Path("/srv/factory/repo"), "nf/7-x", "TOKEN") is False


def test_remote_branch_exists_raises_when_ls_remote_fails():
    run = RecordingRun(CommandResult(128, "", "fatal: could not read from remote"))

    with pytest.raises(
        RuntimeError, match="git ls-remote failed: fatal: could not read from remote"
    ):
        Git(run=run).remote_branch_exists(Path("/srv/factory/repo"), "nf/7-x", "TOKEN")


def _git(repo: Path, *args: str) -> str:
    import subprocess

    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "HOME": str(repo),
        "PATH": "/usr/bin:/bin",
    }
    return subprocess.run(
        ["git", *args], cwd=repo, env=env, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_diff_stats_since_ignores_main_files_after_the_agent_amends_the_merge(tmp_path):
    """Real git: the agent amends the runner's merge of main; only its file counts."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("base\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-qb", "nf/7-ticket")
    (repo / "feature.py").write_text("x = 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "ticket")
    _git(repo, "checkout", "-q", "main")
    (repo / ".github").mkdir()
    (repo / ".github" / "ci.yml").write_text("on: push\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "main moves")
    _git(repo, "checkout", "-q", "nf/7-ticket")
    _git(repo, "merge", "-q", "--no-edit", "main")
    since = _git(repo, "rev-parse", "HEAD")
    (repo / "review.txt").write_text("fix\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "--amend", "--no-edit")

    stats = Git().diff_stats(repo, since=since)

    assert [f.path for f in stats.files] == ["review.txt"]


def test_read_ref_file_reads_a_file_from_a_ref_not_the_worktree(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "REVIEW.md").write_text("rules from main\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "rules")
    (repo / "REVIEW.md").write_text("tampered in the worktree\n")

    assert Git().read_ref_file(repo, "main", "REVIEW.md") == "rules from main\n"


def test_review_diff_includes_new_untracked_files(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.py").write_text("a = 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    (repo / "a.py").write_text("a = 2\n")
    (repo / "new.py").write_text("b = 1\n")

    diff = Git().review_diff(repo)

    assert "+a = 2" in diff
    assert "new.py" in diff and "+b = 1" in diff


def test_worktree_fingerprint_changes_when_any_file_changes(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.py").write_text("a = 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    (repo / "a.py").write_text("a = 2\n")
    git = Git()

    before = git.worktree_fingerprint(repo)
    assert git.worktree_fingerprint(repo) == before
    (repo / "a.py").write_text("a = 3\n")
    after_edit = git.worktree_fingerprint(repo)
    (repo / "c.py").write_text("c = 1\n")

    assert after_edit != before
    assert git.worktree_fingerprint(repo) != after_edit


def test_review_changed_files_lists_new_and_changed_paths(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.py").write_text("a = 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    (repo / "a.py").write_text("a = 2\n")
    (repo / "opencode.jsonc").write_text("{}\n")

    assert sorted(Git().review_changed_files(repo)) == ["a.py", "opencode.jsonc"]


def test_check_kills_agent_processes_left_behind_by_the_scripts(tmp_path):
    worktree = tmp_path
    write_script(worktree, BACKEND)
    run = RecordingRun()

    result = Git(run=run, agent_user="factory-agent").check(worktree, areas=(BACKEND,))

    assert result.passed is True
    assert run.calls[-1][0] == [
        "sudo",
        "-n",
        "-u",
        "factory-agent",
        "/usr/bin/pkill",
        "-KILL",
        "-u",
        "factory-agent",
    ]


def test_review_tests_run_through_check_sh_as_the_agent_without_secrets(tmp_path):
    run = RecordingRun()
    script = write_script(tmp_path, BACKEND)

    status, _output = Git(
        run=run,
        agent_user="factory-agent",
        agent_home="/home/factory-agent",
        base_env={"PATH": "/usr/bin", "GH_TOKEN": "secret"},
    ).run_review_tests(tmp_path, ("tests/review/test_review_7_1.py",))

    argv, cwd, env, replace_env = run.calls[0]
    assert status == "held"
    assert argv[:2] == ["sudo", "-n"]
    assert argv[-3:] == [str(script), "--review-tests", "tests/review/test_review_7_1.py"]
    assert "PYTHONDONTWRITEBYTECODE" in argv[2]
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert "GH_TOKEN" not in env
    assert cwd == str(tmp_path / "backend" / "scripts")
    assert replace_env is True


@pytest.mark.parametrize(
    ("exit_code", "status"), [(0, "held"), (1, "broke"), (2, "error"), (5, "error")]
)
def test_review_tests_map_pytest_exit_codes_to_a_verdict(tmp_path, exit_code, status):
    write_script(tmp_path, BACKEND)
    run = RecordingRun(CommandResult(exit_code=exit_code, stdout="out", stderr=""))

    assert (
        Git(run=run).run_review_tests(tmp_path, ("tests/review/test_review_7_1.py",))[0] == status
    )


def test_review_tests_without_a_backend_script_give_no_verdict(tmp_path):
    assert Git(run=RecordingRun()).run_review_tests(tmp_path, ("x",))[0] == "error"


def test_review_tests_are_placed_and_removed_with_their_directory(tmp_path):
    git = Git(run=RecordingRun())
    paths = ("tests/review/test_review_7_1.py", "tests/review/test_review_7_2.py")

    git.place_review_tests(tmp_path, {paths[0]: "a\n", paths[1]: "b\n"})
    assert (tmp_path / "backend" / paths[1]).read_text() == "b\n"

    git.remove_review_tests(tmp_path, paths)
    assert not (tmp_path / "backend" / "tests" / "review").exists()
    assert (tmp_path / "backend" / "tests").is_dir()


def test_interrupted_attack_tests_kill_every_agent_process_before_it_propagates(tmp_path):
    write_script(tmp_path, BACKEND)
    calls = []

    def run(argv, cwd, *, timeout, env=None, replace_env=False):
        calls.append(argv)
        if "--review-tests" in argv:
            raise KeyboardInterrupt
        return CommandResult(exit_code=1, stdout="", stderr="")

    with pytest.raises(KeyboardInterrupt):
        Git(run=run, agent_user="factory-agent").run_review_tests(
            tmp_path, ("tests/review/test_review_7_1.py",)
        )

    attack = next(i for i, argv in enumerate(calls) if "--review-tests" in argv)
    assert "/usr/bin/pkill" in calls[attack + 1]


def test_contract_diff_takes_the_whole_contract_files_as_context(tmp_path):
    run = RecordingRun(CommandResult(0, "diff --git a/docs/contracts/photos.md ...", ""))

    out = Git(run=run).contract_diff(tmp_path)

    assert out.startswith("diff --git a/docs/contracts/photos.md")
    diff_call = next(call for call in run.calls if call[0][:3] == ["git", "diff", "--cached"])
    assert "--unified=100000" in diff_call[0]
    assert diff_call[0][-3:] == ["origin/main", "--", "docs/contracts/"]
