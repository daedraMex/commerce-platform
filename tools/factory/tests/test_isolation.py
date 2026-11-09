import os
from pathlib import Path

import pytest

from factory.config import Settings
from factory.isolation import (
    IsolationError,
    repo_tree_violations,
    sensitive_paths,
    verify_isolation,
    write_protected_paths,
)
from factory.shell import CommandResult


def make_settings(tmp_path, *, private_key=None):
    return Settings(
        factory_model="m",
        factory_strong_model="s",
        repo="r",
        max_tickets=1,
        attempts=5,
        repo_dir=tmp_path / "repo",
        worktrees_dir=tmp_path / "worktrees",
        logs_dir=tmp_path / "logs",
        time_limit_seconds=60,
        keep_days=14,
        telegram_bot_token=None,
        telegram_chat_id=None,
        github_app_id="1",
        github_private_key=private_key,
        github_installation_id="2",
        agent_user="factory-agent",
        secrets_file=tmp_path / "secrets.env",
        deploy_key=tmp_path / ".ssh" / "commerce_deploy",
    )


class FakeRun:
    def __init__(
        self,
        *,
        control_exit=0,
        control_stderr="",
        read_exit=1,
        read_stderr="cat: target: Permission denied",
        write_exit=1,
        write_stderr="",
    ):
        self.control_exit = control_exit
        self.control_stderr = control_stderr
        self.read_exit = read_exit
        self.read_stderr = read_stderr
        self.write_exit = write_exit
        self.write_stderr = write_stderr
        self.calls = []

    def __call__(self, argv, cwd, *, timeout, env=None):
        self.calls.append(argv)
        if argv[-1] == "/etc/hostname":
            return CommandResult(self.control_exit, "", self.control_stderr)
        if argv[-3] == "/usr/bin/test":
            return CommandResult(self.write_exit, "", self.write_stderr)
        return CommandResult(self.read_exit, "", self.read_stderr)


def test_sensitive_paths_are_files_not_directories(tmp_path):
    key = tmp_path / "xolo.pem"
    key.write_text("key")
    settings = make_settings(tmp_path, private_key=str(key))

    paths = sensitive_paths(settings)

    assert paths == [tmp_path / "secrets.env", tmp_path / ".ssh" / "commerce_deploy", key]
    assert all(not path.is_dir() for path in paths)


def test_sensitive_paths_omits_key_when_not_a_file(tmp_path):
    paths = sensitive_paths(make_settings(tmp_path, private_key="-----BEGIN PRIVATE KEY-----"))
    assert len(paths) == 2


def test_write_protected_paths_cover_factory_repo_and_hooks(tmp_path):
    settings = make_settings(tmp_path)
    assert write_protected_paths(settings) == [
        tmp_path,
        tmp_path / "repo",
        tmp_path / "repo" / ".git" / "hooks",
    ]


def test_verify_isolation_passes_when_paths_are_permission_denied(tmp_path):
    run = FakeRun()

    verify_isolation(
        agent_user="factory-agent",
        paths=[tmp_path / "secrets.env"],
        write_paths=[tmp_path / "repo"],
        run=run,
    )


def test_verify_isolation_raises_when_path_readable(tmp_path):
    run = FakeRun(read_exit=0)

    with pytest.raises(IsolationError, match="can read"):
        verify_isolation(agent_user="factory-agent", paths=[tmp_path / "secrets.env"], run=run)


def test_verify_isolation_aborts_when_positive_control_fails(tmp_path):
    run = FakeRun(control_exit=1, control_stderr="sudo: a password is required")

    with pytest.raises(IsolationError, match="positive control"):
        verify_isolation(agent_user="factory-agent", paths=[tmp_path / "secrets.env"], run=run)


def test_verify_isolation_aborts_on_unexpected_read_error(tmp_path):
    run = FakeRun(read_exit=1, read_stderr="cat: /secret: No such file or directory")

    with pytest.raises(IsolationError, match="unexpected error"):
        verify_isolation(agent_user="factory-agent", paths=[tmp_path / "secrets.env"], run=run)


def test_verify_isolation_raises_when_path_writable(tmp_path):
    run = FakeRun(write_exit=0)

    with pytest.raises(IsolationError, match="can write"):
        verify_isolation(
            agent_user="factory-agent",
            paths=[],
            write_paths=[tmp_path / "repo"],
            run=run,
        )


def test_verify_isolation_aborts_on_unexpected_write_error(tmp_path):
    run = FakeRun(write_exit=2, write_stderr="test: permission denied")

    with pytest.raises(IsolationError, match="unexpected error"):
        verify_isolation(
            agent_user="factory-agent",
            paths=[],
            write_paths=[tmp_path / "repo"],
            run=run,
        )


def test_verify_isolation_skips_when_no_agent_user(tmp_path):
    run = FakeRun()

    verify_isolation(agent_user="", paths=[tmp_path / "secrets.env"], run=run)

    assert run.calls == []


def make_repo_tree(tmp_path):
    repo = tmp_path / "repo"
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(parents=True)
    (repo / "README.md").write_text("ok\n")
    (repo / ".git" / "config").write_text("[core]\n")
    return repo


