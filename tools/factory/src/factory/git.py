"""The factory's one git port: the checkout plus what runs as the agent in it.

``Git`` is a ``GitRepo`` (git on the checkout and its worktrees) that also owns
an ``AreaChecks`` (check scripts and attack tests as the agent) and a
``WorktreeCleanup`` (deleting worktrees as their owner). Callers and fakes keep
one object; each part lives and is tested in its own module (#147).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from .area_checks import (
    CHECK_TIMEOUT_SECONDS,
    REVIEW_TESTS_TIMEOUT_SECONDS,
    AreaChecks,
    CheckResult,
    describe_exit,
    port_in_use,
)
from .areas import Area
from .git_repo import (
    BOT_COMMIT_EMAIL_DOMAIN,
    BOT_COMMIT_NAME,
    MIN_GIT_VERSION,
    TOKEN_CREDENTIAL_HELPER,
    GitIdentityError,
    GitRepo,
    GitVersionError,
    bot_commit_email,
    commit_identity_args,
    parse_git_version,
    verify_git_version,
)
from .shell import RunCommand, run_command
from .worktree_cleanup import (
    CLEANUP_PROBE_PATH,
    CLEANUP_PROBE_RELATIVE,
    CLEANUP_PROBE_REPO_RELATIVE,
    PREFLIGHT_PREFIX,
    RM_BIN,
    WorktreeCleanup,
    WorktreeCleanupError,
    worktree_cleanup_path,
)

__all__ = [
    "BOT_COMMIT_EMAIL_DOMAIN",
    "BOT_COMMIT_NAME",
    "CHECK_TIMEOUT_SECONDS",
    "CLEANUP_PROBE_PATH",
    "CLEANUP_PROBE_RELATIVE",
    "CLEANUP_PROBE_REPO_RELATIVE",
    "MIN_GIT_VERSION",
    "PREFLIGHT_PREFIX",
    "REVIEW_TESTS_TIMEOUT_SECONDS",
    "RM_BIN",
    "TOKEN_CREDENTIAL_HELPER",
    "AreaChecks",
    "CheckResult",
    "Git",
    "GitIdentityError",
    "GitRepo",
    "GitVersionError",
    "WorktreeCleanup",
    "WorktreeCleanupError",
    "bot_commit_email",
    "commit_identity_args",
    "describe_exit",
    "parse_git_version",
    "port_in_use",
    "verify_git_version",
    "worktree_cleanup_path",
]


class Git(GitRepo):
    def __init__(
        self,
        run: RunCommand = run_command,
        *,
        agent_user: str | None = None,
        agent_home: str | None = None,
        bot_user_id: str | None = None,
        base_env: dict[str, str] | None = None,
        port_in_use: Callable[[int], bool] = port_in_use,
        logs_dir: Path | None = None,
    ):
        super().__init__(run, bot_user_id=bot_user_id)
        self.checks = AreaChecks(
            run,
            # Looked up per call, as when check was a Git method.
            changed_files=lambda worktree: self.changed_files(worktree),
            agent_user=agent_user,
            agent_home=agent_home,
            base_env=base_env if base_env is not None else dict(os.environ),
            port_in_use=port_in_use,
            logs_dir=logs_dir,
        )
        self.cleanup = WorktreeCleanup(run, agent_user=agent_user)

    def check(self, worktree: Path, *, areas: tuple[Area, ...] | None = None) -> CheckResult:
        return self.checks.check(worktree, areas=areas)

    def run_review_tests(self, worktree: Path, files: tuple[str, ...]) -> tuple[str, str]:
        return self.checks.run_review_tests(worktree, files)

    def place_review_tests(self, worktree: Path, tests: dict[str, str]) -> None:
        self.checks.place_review_tests(worktree, tests)

    def remove_review_tests(self, worktree: Path, relpaths: tuple[str, ...]) -> None:
        self.checks.remove_review_tests(worktree, relpaths)

    def preflight_leftovers(self, worktrees_dir: Path) -> list[Path]:
        return self.cleanup.preflight_leftovers(worktrees_dir)

    def create_agent_cleanup_probe(self, worktree: Path) -> Path:
        return self.cleanup.create_agent_cleanup_probe(worktree)

    def remove_worktree(self, repo_dir: Path, worktree: Path, worktrees_dir: Path) -> None:
        self.cleanup.remove_worktree(repo_dir, worktree, worktrees_dir)
