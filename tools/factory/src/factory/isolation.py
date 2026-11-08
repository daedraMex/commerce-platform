"""Verify the agent user cannot reach the factory's secrets.

The factory runs OpenCode as a separate unprivileged ``factory-agent`` user.
Before any unattended run, we prove that user cannot read the GitHub App
private key, the secrets file, or the xolo-bot config directory — even via a
shell (``cat``) — because the model drives arbitrary bash.
"""

from __future__ import annotations

from pathlib import Path

from .config import Settings
from .credentials import private_key_path
from .shell import RunCommand, run_command


class IsolationError(RuntimeError):
    """Raised when the agent user can read something it must not."""


def sensitive_paths(settings: Settings) -> list[Path]:
    paths = [settings.secrets_file, settings.xolo_config_dir]
    key_path = private_key_path(settings.github_private_key)
    if key_path is not None:
        paths.append(key_path)
    return paths


def verify_isolation(
    *,
    agent_user: str,
    paths: list[Path],
    run: RunCommand = run_command,
) -> None:
    """Fail if ``agent_user`` can read any of ``paths`` via ``cat``."""
    if not agent_user:
        return
    for path in paths:
        result = run(
            ["sudo", "-n", "-u", agent_user, "--", "/usr/bin/cat", "-n", str(path)],
            cwd="/",
            timeout=60,
        )
        if result.exit_code == 0:
            raise IsolationError(
                f"agent user {agent_user!r} can read {path}; tighten its permissions."
            )
