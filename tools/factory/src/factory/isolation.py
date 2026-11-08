"""Verify the agent user cannot reach the factory's secrets or protected paths.

The factory runs OpenCode as a separate unprivileged ``factory-agent`` user.
Before any unattended run, we prove that user cannot read the GitHub App
private key, the secrets file or the SSH deploy key — even via a shell
(``cat``) — because the model drives arbitrary bash. We also prove it cannot
write to the factory tree or the repo's git hooks.

The check fails closed: a positive control must work first, and any result
other than a clean "unreadable"/"not writable" aborts the run.
"""

from __future__ import annotations

from pathlib import Path

from .config import Settings
from .credentials import private_key_path
from .shell import CommandResult, RunCommand, run_command

POSITIVE_CONTROL_PATH = Path("/etc/hostname")
CAT = "/usr/bin/cat"
TEST = "/usr/bin/test"


class IsolationError(RuntimeError):
    """Raised when the agent user can read or write something it must not."""


def sensitive_paths(settings: Settings) -> list[Path]:
    """Files the agent user must not be able to read."""
    paths = [settings.secrets_file, settings.deploy_key]
    key_path = private_key_path(settings.github_private_key)
    if key_path is not None:
        paths.append(key_path)
    return paths


def write_protected_paths(settings: Settings) -> list[Path]:
    """Paths the agent user must not be able to write to."""
    return [
        settings.repo_dir.parent,
        settings.repo_dir,
        settings.repo_dir / ".git" / "hooks",
    ]


def _sudo(agent_user: str, argv: list[str]) -> list[str]:
    return ["sudo", "-n", "-u", agent_user, "--", *argv]


def _permission_denied(result: CommandResult) -> bool:
    return "permission denied" in result.stderr.lower()


def _fail(agent_user: str, detail: str) -> IsolationError:
    return IsolationError(f"isolation check could not be proven for {agent_user!r}: {detail}")


def verify_isolation(
    *,
    agent_user: str,
    paths: list[Path],
    write_paths: list[Path] | None = None,
    run: RunCommand = run_command,
) -> None:
    """Fail unless ``agent_user`` cannot read ``paths`` or write ``write_paths``."""
    if not agent_user:
        return

    control = run(
        _sudo(agent_user, [CAT, str(POSITIVE_CONTROL_PATH)]),
        cwd="/",
        timeout=60,
    )
    if control.exit_code != 0:
        raise _fail(
            agent_user,
            f"positive control failed reading {POSITIVE_CONTROL_PATH}: "
            f"{control.stderr.strip() or control.exit_code}",
        )

    for path in paths:
        result = run(_sudo(agent_user, [CAT, "-n", str(path)]), cwd="/", timeout=60)
        if result.exit_code == 0:
            raise IsolationError(
                f"agent user {agent_user!r} can read {path}; tighten its permissions."
            )
        if not _permission_denied(result):
            raise _fail(
                agent_user,
                f"unexpected error reading {path}: {result.stderr.strip() or result.exit_code}",
            )

    for path in write_paths or []:
        result = run(_sudo(agent_user, [TEST, "-w", str(path)]), cwd="/", timeout=60)
        if result.exit_code == 0:
            raise IsolationError(
                f"agent user {agent_user!r} can write to {path}; tighten its permissions."
            )
        if result.exit_code != 1:
            raise _fail(
                agent_user,
                f"unexpected error testing write access to {path}: "
                f"{result.stderr.strip() or result.exit_code}",
            )
