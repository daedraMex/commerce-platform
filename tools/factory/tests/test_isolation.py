from pathlib import Path

import pytest

from factory.config import Settings
from factory.isolation import IsolationError, sensitive_paths, verify_isolation
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
        xolo_config_dir=tmp_path / ".config" / "xolo-bot",
    )


def test_sensitive_paths_includes_secrets_config_and_key(tmp_path):
    key = tmp_path / "xolo.pem"
    key.write_text("key")
    paths = sensitive_paths(make_settings(tmp_path, private_key=str(key)))
    assert (tmp_path / "secrets.env") in paths
    assert (tmp_path / ".config" / "xolo-bot") in paths
    assert key in paths


def test_sensitive_paths_omits_key_when_not_a_file(tmp_path):
    paths = sensitive_paths(make_settings(tmp_path, private_key="-----BEGIN PRIVATE KEY-----"))
    assert len(paths) == 2


def test_verify_isolation_passes_when_paths_unreadable(tmp_path):
    def run(argv, cwd, *, timeout, env=None):
        return CommandResult(exit_code=1, stdout="", stderr="Permission denied")

    verify_isolation(agent_user="factory-agent", paths=[tmp_path / "secrets.env"], run=run)


def test_verify_isolation_raises_when_path_readable(tmp_path):
    def run(argv, cwd, *, timeout, env=None):
        return CommandResult(exit_code=0, stdout="SECRET", stderr="")

    with pytest.raises(IsolationError, match="can read"):
        verify_isolation(agent_user="factory-agent", paths=[tmp_path / "secrets.env"], run=run)


def test_verify_isolation_skips_when_no_agent_user(tmp_path):
    calls = []

    def run(argv, cwd, *, timeout, env=None):
        calls.append(argv)
        return CommandResult(exit_code=0, stdout="", stderr="")

    verify_isolation(agent_user="", paths=[tmp_path / "secrets.env"], run=run)
    assert calls == []


def test_verify_isolation_uses_sudo_cat(tmp_path):
    seen = []

    def run(argv, cwd, *, timeout, env=None):
        seen.append(argv)
        return CommandResult(exit_code=1, stdout="", stderr="")

    verify_isolation(agent_user="factory-agent", paths=[Path("/secret")], run=run)
    assert seen[0] == ["sudo", "-u", "factory-agent", "--", "cat", "/secret"]