def test_repo_tree_is_clean_when_nothing_belongs_to_the_agent(tmp_path):
    repo = make_repo_tree(tmp_path)

    violations = repo_tree_violations(
        repo,
        agent_user="factory-agent",
        agent_uid=os.getuid() + 100000,
        agent_gids=set(),
    )

    assert violations == []


def test_repo_tree_flags_paths_owned_by_the_agent(tmp_path):
    repo = make_repo_tree(tmp_path)

    violations = repo_tree_violations(
        repo,
        agent_user="factory-agent",
        agent_uid=os.getuid(),
        agent_gids=set(),
        limit=100,
    )

    assert repo / "README.md" in violations
    assert repo / ".git" / "config" in violations


def test_repo_tree_flags_paths_in_a_group_the_agent_belongs_to(tmp_path):
    repo = make_repo_tree(tmp_path)

    violations = repo_tree_violations(
        repo,
        agent_user="factory-agent",
        agent_uid=os.getuid() + 100000,
        agent_gids={os.getgid()},
        limit=100,
    )

    assert repo / "README.md" in violations
    assert repo / ".git" / "config" in violations


def test_repo_tree_allows_a_symlink_owned_by_factory(tmp_path):
    repo = make_repo_tree(tmp_path)
    link = repo / "README.link"
    os.symlink("README.md", link)

    violations = repo_tree_violations(
        repo,
        agent_user="factory-agent",
        agent_uid=os.getuid() + 100000,
        agent_gids=set(),
    )

    assert violations == []


def test_repo_tree_flags_a_symlink_owned_by_the_agent(tmp_path):
    repo = make_repo_tree(tmp_path)
    link = repo / "README.link"
    os.symlink("README.md", link)

    violations = repo_tree_violations(
        repo,
        agent_user="factory-agent",
        agent_uid=os.getuid(),
        agent_gids=set(),
        limit=100,
    )

    assert link in violations


def test_repo_tree_does_not_follow_symlinked_directories(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    bad = outside / "bad.txt"
    bad.write_text("x")
    bad.chmod(0o666)
    repo = make_repo_tree(tmp_path)
    os.symlink(outside, repo / "outside-link", target_is_directory=True)

    violations = repo_tree_violations(
        repo,
        agent_user="factory-agent",
        agent_uid=os.getuid() + 100000,
        agent_gids=set(),
        limit=100,
    )

    assert bad not in violations
    assert violations == []


def test_repo_tree_still_flags_world_writable_paths_next_to_symlinks(tmp_path):
    repo = make_repo_tree(tmp_path)
    os.symlink("README.md", repo / "README.link")
    world_writable = repo / "world.txt"
    world_writable.write_text("x")
    world_writable.chmod(0o666)

    violations = repo_tree_violations(
        repo,
        agent_user="factory-agent",
        agent_uid=os.getuid() + 100000,
        agent_gids=set(),
    )

    assert violations == [world_writable]


def test_repo_tree_flags_setgid_directories_in_an_agent_group(tmp_path):
    repo = make_repo_tree(tmp_path)
    setgid_dir = repo / "shared"
    setgid_dir.mkdir()
    setgid_dir.chmod(0o2755)

    violations = repo_tree_violations(
        repo,
        agent_user="factory-agent",
        agent_uid=os.getuid() + 100000,
        agent_gids={os.getgid()},
        limit=100,
    )

    assert setgid_dir in violations


def test_repo_tree_reports_only_the_requested_number_of_paths(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for number in range(10):
        path = repo / f"{number}.txt"
        path.write_text("x")
        path.chmod(0o666)

    violations = repo_tree_violations(
        repo,
        agent_user="factory-agent",
        agent_uid=os.getuid() + 100000,
        agent_gids=set(),
        limit=3,
    )

    assert len(violations) == 3


def test_verify_isolation_fails_for_an_unsafe_repo_tree(tmp_path, monkeypatch):
    run = FakeRun()
    unsafe = tmp_path / "repo" / "shared"
    monkeypatch.setattr(
        "factory.isolation.repo_tree_violations",
        lambda *_args, **_kwargs: [unsafe],
    )

    with pytest.raises(IsolationError, match="repo tree") as caught:
        verify_isolation(
            agent_user="factory-agent",
            paths=[],
            repo_dir=tmp_path / "repo",
            run=run,
        )

    assert str(unsafe) in str(caught.value)


def test_verify_isolation_uses_positive_control_and_non_interactive_sudo(tmp_path):
    run = FakeRun()

    verify_isolation(
        agent_user="factory-agent",
        paths=[Path("/secret")],
        write_paths=[Path("/srv/factory/repo")],
        run=run,
    )

    assert run.calls == [
        ["sudo", "-n", "-u", "factory-agent", "--", "/usr/bin/cat", "/etc/hostname"],
        ["sudo", "-n", "-u", "factory-agent", "--", "/usr/bin/cat", "-n", "/secret"],
        ["sudo", "-n", "-u", "factory-agent", "--", "/usr/bin/test", "-w", "/srv/factory/repo"],
    ]
