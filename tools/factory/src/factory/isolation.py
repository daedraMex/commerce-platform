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

import os
import pwd
import stat
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


def repo_tree_violations(
    repo_dir: Path,
    *,
    agent_user: str,
    agent_uid: int | None = None,
    agent_gids: set[int] | None = None,
    limit: int = 5,
) -> list[Path]:
    """Walk ``repo_dir`` and return the first unsafe paths for the agent user.

    Runs as the factory user with plain ``os.walk`` and ``lstat``: a path is
    unsafe when it is owned by ``factory-agent``, belongs to a group that user
    is in, is world-writable, or is a setgid directory in an agent group.
    """
    if agent_uid is None or agent_gids is None:
        entry = pwd.getpwnam(agent_user)
        if agent_uid is None:
            agent_uid = entry.pw_uid
        if agent_gids is None:
            agent_gids = set(os.getgrouplist(agent_user, entry.pw_gid))

    violations: list[Path] = []

    def unsafe(path: Path) -> bool:
        try:
            info = os.lstat(path)
        except OSError:
            return False
        mode = info.st_mode
        agent_group = info.st_gid in agent_gids
        setgid_agent_group = stat.S_ISDIR(mode) and bool(mode & stat.S_ISGID) and agent_group
        if info.st_uid == agent_uid or agent_group or mode & stat.S_IWOTH or setgid_agent_group:
            violations.append(path)
        return len(violations) >= limit

    if unsafe(repo_dir):
        return violations
    for root, dirnames, filenames in os.walk(repo_dir):
        for name in (*dirnames, *filenames):
            if unsafe(Path(root) / name):
                return violations
    return violations


def verify_isolation(
    *,
    agent_user: str,
    paths: list[Path],
    write_paths: list[Path] | None = None,
    repo_dir: Path | None = None,
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

    if repo_dir is not None:
        violations = repo_tree_violations(repo_dir, agent_user=agent_user)
        if violations:
            shown = ", ".join(str(path) for path in violations)
            raise IsolationError(
                f"repo tree at {repo_dir} is unsafe for agent user {agent_user!r}: {shown}"
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
